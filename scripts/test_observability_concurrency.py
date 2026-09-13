"""Run through odoo shell against the installed disposable CI database.

Independent cursors cannot run inside TransactionCase's registry test lock.
This check deliberately runs after the module test transaction has ended.
"""
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
from uuid import uuid4

from psycopg2.errors import SerializationFailure
from odoo import api, SUPERUSER_ID
from odoo.addons.codestra_observability_integration.tests.test_observability import TestKyyowObservability
from odoo.addons.codestra_observability_integration.models.observability import KPI_HASH_KEYS, INCIDENT_HASH_KEYS

fixtures = TestKyyowObservability()
registry = env.registry
for model_name, source, keys in (
    ('kyyow.observability.kpi.snapshot', fixtures._kpi(), KPI_HASH_KEYS),
    ('kyyow.observability.incident', fixtures._incident(), INCIDENT_HASH_KEYS),
):
    identity = 'concurrent-' + uuid4().hex
    payload = fixtures._with_projection({**source, 'tenant_id': identity, 'event_id': identity}, keys)
    barrier = Barrier(2)

    def deliver(_):
        barrier.wait(timeout=15)
        for attempt in range(5):
            with registry.cursor() as cursor:
                environment = api.Environment(cursor, SUPERUSER_ID, {})
                try:
                    record, duplicate = environment[model_name]._from_payload(payload)
                    identifier = record.id
                    cursor.commit()
                    return identifier, duplicate
                except SerializationFailure:
                    cursor.rollback()
        raise RuntimeError('concurrent projection retry exhausted')

    with ThreadPoolExecutor(max_workers=2) as executor:
        first, second = list(executor.map(deliver, range(2)))
    if first[0] != second[0] or sorted([first[1], second[1]]) != [False, True]:
        raise RuntimeError('concurrent duplicate did not return one immutable record')
print('ODOO_OBSERVABILITY_CONCURRENCY=PASS')
