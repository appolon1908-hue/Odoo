"""Install five inactive, unbound workflow templates without guessing campaign IDs."""

WORKFLOWS={
"transportation":{
 "name":"Transportation / Logistics",
 "statuses":"NEW_LEAD CONTACT_VALIDATION READY_TO_CALL ATTEMPTING_CONTACT CONNECTED QUALIFIED DOT_AUTHORITY_REVIEW QUOTE_REQUESTED QUOTE_PREPARATION QUOTE_SENT QUOTE_FOLLOW_UP NEGOTIATION CONTRACT_CARRIER_PACKET LOAD_BOOKED PICKUP_SCHEDULED IN_TRANSIT DELIVERED CUSTOMER_FOLLOW_UP RETENTION_REPEAT_LOAD WON".split(),
 "exceptions":"NOT_INTERESTED NO_CURRENT_LOAD CALL_BACK_LATER INVALID_COMPANY INVALID_PHONE WRONG_CONTACT DUPLICATE DO_NOT_CALL COMPLIANCE_HOLD LOST_TO_COMPETITOR QUOTE_DECLINED".split(),
 "appointments":"SHIPPER_DISCOVERY QUOTE_REVIEW CARRIER_CUSTOMER_ONBOARDING LOAD_CONFIRMATION ACCOUNT_REVIEW FOLLOW_UP_CALL".split(),
 "dispositions":{"DOTREV":"DOT_AUTHORITY_REVIEW","QUOTE":"QUOTE_REQUESTED","CARRIERPKT":"CONTRACT_CARRIER_PACKET","CONTRACT":"CONTRACT_CARRIER_PACKET"},
 "followups":{"CONNECTED":"CONTACT_FOLLOW_UP","QUALIFIED":"QUALIFICATION_FOLLOW_UP","QUOTE_SENT":"QUOTE_REVIEW_FOLLOW_UP"},
 "required":{"QUOTE_SENT":["quote_reference","quote_sent_at"]},
 "automations":"transportation_quote_requested transportation_quote_sent_followup transportation_carrier_packet transportation_load_booked transportation_pickup_reminder transportation_delivery_followup transportation_repeat_load".split(),
 "kpis":"QUOTES_REQUESTED QUOTES_SENT QUOTE_ACCEPTANCE_RATE LOADS_BOOKED LOADS_DELIVERED REPEAT_LOADS QUOTE_RESPONSE_SLA LOAD_CONVERSION_RATE".split(),
},
"codestra_development":{
 "name":"Codestra Development",
 "statuses":"NEW_INQUIRY CONTACT_VALIDATION ATTEMPTING_CONTACT CONNECTED NEEDS_DISCOVERY DISCOVERY_SCHEDULED DISCOVERY_COMPLETED TECHNICAL_REVIEW SCOPE_PREPARATION ESTIMATE_PREPARATION PROPOSAL_SENT PROPOSAL_FOLLOW_UP NEGOTIATION CONTRACT_SENT DEPOSIT_PENDING DEPOSIT_RECEIVED PROJECT_HANDOFF IN_DEVELOPMENT CLIENT_REVIEW_UAT DELIVERED SUPPORT UPSELL_RETAINER WON".split(),
 "exceptions":"NO_BUDGET TIMELINE_MISMATCH PROJECT_ON_HOLD TECHNICALLY_NOT_FEASIBLE CLIENT_UNRESPONSIVE PROPOSAL_DECLINED LOST_TO_COMPETITOR DUPLICATE DO_NOT_CONTACT".split(),
 "appointments":"DISCOVERY_CALL TECHNICAL_CONSULTATION DEMO PROPOSAL_REVIEW CONTRACT_REVIEW PROJECT_KICKOFF CLIENT_UAT POST_LAUNCH_REVIEW".split(),
 "dispositions":{"DISCOVERY":"DISCOVERY_SCHEDULED","TECHREV":"TECHNICAL_REVIEW","PROPOSAL":"PROPOSAL_SENT","DEPOSIT":"DEPOSIT_RECEIVED"},
 "followups":{"CONNECTED":"CONTACT_FOLLOW_UP","PROPOSAL_SENT":"PROPOSAL_FOLLOW_UP"},
 "required":{"PROPOSAL_SENT":["proposal_reference","proposal_sent_at"]},
 "automations":"codestra_discovery_scheduled codestra_discovery_completed codestra_technical_review codestra_proposal_sent codestra_proposal_overdue codestra_contract_sent codestra_deposit_received codestra_project_handoff codestra_retainer_followup".split(),
 "kpis":"DISCOVERIES COMPLETED_DISCOVERIES TECHNICAL_REVIEWS PROPOSALS_SENT PROPOSAL_ACCEPTANCE_RATE DEPOSITS_RECEIVED PROJECTS_WON PROJECT_VALUE AVERAGE_SALES_CYCLE".split(),
},
"moneybee":{
 "name":"MoneyBee Business Loans",
 "statuses":"NEW_BUSINESS_LEAD CONTACT_BUSINESS_VALIDATION READY_TO_CALL ATTEMPTING_CONTACT CONNECTED INITIAL_QUALIFICATION PREQUALIFIED DOCUMENTS_REQUESTED DOCUMENTS_PARTIAL DOCUMENTS_RECEIVED APPLICATION_STARTED APPLICATION_COMPLETE UNDERWRITING_REVIEW ADDITIONAL_INFORMATION_REQUIRED OFFER_PREPARED OFFER_SENT OFFER_REVIEW ACCEPTED FUNDING_PENDING FUNDED POST_FUNDING_FOLLOW_UP SERVICING RENEWAL_RETENTION".split(),
 "exceptions":"NOT_ELIGIBLE INSUFFICIENT_DOCUMENTATION CUSTOMER_WITHDREW UNDERWRITING_DECLINED OFFER_DECLINED UNRESPONSIVE DUPLICATE INVALID_BUSINESS DO_NOT_CALL COMPLIANCE_HOLD".split(),
 "appointments":"PREQUALIFICATION_REVIEW DOCUMENT_REVIEW APPLICATION_COMPLETION UNDERWRITING_FOLLOW_UP OFFER_REVIEW FUNDING_FOLLOW_UP POST_FUNDING_REVIEW RENEWAL_REVIEW".split(),
 "dispositions":{"DOCREQ":"DOCUMENTS_REQUESTED","APPSTART":"APPLICATION_STARTED","UWREV":"UNDERWRITING_REVIEW","OFFER":"OFFER_SENT","FUNDED":"FUNDED"},
 "followups":{"CONNECTED":"CONTACT_FOLLOW_UP","DOCUMENTS_REQUESTED":"DOCUMENT_FOLLOW_UP","OFFER_SENT":"OFFER_FOLLOW_UP"},
 "required":{"DOCUMENTS_REQUESTED":["requested_documents","request_date"]},
 "automations":"moneybee_prequalified moneybee_documents_requested moneybee_documents_partial moneybee_documents_overdue moneybee_application_started moneybee_underwriting_followup moneybee_additional_info moneybee_offer_sent moneybee_funding_followup moneybee_post_funding moneybee_renewal".split(),
 "kpis":"PREQUALIFIED PREQUALIFICATION_RATE DOCUMENTS_REQUESTED DOCUMENT_COMPLETION_RATE APPLICATIONS_STARTED APPLICATIONS_COMPLETED UNDERWRITING_SUBMISSIONS OFFERS OFFER_ACCEPTANCE_RATE FUNDED FUNDED_CONVERSION_RATE TIME_TO_FUNDING".split(),
},
"senior_products":{
 "name":"Senior Citizen Products",
 "statuses":"NEW_LEAD CONTACT_VALIDATION ATTEMPTING_CONTACT CONNECTED NEEDS_IDENTIFIED PRODUCT_INFORMATION PRODUCT_SELECTED ORDER_PREPARATION PAYMENT_PENDING PAYMENT_CONFIRMED ORDER_PROCESSING SHIPPED DELIVERED CUSTOMER_FOLLOW_UP SUPPORT REORDER_DUE REORDER RETENTION".split(),
 "exceptions":"NOT_INTERESTED PRODUCT_NOT_SUITABLE PRICE_OBJECTION PAYMENT_FAILED ORDER_CANCELLED RETURN_REQUESTED REFUND_REQUESTED INVALID_CONTACT DO_NOT_CALL".split(),
 "appointments":"PRODUCT_CONSULTATION ORDER_FOLLOW_UP PAYMENT_FOLLOW_UP DELIVERY_FOLLOW_UP PRODUCT_SUPPORT REORDER_FOLLOW_UP".split(),
 "dispositions":{"PRODINFO":"PRODUCT_INFORMATION","ORDERPREP":"ORDER_PREPARATION","PAYPEND":"PAYMENT_PENDING","REORDER":"REORDER"},
 "followups":{"CONNECTED":"CONTACT_FOLLOW_UP","DELIVERED":"SATISFACTION_FOLLOW_UP"},
 "automations":"senior_product_selected senior_payment_pending senior_payment_confirmed senior_shipped senior_delivery_followup senior_support senior_reorder_due".split(),
 "kpis":"PRODUCT_CONSULTATIONS PRODUCTS_SELECTED ORDERS PAYMENTS_COMPLETED ORDERS_DELIVERED RETURNS REORDERS REORDER_RATE".split(),
},
"student_repayment":{
 "name":"Student Repayment",
 "statuses":"NEW_INQUIRY CONTACT_VALIDATION ATTEMPTING_CONTACT CONNECTED PROFILE_REVIEW ELIGIBILITY_REVIEW DOCUMENTS_REQUESTED DOCUMENTS_PARTIAL DOCUMENTS_RECEIVED COUNSELOR_APPOINTMENT PROGRAM_REVIEW APPLICATION_ENROLLMENT_STARTED SUBMITTED AWAITING_RESPONSE ADDITIONAL_INFORMATION_REQUIRED APPROVED_ENROLLED FOLLOW_UP RETENTION COMPLETED".split(),
 "exceptions":"NOT_ELIGIBLE DOCUMENTS_NOT_RECEIVED CUSTOMER_WITHDREW NOT_INTERESTED UNRESPONSIVE INVALID_CONTACT DUPLICATE DO_NOT_CALL COMPLIANCE_HOLD".split(),
 "appointments":"PROFILE_REVIEW ELIGIBILITY_REVIEW DOCUMENT_REVIEW COUNSELOR_APPOINTMENT APPLICATION_COMPLETION PROGRAM_REVIEW FOLLOW_UP_APPOINTMENT".split(),
 "dispositions":{},"followups":{"CONNECTED":"CONTACT_FOLLOW_UP","DOCUMENTS_REQUESTED":"DOCUMENT_FOLLOW_UP"},
 "automations":"student_eligibility_review student_documents_requested student_documents_missing student_counselor_appointment student_submission student_response_followup student_additional_info student_enrollment_followup".split(),
 "kpis":"ELIGIBILITY_REVIEWS ELIGIBLE DOCUMENT_COMPLETION_RATE COUNSELOR_APPOINTMENTS APPOINTMENT_ATTENDANCE_RATE APPLICATIONS_SUBMISSIONS ENROLLMENTS COMPLETION_RATE".split(),
}}

