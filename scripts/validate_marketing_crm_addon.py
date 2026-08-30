from pathlib import Path

ROOT = Path('custom-addons/codestra_marketing_crm')


def main() -> None:
    required = [
        ROOT / '__manifest__.py',
        ROOT / 'models' / 'crm_lead.py',
        ROOT / 'views' / 'crm_lead_views.xml',
        ROOT / 'tests' / 'test_marketing_crm.py',
    ]
    for path in required:
        assert path.exists(), f'missing:{path}'
    model = (ROOT / 'models' / 'crm_lead.py').read_text(encoding='utf-8').lower()
    assert 'tenant' in model
    assert 'campaign' in model
    assert 'provider' in model
    assert 'requests.' not in model and 'httpx.' not in model, 'odoo_must_not_call_ad_provider_directly'
    print('odoo marketing CRM addon certification passed')


if __name__ == '__main__':
    main()
