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


def provision_exact_destinations(env):
    company = env.ref("base.main_company")
    queues = {
        "support": env.ref("codestra_mail_inbox.queue_type_support"),
        "billing": env.ref("codestra_mail_inbox.queue_type_billing"),
    }
    for name, code, domain in DOMAINS:
        alias_domain = env["mail.alias.domain"].search([("name", "=", domain)], limit=1)
        alias_domain = alias_domain or env["mail.alias.domain"].create({"name": domain})
        brand = env["codestra.mail.brand"].search([("domain", "=", domain)], limit=1)
        brand = brand or env["codestra.mail.brand"].create({
            "name": name, "code": code, "domain": domain, "company_id": company.id,
        })
        for local_part, queue in queues.items():
            team = env["codestra.mail.team"].search([
                ("brand_id", "=", brand.id), ("queue_type_id", "=", queue.id),
            ], limit=1)
            team = team or env["codestra.mail.team"].create({
                "name": f"{name} {queue.name}", "brand_id": brand.id,
                "queue_type_id": queue.id, "alias_name": local_part,
                "alias_domain_id": alias_domain.id,
            })
            sender = f"{local_part}@{domain}"
            if not env["codestra.mail.sender.allowlist"].search_count([("sender", "=", sender)]):
                env["codestra.mail.sender.allowlist"].create({"team_id": team.id, "sender": sender})


def post_init_hook(env):
    """Keep restored baseline companies and unrelated aliases domain-neutral.

    Odoo assigns the first ever alias domain globally. The certified baseline had
    no alias domains, so undo that framework convenience after our explicit
    domain/team data is loaded. Team aliases retain their exact domains.
    """
    if not isinstance(env, api.Environment):
        env = api.Environment(env, SUPERUSER_ID, {})
    provision_exact_destinations(env)
    team_aliases = env["codestra.mail.team"].sudo().search([]).mapped("alias_id")
    env["res.company"].sudo().search([]).write({"alias_domain_id": False})
    env["mail.alias"].sudo().search([("id", "not in", team_aliases.ids)]).write({"alias_domain_id": False})
