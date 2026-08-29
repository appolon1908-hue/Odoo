from odoo import api, SUPERUSER_ID


DOMAINS = (
    ("Codestra Agency", "CODESTRA_AGENCY", "codestra.agency"),
    ("Codestra", "CODESTRA", "codestra.co"),
    ("Nativo English", "NATIVO_ENGLISH", "nativoenglish.com"),
    ("MoneyBee Loans", "MONEYBEE_LOANS", "moneybeeloan.com"),
    ("Codestra Cloud", "CODESTRA_CLOUD", "codestra.cloud"),
    ("Codestra Digital", "CODESTRA_DIGITAL", "codestra.digital"),
    ("Codestra Media", "CODESTRA_MEDIA", "codestra.media"),
    ("MoneyBee", "MONEYBEE", "moneybee.loan"),
    ("Klyrow", "KLYROW", "klyrow.com"),
    ("Beyvra", "BEYVRA", "beyvra.com"),
    ("Kyqra", "KYQRA", "kyqra.com"),
    ("Breero", "BREERO", "breero.com"),
    ("Breero Shop", "BREERO_SHOP", "breero.shop"),
    ("Telnexa", "TELNEXA", "telnexa.co"),
)


def migrate(cr, version):
    """Provision exact, loop-safe Odoo support and billing destinations."""
    env = api.Environment(cr, SUPERUSER_ID, {})
    company = env.ref("base.main_company")
    queue_by_local = {
        "support": env.ref("codestra_mail_inbox.queue_type_support"),
        "billing": env.ref("codestra_mail_inbox.queue_type_billing"),
    }
    for name, code, domain in DOMAINS:
        alias_domain = env["mail.alias.domain"].search([("name", "=", domain)], limit=1)
        if not alias_domain:
            alias_domain = env["mail.alias.domain"].create({"name": domain})
        brand = env["codestra.mail.brand"].search([("domain", "=", domain)], limit=1)
        if not brand:
            brand = env["codestra.mail.brand"].create({
                "name": name, "code": code, "domain": domain, "company_id": company.id,
            })
        for local_part, queue_type in queue_by_local.items():
            team = env["codestra.mail.team"].search([
                ("brand_id", "=", brand.id), ("queue_type_id", "=", queue_type.id),
            ], limit=1)
            if not team:
                team = env["codestra.mail.team"].create({
                    "name": f"{name} {queue_type.name}",
                    "brand_id": brand.id,
                    "queue_type_id": queue_type.id,
                    "alias_name": local_part,
                    "alias_domain_id": alias_domain.id,
                })
            sender = f"{local_part}@{domain}"
            if not env["codestra.mail.sender.allowlist"].search_count([("sender", "=", sender)]):
                env["codestra.mail.sender.allowlist"].create({
                    "team_id": team.id, "sender": sender, "active": True,
                })
