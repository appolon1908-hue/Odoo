{
 "name":"Codestra Campaign-Specific CRM Operating System",
 "version":"19.0.1.2.1",
 "category":"Sales/CRM",
 "summary":"Configurable campaign workflows, RBAC, SLA, appointments, timeline and reporting",
 "author":"Codestra",
 "license":"LGPL-3",
 "depends":["call_center_campaign","codestra_appointments","mail"],
 "data":["security/ir.model.access.csv","security/record_rules.xml","data/corporate_sequences.xml","data/cod_web_out_email_templates.xml","data/cron.xml","views/crm_os_views.xml"],
 "post_init_hook":"post_init_hook",
 "installable":True,
 "application":True,
}
