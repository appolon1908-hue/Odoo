# CRM night theme visual acceptance

final result: blocked

The implementation is in `custom-addons/codestra_workspace_theme`. Source and HTTP asset checks passed. The user approved making the theme live with the documented limitation. The module is installed and its served CSS was verified; the live evidence is in `deploy/evidence/crm-night-live-20260910.json`. The supplied authenticated screenshots also identified a form-layout regression, repaired in `docs/CRM-FORM-LAYOUT-REPAIR-20260910.md`. There is still no assistant-captured post-repair authenticated CRM comparison, so this report does not certify the complete visual experience.

## Reference and state

- User reference: `upload/23a8dd87-10db-4fac-8045-476bd0a11723.png`, a desktop
  CRM record form with the Campaign CRM OS header, action buttons, field grid,
  notebook tabs, and Ralph Appolon chat drawer. `upload/e35377ab-16da-4068-9fe1-87c2ae11f00c.png`
  captures the open account menu/member panel state.
- Visual direction: `https://starlink.com/`, inspected in the cloud browser on
  2026-09-10. Restrained typography, white controls and dark surfaces inform this
  theme. No Starlink images or branding are copied.
- Reference browser capture: 1854 x 978 pixels including desktop chrome. No
  density-normalized comparison has been performed.
- Implementation screenshot: unavailable. The cloud browser reports "Site
  Unavailable" for `https://crm.codestra.agency/web/login`. This is a limitation
  of that browser, not evidence of a production outage.
- Intended implementation state: authenticated Communications list, desktop and
  narrow mobile layouts, with a floating chat open.

## Findings and remaining checks

The implementation cannot be visually accepted until the authenticated page can
be rendered. No full-view or focused-region comparison was possible. No browser
interaction or console-error check of the new theme is claimed.

1. Hard-reload the CRM record and check slate actions, fixed label/value
   alignment, enclosed inputs, tab scrolling/active state, and the chat drawer.
2. Check typography, header menu overflow and control-panel wrapping at desktop
   and narrow widths. Confirm all navigation remains reachable.
3. Exercise New/Save, a validation error, filter selection, notebook tabs, and
   chat collapse/close controls. Confirm native images, icons, and business copy
   retain their content.

## Verification history

- Source validation passed, including 172 source contract tests.
- A disposable Odoo 19/PostgreSQL database installed and upgraded the addon and passed both
  HTTP tests: authenticated compiled CSS includes the theme, and public login
  retains its password/CSRF fields without the backend theme.
- Final tested module files and their SHA-256 hashes are recorded in
  `deploy/evidence/crm-night-theme-20260910.json`. The isolated test containers,
  database, network and temporary credentials were removed after verification.
- Inspection of the installed Odoo 19 styles identified its current statusbar
  variables and the separate chat bubble tail/muted states. The CSS uses those
  variables and covers those states. This was a source correction, not a visual
  QA pass.
- PR review identified that a calendar-wide grayscale filter also recolored
  attendee images. The filter was removed; event backgrounds and borders now
  receive monochrome colors directly. Native color-picker options also retain
  their actual choices. The corrected CSS passed source asset validation; the
  runtime evidence records the earlier tested source explicitly.

## Follow-up iteration

The user-provided CRM form screenshots exposed white action buttons, underline
fields, fading tabs, and chat overlap. The follow-up CSS adds slate action
tokens, a 180px desktop label track, enclosed field boxes, scrollable tabs, and a
responsive chat reservation. Source and asset validation passed after this
repair.

The remaining blocker is browser-rendered authenticated post-repair
implementation evidence.