GLOBAL_AUTOMATIONS={
 "appointment_confirmation":"CDST_AppointmentCreated_v1",
 "appointment_24h_reminder":"CDST_Appointment24HourReminder_v1",
 "appointment_1h_reminder":"CDST_Appointment1HourReminder_v1",
 "customer_no_show":"CDST_CustomerNoShow_v1",
 "callback_overdue":"CDST_CallbackOverdue_v1",
 "lead_no_activity":"CDST_NoActivity_v1",
 "supervisor_escalation":"CDST_SupervisorEscalation_v1",
 "manager_escalation":"CDST_ManagerEscalation_v1",
 "daily_admin_report":"CDST_DailyAdminReport_v1",
}

COD_WEB_OUT_EMAIL_POLICY={
 "NEW_INQUIRY":("AGENT_DRAFT","cod_web_out_initial_outreach_v1"),
 "ATTEMPTING_CONTACT":("OPTIONAL_EMAIL","cod_web_out_followup_1_v1"),
 "CONNECTED":("OPTIONAL_EMAIL","cod_web_out_followup_2_v1"),
 "NEEDS_DISCOVERY":("AGENT_DRAFT","cod_web_out_discovery_invitation_v1"),
 "DISCOVERY_SCHEDULED":("AUTOMATIC_EMAIL","cod_web_out_discovery_confirmation_v1"),
 "DISCOVERY_COMPLETED":("AGENT_DRAFT","cod_web_out_post_discovery_followup_v1"),
 "PROPOSAL_SENT":("AGENT_DRAFT","cod_web_out_proposal_sent_v1"),
 "PROPOSAL_FOLLOW_UP":("AGENT_DRAFT","cod_web_out_proposal_followup_v1"),
 "CONTRACT_SENT":("AGENT_DRAFT","cod_web_out_contract_followup_v1"),
 "PROJECT_HANDOFF":("AUTOMATIC_EMAIL","cod_web_out_project_handoff_v1"),
 "CLIENT_UNRESPONSIVE":("REQUIRES_APPROVAL","cod_web_out_no_response_close_v1"),
}

