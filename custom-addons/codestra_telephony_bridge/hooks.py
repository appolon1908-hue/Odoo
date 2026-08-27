import uuid

CALLBACK_NAMESPACE = uuid.UUID("e4bcab72-dff1-5b5c-a787-81e6541899df")


def post_init_hook(env):
    """Backfill stable callback bindings without external side effects."""
    callbacks = env["call.center.callback.task"].with_context(active_test=False).search(
        ["|", ("callback_public_id", "=", False), ("idempotency_key", "=", False)]
    )
    for callback in callbacks:
        identity = (
            f"{callback.record_environment}:{callback.id}:"
            f"{callback.correlation_id}"
        )
        callback.write(
            {
                "callback_public_id": callback.callback_public_id
                or str(uuid.uuid5(CALLBACK_NAMESPACE, identity)),
                "idempotency_key": callback.idempotency_key
                or f"callback:{uuid.uuid5(CALLBACK_NAMESPACE, identity)}",
            }
        )
