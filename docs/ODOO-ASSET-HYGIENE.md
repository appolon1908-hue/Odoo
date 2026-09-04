# Odoo browser-asset hygiene and recovery

## Repository policy

Codestra-owned Odoo browser styles must be committed as standards-based `.css`
files. Custom `.scss`, `.sass`, and `.less` files are prohibited under
`custom-addons/*/static/src/`.

This policy does **not** modify Odoo's core asset pipeline. Odoo may continue to
compile its own upstream SCSS. The policy removes repository-owned Sass syntax,
nesting, imports, and compiler-version drift from the production failure path.

The repository-wide validator fails closed when it finds:

- a missing or duplicate asset declaration;
- an asset outside its module namespace;
- an orphan stylesheet under `static/src/`;
- a custom SCSS, Sass, or Less file;
- Sass-only syntax in a `.css` file;
- unbalanced CSS delimiters or an unterminated string/comment;
- a CSS `@import` or remote stylesheet URL;
- invalid asset XML, empty text assets, UTF-8 BOMs, or NUL bytes.

Runtime CI installs every custom addon on immutable Odoo 19 and PostgreSQL
images. It now requests the normal, non-debug login and backend stylesheet
bundles. The test fails if Odoo returns a bundle error, omits the Codestra login
CSS, displays the style-compilation warning, or leaves the backend stylesheets
unloaded.

## Cleaned modules

The following custom styles were converted from SCSS to plain CSS and their
module versions were advanced so a controlled Odoo module upgrade regenerates
the corresponding asset metadata:

- `codestra_vicidial_crm`;
- `codestra_appointments`;
- `codestra_login_branding`;
- `codestra_interaction_workflow`.

No generated `ir.attachment` asset, database row, filestore object, or live
container is stored or changed by this repository cleanup.

## Required deployment sequence after merge

1. Record the protected `main` SHA and immutable image digest.
2. Back up the target PostgreSQL database, Odoo filestore, and configuration.
3. Deploy that exact reviewed image to `staging-readonly` without rebuilding or
   retagging it.
4. Stop all Odoo workers before changing module state.
5. Upgrade only the four modules listed above on the intended database.
6. Restart every Odoo worker on the same exact source/image identity.
7. Request `/web/login` and `/odoo` without `debug=assets` and verify that every
   stylesheet response is HTTP 200 with `text/css`.
8. Confirm that the server logs contain no `Style error`, `SassError`, missing
   asset path, undefined variable, or bundle-compilation traceback.
9. If the database still references an old `.scss` path, inventory `ir.asset`
   and generated `/web/assets/` attachments read-only before any cleanup.
10. Delete only confirmed generated stale asset attachments after backup; never
    delete arbitrary `ir.attachment` rows or weaken the release gates.

A successful repository CI run proves the source and disposable-database asset
path. It does not prove that an existing production database has no stale
`ir.asset` row or generated attachment. Runtime database cleanup remains a
separate, evidence-backed staging operation.
