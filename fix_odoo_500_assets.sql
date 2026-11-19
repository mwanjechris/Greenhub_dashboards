-- Emergency: deactivate broken dashboard assets so /odoo loads again.
-- Prefer upgrading Greenhub_dashboards to 19.0.1.1.3 instead (correct asset paths).

BEGIN;

UPDATE ir_asset
SET active = false
WHERE path ILIKE '%greenhub_dash%'
   OR path ILIKE '%Greenhub_dash%';

DELETE FROM ir_attachment
WHERE name ILIKE '%web.assets_web%'
   OR name ILIKE '%web.assets_backend%'
   OR url ILIKE '%web.assets_web%'
   OR url ILIKE '%web.assets_backend%';

COMMIT;
