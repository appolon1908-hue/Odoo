# CRM form layout repair — 2026-09-10

The supplied CRM screenshots show an authenticated Odoo record form at desktop
width with the direct chat drawer open. The night theme is intentionally
monochrome, but native form rules were still producing bright white actions,
underline-only fields, low-contrast notebook tabs, and a drawer that could cover
record inputs.

## Applied design decisions

- Form actions (`Won`, `Enrich`, `Lost`, `Validate`, and eligibility actions) use
  a `#2a2a2a` slate fill, `#555` border, muted white text, and a brighter hover
  state. Pipeline arrow buttons use the same hierarchy; the current stage is
  distinguishable with a lighter border rather than a white glare block.
- Desktop `o_inner_group` grids use `minmax(150px, 180px) minmax(0, 1fr)` with
  consistent gaps and centered labels. Mobile widths retain Odoo's stacked form
  behavior.
- Editable and readonly scalar values use a 1px `#333` box, 4px radius, 6px by
  10px padding, and a `#1e1e1e` surface. Focus uses a visible gray ring.
- Notebook tabs are non-wrapping, horizontally scrollable, and have readable
  inactive labels. The active tab has a slate surface and a white bottom rule.
- The native `.o-mail-ChatWindow` remains collapsible through its Odoo header
  controls, stays above the record with an explicit z-index, is bounded to the
  viewport, and reserves up to 360px of form space at wide desktop widths.
  On narrow screens it becomes a viewport-width drawer and the form reservation
  is removed so Odoo's mobile layout remains usable.

No DOM, routes, authentication, RPC, calls, messages, attachments, or business
data are changed. The CSS stays scoped to `@media screen` and
`body.o_web_client`; the public Codestra login is unaffected.

## Evidence and validation

The visual source is the user's screenshots:

- `upload/23a8dd87-10db-4fac-8045-476bd0a11723.png` — CRM record form with
  action buttons, fields, tabs, and Ralph Appolon chat drawer.
- `upload/e35377ab-16da-4068-9fe1-87c2ae11f00c.png` — open account menu and
  member panel state.

The source CI suite passes, including custom asset validation and 172 source
contract tests. The module HTTP test now asserts the fixed action token, desktop
grid, enclosed inputs, tab state, drawer reservation, and z-index in the served
authenticated stylesheet.

An authenticated post-deploy browser screenshot is not available from the
assistant browser, so `design-qa.md` remains `final result: blocked`. After a
hard reload, check the same record at desktop and narrow widths: open/close the
chat window, edit a field, select each notebook tab, and confirm the active
pipeline stage remains obvious.
