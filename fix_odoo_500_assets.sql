-- Restore /odoo when greenhub_dashboards assets 404 / crash the web client.
-- Run on the DB that serves greenhub19test.techthings.dev, then restart Odoo.

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

SELECT id, bundle, path, active
FROM ir_asset
WHERE path ILIKE '%greenhub_dash%'
   OR path ILIKE '%Greenhub_dash%'
ORDER BY id;

COMMIT;
