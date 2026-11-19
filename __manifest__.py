{
    "name": "Green Hub Dashboards",
    "summary": "Server-computed KPIs, weekly history and OWL dashboards for Green Hub",
    "author": "Tech Things",
    "website": "https://www.techthings.it",
    "category": "Productivity",
    "version": "19.0.1.1.1",
    "license": "LGPL-3",
    "depends": ["greenhub", "fleet", "account", "account_reports", "account_budget", "mail"],
    # Explicit installs only: the Green Hub server is shared by several tenants.
    "auto_install": False,
    "post_init_hook": "post_init_hook",
    "data": [
        "security/security.xml",
        "security/ir.model.access.csv",
        "data/default_config.xml",
        "data/default_rules.xml",
        "data/cron.xml",
        "views/config_views.xml",
        "views/snapshot_views.xml",
        "views/drill_views.xml",
        "views/config2_views.xml",
        "views/dashboard_actions.xml",
        "views/menus.xml",
    ],
    # Temporarily empty: live host cannot resolve greenhub_dashboards/static/* (404),
    # which breaks web.assets_web and the whole backend. Re-enable after folder
    # name + saas-addons sync are confirmed on the greenhub19test host.
    "assets": {},
    "application": True,
}
