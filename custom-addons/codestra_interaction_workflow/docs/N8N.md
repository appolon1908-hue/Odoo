# n8n workflow inventory

The Odoo UI stores logical workflow keys and versions only. Runtime n8n IDs,
endpoint URLs, credentials, activation leases, and package digests are
deployment/registry data and are never browser contracts.

All dashboard actions create approval requests. They do not activate a
workflow or call n8n directly.
