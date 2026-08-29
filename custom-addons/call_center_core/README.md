# Call Center Core

This Odoo 19 add-on owns business-unit scope, call-center roles, shared CRM
fields, and audit foundations.

`Integration Service` is a non-interactive authorization group. It inherits the
ordinary call-center user boundary so global business-unit rules apply, but it
does not inherit manager, compliance, or administrator permissions. A service
module must grant every writable model through its own explicit ACL and must
bind the user to exactly the approved business units.
