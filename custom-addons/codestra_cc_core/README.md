# Codestra Contact Center Core

Compatibility and ownership facade for the corporate call-center mission.

The audited implementation remains in `call_center_core`, `codestra_interaction_workflow`, and the hardened interaction records in `codestra_vicidial_crm`. This module deliberately avoids duplicating customer, call, campaign, or audit tables. New canonical projections must be introduced only after a reviewed migration map proves that no existing model already owns the concept.

Live writes, external delivery, callbacks, and dialing remain disabled by default.
