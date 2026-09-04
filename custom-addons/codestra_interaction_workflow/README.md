# Codestra Interaction Workflow

Read-only Odoo 19 operations dashboard for reviewing integration state and
submitting governed activation requests. The module exposes no direct provider
activation path and does not authorize external delivery.

## Browser assets

The dashboard JavaScript, XML template, and styles are declared in
`web.assets_backend`. The stylesheet is standards-based CSS so this custom addon
does not introduce a Sass, SCSS, or Less compiler dependency into Odoo's
production asset bundle.

## Validation

Repository CI validates the manifest paths, browser assets, module tests, and
normal production bundle through the shared Odoo 19 runtime workflow. Deploy
only an exact reviewed commit and upgrade this module in staging before any
production rollout.
