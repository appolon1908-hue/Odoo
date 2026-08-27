"""Idempotent Odoo-shell provisioner for approved COD-WEB-OUT canary readiness.

Run only after the module upgrade.  It never activates unrestricted campaign
traffic and never stores or invents a recipient address.
"""
from odoo.addons.codestra_campaign_crm_os.hooks import post_init_hook


Campaign=env["call.center.campaign"].sudo().with_context(active_test=False)
campaign=Campaign.search([("id","=",6),("code","=","COD-WEB-OUT")],limit=1)
if not campaign or campaign.id != 6:
    raise RuntimeError("exact_campaign_guard_failed")

Parameter=env["ir.config_parameter"].sudo()
Parameter.set_param("codestra.cod_web_out.canary_provisioning_approved","true")
Parameter.set_param("codestra.cod_web_out.email.enabled","true")
Parameter.set_param("codestra.cod_web_out.email.mode","CANARY")
Parameter.set_param("codestra.cod_web_out.email.allowlist_required","true")
Parameter.set_param("codestra.email.production.global","false")
Parameter.set_param("codestra.sms.production","false")
Parameter.set_param("codestra.voice.production","false")
Parameter.set_param(
    "codestra.cod_web_out.canary_recipient_secret_file",
    "/etc/codestra/secrets/cod-web-out-email/canary-recipient",
)
post_init_hook(env)

unit=campaign.business_unit_id
Department=env["call.center.department"].sudo().with_context(active_test=False)
department=Department.search([("business_unit_id","=",unit.id)],limit=1)
if not department:
    department=Department.create({"name":"COD Web Canary Operations","code":"COD-WEB-CANARY","business_unit_id":unit.id})

Users=env["res.users"].sudo().with_context(active_test=False)
def service_user(login,name):
    user=Users.search([("login","=",login)],limit=1)
    if not user:
        # Odoo 19 creates/links the partner while the new user is active.
        # Creating directly with active=False can attempt to archive that
        # partner before the user row is deactivated and is rejected by the
        # partner/user integrity guard.  Create, then deactivate explicitly.
        user=Users.create({"name":name,"login":login,"active":True,
                           "company_id":env.company.id,"company_ids":[(6,0,env.company.ids)],
                           "call_center_business_unit_ids":[(6,0,unit.ids)]})
    user.write({"active":False,"call_center_business_unit_ids":[(6,0,unit.ids)]})
    return user

supervisor=service_user("svc.cod-web-out-canary-supervisor@internal.invalid","COD-WEB-OUT Canary Supervisor [NONINTERACTIVE]")
agent_user=service_user("svc.cod-web-out-canary-agent@internal.invalid","COD-WEB-OUT Canary Agent [NONINTERACTIVE]")

Team=env["call.center.team"].sudo().with_context(active_test=False)
team=Team.search([("code","=","COD-WEB-OUT-CANARY"),("business_unit_id","=",unit.id)],limit=1)
team_values={"name":"COD-WEB-OUT Canary","code":"COD-WEB-OUT-CANARY",
             "business_unit_id":unit.id,"department_id":department.id,
             "capacity":1,"canary_only":True,"customer_traffic_allowed":False,
             "agent_ids":[(6,0,agent_user.ids)],"supervisor_ids":[(6,0,supervisor.ids)],
             "active":True}
team.write(team_values) if team else Team.create(team_values)
team=Team.search([("code","=","COD-WEB-OUT-CANARY"),("business_unit_id","=",unit.id)],limit=1)

campaign.write({"team_ids":[(6,0,team.ids)],"agent_ids":[(6,0,agent_user.ids)],
                "supervisor_ids":[(6,0,supervisor.ids)],"active":False,"state":"draft"})

Profile=env["codestra.agent.profile"].sudo().with_context(active_test=False)
profile=Profile.search([("name","=","COD-WEB-OUT Canary Agent [SYSTEM]")],limit=1)
profile_values={"name":"COD-WEB-OUT Canary Agent [SYSTEM]","agent_type":"SYSTEM_CANARY",
                "user_id":agent_user.id,"campaign_ids":[(6,0,campaign.ids)],"team_id":team.id,
                "supervisor_id":supervisor.id,"skills":["email_canary"],
                "permissions":["campaign.read","synthetic_record.process","email.dry_run"],
                "daily_capacity":1,"canary_only":True,"customer_traffic_allowed":False,"active":True}
profile.write(profile_values) if profile else Profile.create(profile_values)

mapping=env["call.center.campaign.mapping"].sudo().with_context(active_test=False).search([
    ("campaign_id","=",campaign.id),("canonical_campaign_code","=","COD-WEB-OUT")
],limit=1)
if not mapping:
    raise RuntimeError("cod_web_out_mapping_missing")
mapping_values={"environment":"production","production_eligible":True,
                "activation_mode":"CANARY_ONLY","desired_state":"inactive","active":False}
if any(mapping[field_name]!=value for field_name,value in mapping_values.items()):
    mapping_values["mapping_version"]=mapping.mapping_version+1
    mapping.write(mapping_values)

Lead=env["crm.lead"].sudo().with_context(active_test=False)
lead=Lead.search([("test_canary","=",True),("call_center_campaign_id","=",campaign.id)],limit=1)
lead_values={"name":"TEST_CANARY COD-WEB-OUT Email Readiness","type":"lead",
             "business_unit_id":unit.id,"call_center_campaign_id":campaign.id,
             "codestra_workflow_id":env["codestra.campaign.workflow"].search([("key","=","codestra_development")],limit=1).id,
             "assigned_agent_profile_id":profile.id,"user_id":agent_user.id,
             "codestra_supervisor_id":supervisor.id,"test_canary":True,
             "email_from":False,"active":False,"source_system":"odoo-canary-provisioner"}
lead.write(lead_values) if lead else Lead.create(lead_values)

env.cr.commit()
print("COD_WEB_OUT_ODOO_CANARY_PROVISIONING=PASS")
