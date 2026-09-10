"""Bounded read-side transport. Caller supplies a server-session user credential.

This module has no originate, agent-state mutation, retry, or provider transport.
Schemas are generated from the pinned platform authority.
"""
import json
import math
import re
import ssl
import time
import urllib.error
import urllib.request
from datetime import datetime
from pathlib import Path

SCHEMA = json.loads(Path(__file__).with_name('calling_schema.json').read_text())
MAX_BYTES = 262144
ORIGIN = 'https://api.codestra.co'
UUID = re.compile(r'\A[0-9a-fA-F]{8}-(?:[0-9a-fA-F]{4}-){3}[0-9a-fA-F]{12}\Z')


class RealtimeUnavailable(Exception):
    """Redacted, bounded failure; never contains credentials or a remote body."""


def _require(condition):
    if not condition:
        raise RealtimeUnavailable('Calling integration validation failed.')


def validate(value, schema):
    kind = schema.get('type')
    if kind == 'object':
        _require(type(value) is dict)
        _require(set(schema.get('required', [])) <= set(value))
        properties = schema.get('properties', {})
        if schema.get('additionalProperties') is False:
            _require(set(value) <= set(properties))
        for key, item in value.items():
            validate(item, properties.get(key, {}))
    elif kind == 'string':
        _require(isinstance(value, str))
        _require(schema.get('minLength', 0) <= len(value) <= schema.get('maxLength', MAX_BYTES))
        if 'pattern' in schema:
            _require(re.fullmatch(schema['pattern'], value) is not None)
        if schema.get('format') == 'uuid':
            _require(UUID.fullmatch(value) is not None)
        if schema.get('format') == 'date-time':
            _require(re.fullmatch(r'\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d(?:\.\d+)?(?:Z|[+-]\d\d:\d\d)', value) is not None)
            try:
                parsed = datetime.fromisoformat(value.replace('Z', '+00:00'))
                _require(parsed.tzinfo is not None)
            except ValueError:
                raise RealtimeUnavailable('Invalid calling timestamp.') from None
    elif kind == 'integer':
        _require(type(value) is int and schema.get('minimum', 0) <= value <= min(schema.get('maximum', 2**53-1), 2**53-1))
    elif kind == 'boolean':
        _require(type(value) is bool)
    if 'const' in schema:
        _require(type(value) is type(schema['const']) and value == schema['const'])
    if 'enum' in schema:
        _require(value in schema['enum'])


def _pairs(pairs):
    result = {}
    for key, value in pairs:
        _require(key not in result)
        result[key] = value
    return result


def _constant(_value):
    raise RealtimeUnavailable('Invalid calling JSON.')


def _float(value):
    result = float(value)
    _require(math.isfinite(result))
    return result


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def _request(operation, token, correlation_id, *, body=None, idempotency_key=None, operation_id=None):
    _require(isinstance(token, str) and 0 < len(token) <= 16384 and all(33 <= ord(c) <= 126 for c in token))
    _require(isinstance(correlation_id, str) and UUID.fullmatch(correlation_id))
    spec = SCHEMA['operations'][operation]
    path = spec['path']
    if operation_id is not None:
        _require(isinstance(operation_id, str) and UUID.fullmatch(operation_id))
        path = path.replace('{operation_id}', operation_id)
    headers = {'Authorization': 'Bearer ' + token, 'X-Correlation-ID': correlation_id,
               'Accept': 'application/json'}
    if idempotency_key is not None:
        _require(isinstance(idempotency_key, str) and 16 <= len(idempotency_key) <= 128 and all(33 <= ord(c) <= 126 for c in idempotency_key))
        headers['Idempotency-Key'] = idempotency_key
    raw = None
    if body is not None:
        raw = json.dumps(body, separators=(',', ':'), allow_nan=False).encode()
        headers['Content-Type'] = 'application/json'
    req = urllib.request.Request(ORIGIN + path, data=raw, headers=headers, method=spec['method'])
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), NoRedirect(),
                                         urllib.request.HTTPSHandler(context=ssl.create_default_context()))
    try:
        with opener.open(req, timeout=5) as response:
            _require(response.status == (201 if body is not None else 200))
            _require(response.headers.get_content_type() == 'application/json')
            data = response.read(MAX_BYTES + 1)
        _require(len(data) <= MAX_BYTES)
        return json.loads(data, object_pairs_hook=_pairs, parse_constant=_constant, parse_float=_float)
    except urllib.error.HTTPError as error:
        error.close()
        raise RealtimeUnavailable('Calling service unavailable; reconciliation remains required.') from None
    except (OSError, ValueError, RecursionError, RealtimeUnavailable):
        raise RealtimeUnavailable('Calling service unavailable; reconciliation remains required.') from None


def create_session(token, campaign_id, resume_cursor, correlation_id, idempotency_key):
    body = {'campaign_id': campaign_id, 'resume_cursor': resume_cursor}
    validate(body, SCHEMA['schemas']['RealtimeSessionRequest'])
    result = _request('createRealtimeSession', token, correlation_id, body=body, idempotency_key=idempotency_key)
    validate(result, SCHEMA['schemas']['RealtimeSession'])
    _require(result['contract_digest'] == SCHEMA['digest'])
    remaining = datetime.fromisoformat(result['expires_at'].replace('Z', '+00:00')).timestamp() - time.time()
    _require(0 < remaining <= 60)
    _require(all(33 <= ord(c) <= 126 for c in result['ticket']))
    return result


def read_operation(token, operation_id, correlation_id):
    result = _request('readOperation', token, correlation_id, operation_id=operation_id)
    validate(result, SCHEMA['schemas']['Operation'])
    _require(result['operation_id'] == operation_id)
    # An operation status is not CDR evidence and never releases an ambiguous call.
    return result
