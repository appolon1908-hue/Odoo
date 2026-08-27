# Installation

Install `openpyxl` and `phonenumbers` in the immutable Odoo image or its pinned
dependency build. If MIME sniffing is enabled later, also install
`python-magic` and the matching reviewed libmagic runtime. Do not run unpinned
package installation directly in production.

Place `codestra_lead_ingestion` in an active custom addons directory and run:

```bash
odoo -c /etc/odoo/odoo.conf -d DATABASE \
  --addons-path=/usr/lib/python3/dist-packages/odoo/addons,/path/to/custom-addons \
  -i codestra_lead_ingestion --stop-after-init --without-demo=true
```

Use `-u` instead of `-i` for upgrades. Restart the normal Odoo service only
after the command succeeds. The module is also discoverable through Apps after
updating the apps list.