COD_WEB_OUT_EMAIL_AUTOMATIONS={
 "cod_web_out_initial_outreach":"cod_web_out_initial_outreach_v1",
 "cod_web_out_followup_1":"cod_web_out_followup_1_v1",
 "cod_web_out_followup_2":"cod_web_out_followup_2_v1",
 "cod_web_out_discovery_invitation":"cod_web_out_discovery_invitation_v1",
 "cod_web_out_discovery_confirmation":"cod_web_out_discovery_confirmation_v1",
 "cod_web_out_discovery_reminder":"cod_web_out_discovery_reminder_v1",
 "cod_web_out_post_discovery_followup":"cod_web_out_post_discovery_followup_v1",
 "cod_web_out_proposal_sent":"cod_web_out_proposal_sent_v1",
 "cod_web_out_proposal_followup":"cod_web_out_proposal_followup_v1",
 "cod_web_out_contract_followup":"cod_web_out_contract_followup_v1",
 "cod_web_out_project_handoff":"cod_web_out_project_handoff_v1",
 "cod_web_out_no_response_close":"cod_web_out_no_response_close_v1",
}


def _title(value): return value.replace("_"," ").title()


def post_init_hook(env):
    Workflow=env["codestra.campaign.workflow"].sudo().with_context(active_test=False); Status=env["codestra.campaign.status"].sudo()
    for key,spec in WORKFLOWS.items():
        workflow=Workflow.search([("key","=",key)],limit=1) or Workflow.create({"key":key,"name":spec["name"],"active":False})
        status_by_code={}
        for sequence,code in enumerate(spec["statuses"]+spec["exceptions"],1):
            terminal=code in spec["exceptions"] or code in {"WON","COMPLETED"}
            values={"workflow_id":workflow.id,"code":code,"display_name":_title(code),"sequence":sequence*10,"terminal":terminal,"won":code=="WON","lost":code in spec["exceptions"],"report_category":code,"required_fields":spec.get("required",{}).get(code,[]),"vicidial_disposition_codes":[d for d,s in spec["dispositions"].items() if s==code],"ai_allowed_actions":[] if terminal else ["READ","SUGGEST_NEXT_ACTION"]}
            if code in spec["followups"]: values.update(next_action_required=True,default_next_action_type=spec["followups"][code],followup_delay_minutes=60,followup_sla_minutes=1440,supervisor_escalation_enabled=True,manager_escalation_enabled=True,n8n_workflow_key=f"{key}_{spec['followups'][code].lower()}")
            row=Status.search([("workflow_id","=",workflow.id),("code","=",code)],limit=1)
            if row: row.write(values)
            else: row=Status.create(values)
            status_by_code[code]=row
        normal=spec["statuses"]
        for index,code in enumerate(normal[:-1]): status_by_code[code].write({"allowed_next_status_ids":[(6,0,[status_by_code[normal[index+1]].id]+[status_by_code[x].id for x in spec["exceptions"]])]})
        for code,action in spec["followups"].items():
            model=env["codestra.campaign.followup.rule"].sudo(); values={"workflow_id":workflow.id,"status_id":status_by_code[code].id,"next_action_type":action,"delay_minutes":60,"agent_reminder_minutes":0,"supervisor_escalation_minutes":60,"manager_escalation_minutes":240}; row=model.search([("status_id","=",status_by_code[code].id)],limit=1); row.write(values) if row else model.create(values)
        types={}
        for code in spec["appointments"]:
            model=env["codestra.campaign.appointment.type"].sudo(); values={"workflow_id":workflow.id,"code":code,"name":_title(code)}; row=model.search([("workflow_id","=",workflow.id),("code","=",code)],limit=1); row.write(values) if row else model.create(values)
        for disposition,status in spec["dispositions"].items():
            model=env["codestra.campaign.disposition.mapping"].sudo(); values={"workflow_id":workflow.id,"disposition_code":disposition,"status_id":status_by_code[status].id}; row=model.search([("workflow_id","=",workflow.id),("disposition_code","=",disposition)],limit=1); row.write(values) if row else model.create(values)
        for code in spec["kpis"]:
            model=env["codestra.campaign.kpi"].sudo(); values={"workflow_id":workflow.id,"code":code,"name":_title(code),"aggregation":"rate" if code.endswith("RATE") else "count"}; row=model.search([("workflow_id","=",workflow.id),("code","=",code)],limit=1); row.write(values) if row else model.create(values)
        for status,action in spec["followups"].items():
            model=env["codestra.campaign.automation"].sudo().with_context(active_test=False)
            registry_name=f"{key}_{action.lower()}"
            values={"workflow_id":workflow.id,"key":registry_name,"event_type":"crm.followup.due.v1",
                    "n8n_workflow_key":"CDST_FollowupDue_v1","active":False}  # gitleaks:allow -- public workflow name
            row=model.search([("workflow_id","=",workflow.id),("key","=",registry_name)],limit=1)
            row.write(values) if row else model.create(values)
        for automation_key in spec["automations"]:
            model=env["codestra.campaign.automation"].sudo().with_context(active_test=False)
            values={"workflow_id":workflow.id,"key":automation_key,
                    "event_type":"crm.campaign.automation.requested.v1",
                    "n8n_workflow_key":automation_key,"active":False}
            row=model.search([("workflow_id","=",workflow.id),("key","=",automation_key)],limit=1)
            row.write(values) if row else model.create(values)
        for automation_key,n8n_workflow_key in GLOBAL_AUTOMATIONS.items():
            model=env["codestra.campaign.automation"].sudo().with_context(active_test=False)
            values={"workflow_id":workflow.id,"key":automation_key,"event_type":f"crm.{automation_key}.v1","n8n_workflow_key":n8n_workflow_key,"active":False}
            row=model.search([("workflow_id","=",workflow.id),("key","=",automation_key)],limit=1)
            row.write(values) if row else model.create(values)

    workflow=Workflow.search([("key","=","codestra_development")],limit=1)
    campaign=env["call.center.campaign"].sudo().with_context(active_test=False).search([
        ("id","=",6),("code","=","COD-WEB-OUT")
    ],limit=1)
    canary_approved=env["ir.config_parameter"].sudo().get_param(
        "codestra.cod_web_out.canary_provisioning_approved","false"
    ).lower()=="true"
    if campaign and workflow and canary_approved:
        workflow.write({"campaign_id":campaign.id,"active":False,"lifecycle_state":"STAGING"})
        Template=env["mail.template"].sudo().with_context(active_test=False)
        templates={row.codestra_template_key:row for row in Template.search([
            ("codestra_template_key","in",list(COD_WEB_OUT_EMAIL_AUTOMATIONS.values()))
        ])}
        for template in templates.values():
            template.write({"codestra_campaign_id":campaign.id})
        for status in workflow.status_ids:
            behavior,key=COD_WEB_OUT_EMAIL_POLICY.get(status.code,("NO_EMAIL",None))
            status.write({"email_behavior":behavior,"email_template_id":templates[key].id if key in templates else False})
        Automation=env["codestra.campaign.automation"].sudo().with_context(active_test=False)
        for key,template_key in COD_WEB_OUT_EMAIL_AUTOMATIONS.items():
            values={"workflow_id":workflow.id,"key":key,"event_type":"crm.email.automation.requested.v1",
                    "n8n_workflow_key":"CDST_EmailSend_v1","email_template_id":templates[template_key].id,
                    "activation_mode":"CANARY_ONLY","active":True}
            row=Automation.search([("workflow_id","=",workflow.id),("key","=",key)],limit=1)
            row.write(values) if row else Automation.create(values)
    # Preserve legacy records without guessing a campaign-specific lifecycle.
    # Administrators can resolve this queue after approving exact campaign and
    # workflow bindings.
    legacy_leads=env["crm.lead"].sudo().with_context(active_test=False).search([
        "|",("call_center_campaign_id","=",False),("codestra_workflow_id","=",False)
    ])
    if legacy_leads:
        legacy_leads.write({"migration_review_required":True})
