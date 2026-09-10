# CRM night theme visual acceptance

final result: blocked

The implementation is in `custom-addons/codestra_workspace_theme`. Source and
HTTP asset checks passed, but there is no rendered authenticated CRM comparison.
This report does not certify the complete visual experience or production use.

## Reference and state

- User reference: `upload/debc38ec-a876-4b2a-897a-d050494f40fd.png`, a desktop
  Communications list with the Campaign CRM OS header and a floating Discuss
  window. The requested change is black-and-white styling, not matching the
  screenshot's existing white surfaces.
- Visual direction: `https://starlink.com/`, inspected in the cloud browser on
  2026-09-10. Restrained typography, white controls and dark surfaces inform this
  theme. No Starlink images or branding are copied.
- Reference browser capture: 1363 x 936 pixels, desktop. The user screenshot is
  1854 x 978 pixels including desktop chrome. No density-normalized comparison
  has been performed.
- Implementation screenshot: unavailable. The cloud browser reports "Site
  Unavailable" for `https://crm.codestra.agency/web/login`. This is a limitation
  of that browser, not evidence of a production outage.
- Intended implementation state: authenticated Communications list, desktop and
  narrow mobile layouts, with a floating chat open.

## Findings and remaining checks

The implementation cannot be visually accepted until the authenticated page can
be rendered. No full-view or focused-region comparison was possible. No browser
interaction or console-error check of the new theme is claimed.

1. Check typography, header menu overflow and control-panel wrapping at desktop
   and narrow widths. Confirm all navigation remains reachable.
2. Check the black/gray surface hierarchy, white text contrast, input borders,
   selected rows, disabled controls and keyboard focus.
3. Check forms, statusbars, search, kanban, calendar, dialogs and floating chat.
   Exercise New/Save, a validation error, filter selection and chat controls.
4. Confirm existing images, native icons and business copy retain their content.
   No new decorative assets or marketing copy are introduced.

## Verification history

- Source validation passed, including 172 source contract tests.
- A disposable Odoo 19/PostgreSQL database installed the addon and passed both
  HTTP tests: authenticated compiled CSS includes the theme, and public login
  retains its password/CSRF fields without the backend theme.
- Inspection of the installed Odoo 19 styles identified its current statusbar
  variables and the separate chat bubble tail/muted states. The CSS uses those
  variables and covers those states. This was a source correction, not a visual
  QA pass.

The remaining blocker is browser-rendered authenticated implementation evidence.
