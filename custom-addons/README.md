# Custom addons

Place each Odoo custom module in its own directory:

```text
custom-addons/
└── example_module/
    ├── __init__.py
    ├── __manifest__.py
    ├── models/
    ├── security/
    ├── views/
    └── tests/
```

Do not copy the Odoo core source, database, filestore, runtime data, or secrets into this directory.
