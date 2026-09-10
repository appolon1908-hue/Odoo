# Discuss night-theme contrast repair — 2026-09-10

The production screenshot showed white sidebars and a white toolbar with pale
labels, dark message text on dark bubbles, and a white composer shell. This was
a real regression in the initial night theme's coverage of native Odoo mail CSS.

## Correction

Odoo 19's `o-mail-discussSidebarBgColor` and `o-discuss-text-body` helpers set
white backgrounds and gray text with `!important`. Override those helpers within
the authenticated web client. The message text is a sibling of its bubble
background, so coloring the bubble alone cannot correct the text.

Also cover Discuss content/header/panel surfaces, active and hovered channels,
toolbar action groups, composer wrappers and placeholders, and quoted-message
text. Keep offline member rows at full opacity; only their avatar is dimmed.
Use the native sidebar state variables, including Odoo 19's three-hyphen
`---mail-DiscussSidebarChannel-borderedBgColor` spelling.

This is a CSS-only change. Native controls, enabled/disabled states, routes,
authentication, message delivery, images and attachments keep their behavior.
Styles remain restricted to `@media screen` and `body.o_web_client`.

## Validation

`./scripts/run_ci.sh` passed, including custom asset validation and 172 existing
source tests. The selectors and cascade were checked against the installed
Odoo 19.0-20260630 mail SCSS and XML templates.

The following ratios are calculated from the declared opaque color pairs;
they are not a claim of a completed authenticated browser accessibility audit.

| Surface | Text | Background | Contrast |
| --- | --- | --- | --- |
| Message text | `#f5f5f5` | `#242424` | 14.24:1 |
| Sidebar labels | `#f5f5f5` | `#0d0d0d` | 17.83:1 |
| Offline member names | `#b5b5b5` | `#0d0d0d` | 9.48:1 |
| Composer placeholder | `#b5b5b5` | `#171717` | 8.74:1 |
| Toolbar icons | `#f5f5f5` | `#171717` | 16.44:1 |

Authenticated browser rendering remains unverified from the assistant's browser.
The user's screenshot is the before-state evidence. A reloaded Discuss page
should be checked for channel selection, member names, message and quote text,
composer placeholder, and toolbar icons at desktop and mobile widths.

## Deployment and rollback

Mount the committed CSS file read-only over the installed theme's CSS path using
`deploy/compose/compose.discuss-contrast.production.yaml`, appended to the current
Compose file list. Compare rendered Compose configurations before applying:
only the Odoo stylesheet mount may change. Preserve the existing call-popup RPC
repair mount and pinned Odoo image. Recreate only Odoo, warm its native backend
asset bundle, and verify the served stylesheet contains the corrected rules.

No module or database upgrade is needed. Retain the original theme release and
previous Compose file list. Roll back by recreating Odoo with that previous
list and regenerating its native asset bundle. Existing tabs need a full reload.
