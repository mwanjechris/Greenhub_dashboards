#!/bin/bash
# Recover /odoo after greenhub_dashboards asset crash.
set -euo pipefail
CONF="${1:-/etc/odoo19.conf}"
DB="${2:-greenhub19test.techthings.dev}"
echo "Deactivating broken ir.asset rows on $DB ..."
# Prefer odoo shell (uses same DB settings as the service)
python3 - <<PY
import odoo
from odoo.tools import config
config.parse_config(['-c', '$CONF', '-d', '$DB'])
import odoo.service.db
from odoo.api import Environment
import odoo.modules.registry as registry
reg = registry.Registry('$DB')
with reg.cursor() as cr:
    env = Environment(cr, 1, {})
    assets = env['ir.asset'].sudo().search([
        '|', ('path', 'ilike', 'greenhub_dash'), ('path', 'ilike', 'Greenhub_dash'),
    ])
    print('found', len(assets), 'assets')
    for a in assets:
        print(' ', a.id, a.active, a.path)
    if assets:
        assets.write({'active': False})
    # Clear asset caches
    env.registry.clear_cache()
    cr.commit()
    print('deactivated; cache cleared')
PY
echo "Restart Odoo service after this."
