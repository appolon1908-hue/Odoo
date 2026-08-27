def migrate(cr, version):
    """Initial-version migration anchor.

    Future schema/data migrations are versioned here. Initial configuration is
    idempotently owned by XML IDs and unique indexes, so no data rewrite is
    required for 19.0.1.0.0.
    """
    return None
