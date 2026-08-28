# Middleware boundary report

Candidate: `feat/cc-compliance-audit` / `4681d755039ee7f4fec21228bac234a668541de8`

Odoo may own transactional outbox/inbox and resource-specific service operations. Cross-system connector execution remains in Codestra Middleware.

## Automated scan

- `REVIEW`: external PostgreSQL client at `custom-addons/codestra_identity_provisioning/models/provisioning.py:9`
- `REVIEW`: external PostgreSQL client at `custom-addons/codestra_identity_provisioning/tests/test_provisioning.py:4`
- `REVIEW`: direct VICIdial database write at `custom-addons/codestra_cc_recordings/models/recording.py:241`
- `REVIEW`: direct VICIdial database write at `custom-addons/codestra_cc_disposition/ROLLBACK.md:7`
- `REVIEW`: direct VICIdial database write at `custom-addons/codestra_cc_vicidial/models/telephony_mapping.py:92`
- `REVIEW`: direct VICIdial database write at `custom-addons/codestra_vicidial_connector/models/connector.py:61`
- `REVIEW`: direct VICIdial database write at `custom-addons/codestra_vicidial_connector/models/connector.py:125`
- `REVIEW`: direct VICIdial database write at `custom-addons/codestra_appointments/models/appointment.py:101`
- `REVIEW`: direct VICIdial database write at `custom-addons/codestra_appointments/models/appointment.py:103`
- `REVIEW`: direct VICIdial database write at `custom-addons/codestra_ai_agent_assistant/models/assistant_draft.py:35`
- `REVIEW`: direct VICIdial database write at `custom-addons/codestra_campaign_crm_os/models/engine.py:130`
- `REVIEW`: direct VICIdial database write at `custom-addons/codestra_campaign_crm_os/models/engine.py:426`
- `REVIEW`: external PostgreSQL client at `custom-addons/codestra_middleware_bridge/tests/test_bridge_schema.py:2`
- `REVIEW`: external PostgreSQL client at `custom-addons/codestra_lead_automation/models/automation_domain.py:8`
- `REVIEW`: external PostgreSQL client at `custom-addons/codestra_telephony_bridge/tests/test_telephony_models.py:6`
- `REVIEW`: external PostgreSQL client at `custom-addons/codestra_telephony_bridge/tests/test_telephony_hardening.py:5`
- `REVIEW`: direct VICIdial database write at `custom-addons/codestra_cc_workforce/models/shift.py:34`
- `REVIEW`: external PostgreSQL client at `custom-addons/codestra_integration_hub/models/idempotency.py:3`
- `REVIEW`: external PostgreSQL client at `custom-addons/codestra_integration_hub/tests/test_schema_constraints.py:1`
- `REVIEW`: direct VICIdial database write at `custom-addons/codestra_vicidial_crm/migrations/19.0.3.2.0/post-migrate.py:2`
- `REVIEW`: direct VICIdial database write at `custom-addons/codestra_vicidial_crm/models/res_users.py:8`
- `REVIEW`: direct VICIdial database write at `custom-addons/codestra_vicidial_crm/models/core.py:34`
- `REVIEW`: direct VICIdial database write at `custom-addons/codestra_vicidial_crm/models/workspace.py:26`
- `REVIEW`: direct VICIdial database write at `custom-addons/codestra_vicidial_crm/models/workspace.py:38`
- `REVIEW`: direct VICIdial database write at `custom-addons/codestra_vicidial_crm/models/workspace.py:122`
- `REVIEW`: direct VICIdial database write at `custom-addons/codestra_vicidial_crm/models/workspace.py:151`
- `REVIEW`: direct VICIdial database write at `custom-addons/codestra_vicidial_crm/models/contact_center.py:44`
- `REVIEW`: direct VICIdial database write at `custom-addons/codestra_vicidial_crm/models/contact_center.py:46`
- `REVIEW`: direct VICIdial database write at `custom-addons/codestra_vicidial_crm/models/call_control.py:279`
- `REVIEW`: external PostgreSQL client at `custom-addons/codestra_vicidial_crm/tests/test_reconciliation.py:6`
- `REVIEW`: external PostgreSQL client at `custom-addons/codestra_vicidial_crm/tests/test_lead_reconciliation.py:1`
- `REVIEW`: direct VICIdial database write at `custom-addons/codestra_vicidial_recording/models/scope.py:33`
- `REVIEW`: direct VICIdial database write at `custom-addons/codestra_vicidial_recording/models/recording.py:34`
- `REVIEW`: direct VICIdial database write at `custom-addons/codestra_vicidial_recording/models/recording.py:40`
- `REVIEW`: direct VICIdial database write at `custom-addons/codestra_vicidial_recording/models/recording.py:209`
- `REVIEW`: direct VICIdial database write at `custom-addons/codestra_vicidial_recording/models/recording.py:361`
- `REVIEW`: direct VICIdial database write at `custom-addons/codestra_vicidial_recording/models/recording.py:408`
- `REVIEW`: external PostgreSQL client at `custom-addons/codestra_vicidial_recording/tests/test_recording.py:8`
- `REVIEW`: direct VICIdial database write at `custom-addons/codestra_vicidial_recording/views/recording_views.xml:4`
- `REVIEW`: direct VICIdial database write at `custom-addons/codestra_vicidial_recording/views/recording_views.xml:25`
- `REVIEW`: direct VICIdial database write at `custom-addons/codestra_vicidial_recording/views/recording_views.xml:104`
- `REVIEW`: direct VICIdial database write at `custom-addons/codestra_vicidial_recording/views/recording_views.xml:123`
- `REVIEW`: external PostgreSQL client at `custom-addons/call_center_campaign/tests/test_outbox.py:8`

Provider-effect and controller findings remain subject to semantic review; absence from this pattern scan is not certification.
