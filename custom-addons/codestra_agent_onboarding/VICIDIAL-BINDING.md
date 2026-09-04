# Governed VICIdial binding

A new agent request may leave Odoo only when the selected legacy campaign
projection explicitly declares telephony and VICIdial required, has a native
VICIdial campaign ID and approved user group, and has read-back state
`synced_disabled`.

The event carries the employee display name, reserved VICIdial username,
approved native campaign ID, approved user group, and any campaign inbound
group. It never carries a VICIdial password. The private VICIdial provisioning
adapter creates its own disabled credential through the protected credential
boundary; the agent receives only the Keycloak one-time activation flow.

The role-template user group must equal the campaign's approved user group. This
prevents the onboarding form from selecting a broader or cross-campaign group.
