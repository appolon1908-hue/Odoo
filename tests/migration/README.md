# Migration certification

The source tree supplies initial-schema migration policies for every new model-owning mission module. Production acceptance additionally requires a restored copy of the deployed database, before/after counts, external-ID reconciliation, interrupted-upgrade restart, duplicate preflight, query-plan evidence, and rollback restoration.

No migration script in this branch deletes records, truncates tables, drops business tables, or removes columns.
