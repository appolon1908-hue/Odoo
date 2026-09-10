# Codestra Night Workspace

An Odoo 19 backend theme with near-black surfaces, white typography, restrained
gray borders and monochrome controls. The visual direction is inspired by
Starlink's minimal black-and-white treatment; no Starlink branding or assets are
used.

The native navigation and page actions remain together at the top. Header actions
use filled white emphasis; body actions use quiet outlines. Required form,
dialog, record, chat and call controls remain available. The theme does not move
DOM nodes, hide actions or replace native Odoo components.

Coverage includes lists, grouped and selected rows, forms, kanban, search, tags,
tabs, statusbars, dialogs, popovers, notifications, calendar surfaces, charts,
chatter and floating Discuss windows. Labels and icons retain status meaning in
the monochrome palette. Images, attachments and native color-picker choices
retain their original content.
Keyboard focus stays visible; mobile menu overflow remains Odoo's responsibility.
Screen-only CSS leaves printed reports untouched.

## Installation

Add this directory's parent to the existing addon search path and install only
`codestra_workspace_theme` in the selected database. It depends on `web` and
`mail`, already present in the CRM. It has no model, controller, access rule,
installation hook, credential handling or public website assets. It does not
require `codestra_orbit_theme` or alter the Codestra login page.

Install/upgrade in an isolated Odoo 19 database first. Run the module's HTTP
tests with `--test-tags /codestra_workspace_theme --test-enable`; they check the
compiled authenticated asset bundle and public login isolation. Source validation
is `bash scripts/run_ci.sh` from the repository root.

Before production installation, capture a consistent database/filestore backup,
retain the current Compose configuration, and mount an immutable release read
only. Keep all existing addon paths and their order. Reload the browser after
Odoo regenerates the asset bundle. Uninstalling this presentation-only module
restores the previous backend styling without removing business records.

## Visual acceptance

Check desktop and narrow layouts for the Communications list, selected rows,
search filters, an editable form, a validation error, a kanban board, calendar,
dialog and floating chat. Confirm keyboard focus, menu overflow, New/Save,
record actions, search and chat controls remain usable. Automated HTTP checks do
not replace this visual review.
