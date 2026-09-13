"""Run with `odoo shell` after module installation in the disposable CI database.

Independent, committed cursors force competing deliveries to share the old
REPEATABLE READ snapshot. Odoo's production `service.model.retrying` wrapper
must perform the whole-transaction retry; no private test retry loop is used.
"""
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
from uuid import uuid4

from odoo import api
from odoo.exceptions import ConcurrencyError, ValidationError
from odoo.service.model import retrying
from odoo.addons.codestra_kyqra_review_hub.tests.test_kyqra_data import (
    TestCodestraKyqraData,
)

assert env.cr.dbname == "odoo_ci", "Run only in the disposable Odoo CI database"
registry = env.registry
user_id = env.uid
company_id = env.company.id
service_group = env.ref("codestra_kyqra_review_hub.group_kyqra_service")
env.user.write({"group_ids": [(4, service_group.id)]})
params = env["ir.config_parameter"].sudo()
params.set_param("codestra.kyqra.tenant_ids", "tenant-1")
params.set_param(
    "codestra.middleware.tenant.tenant-1.codestra.kyqra.service_user_id",
    str(user_id),
)
params.set_param(
    "codestra.kyqra.tenant.tenant-1.company_id",
    str(company_id),
)
env.cr.commit()


def run_pair(conflicting=False):
    suffix = uuid4().hex
    payload = TestCodestraKyqraData._event(
        None, event_id="event-" + suffix, idempotency_key="idem-" + suffix
    )
    second = TestCodestraKyqraData._event(
        None,
        event_id=("other-" if conflicting else "event-") + suffix,
        idempotency_key="idem-" + suffix,
    )
    barrier = Barrier(2, timeout=30)

    def deliver(event):
        retries = 0
        first_attempt = True
        with registry.cursor() as cr:
            local_env = api.Environment(cr, user_id, {})
            model = local_env["codestra.kyqra.batch"]

            def dispatch():
                nonlocal first_attempt, retries
                cr.execute("SHOW transaction_isolation")
                assert cr.fetchone()[0] == "repeatable read"
                cr.execute("SET LOCAL statement_timeout = '30s'")
                # Force both initial snapshots before either reservation is inserted.
                model.sudo().search_count([])
                if first_attempt:
                    first_attempt = False
                    barrier.wait()
                try:
                    return model.apply_middleware_event(event)
                except ConcurrencyError:
                    retries += 1
                    raise
                except ValidationError:
                    if not conflicting:
                        raise
                    return {"action": "conflict"}

            result = retrying(dispatch, local_env)
            return result, retries

    with ThreadPoolExecutor(max_workers=2) as executor:
        futures = [executor.submit(deliver, item) for item in (payload, second)]
        deliveries = [future.result(timeout=45) for future in futures]
    results = [item[0] for item in deliveries]
    assert sum(item[1] for item in deliveries) >= 1, deliveries
    expected = ["conflict", "created"] if conflicting else ["created", "duplicate"]
    assert sorted(item["action"] for item in results) == sorted(expected), deliveries
    with registry.cursor() as cr:
        local_env = api.Environment(cr, user_id, {})
        batches = local_env["codestra.kyqra.batch"].sudo().search(
            [
                ("tenant_id", "=", "tenant-1"),
                ("idempotency_key", "=", payload["idempotency_key"]),
            ]
        )
        assert len(batches) == 1
        assert len(batches.entity_ids) == 1
        assert len(batches.entity_ids.evidence_ids) == 1
        if not conflicting:
            assert {item["batch_id"] for item in results} == {batches.id}
    print(
        "KYQRA_CONCURRENT_%s=PASS"
        % ("CONFLICT" if conflicting else "IDENTICAL")
    )


run_pair()
run_pair(conflicting=True)
