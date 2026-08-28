# Campaign mail migration policy

This branch creates no campaign alias, distribution group, provider mailbox, or
external route automatically. The controlled authority matrix marks every
campaign email alias key as `MISSING`, so guessing addresses would create an
unsafe routing boundary.

A later migration must inventory existing `mail.alias` and
`codestra.mail.team` rows, obtain an approved campaign-to-address mapping,
detect duplicate addresses, link only exact matches, keep every adopted route
disabled, read back provider state, and retain rollback evidence. Unknown,
ambiguous, wildcard, catch-all, or cross-campaign mappings must remain blocked.
