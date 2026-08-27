# UI endpoint inventory

| UI action | Odoo method | Effect |
| --- | --- | --- |
| Refresh dashboard | `get_dashboard_snapshot` | Odoo ORM read only |
| Request retry | `request_delivery_retry` | Creates approval request |
| Request activation | `request_workflow_activation` | Creates staging approval request |

The browser does not call middleware or n8n write endpoints.
