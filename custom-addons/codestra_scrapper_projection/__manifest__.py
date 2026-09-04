{
    "name": "Codestra Scrapper Projection",
    "summary": "Tenant-bound versioned projection of normalized Scrapper businesses",
    "version": "19.0.1.1.0",
    "author": "Codestra",
    "category": "Services/Integration",
    "license": "LGPL-3",
    "depends": ["base", "contacts"],
    "data": [
        "security/codestra_scrapper_groups.xml",
        "security/ir.model.access.csv",
        "views/scrapper_projection_views.xml",
    ],
    "installable": True,
    "application": True,
}
