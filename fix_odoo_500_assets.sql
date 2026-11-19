-- Run on greenhub19test.techthings.dev to restore /odoo immediately:
--   psql -U odoo19b -d greenhub19test.techthings.dev -f fix_odoo_500_assets.sql
-- Or as odoo19 if that is the DB user.

BEGIN;

-- 1) Disable broken dashboard asset paths that crash web.assets_backend
UPDATE ir_asset
SET active = false
WHERE path ILIKE '%greenhub_dash%'
   OR path ILIKE '%Greenhub_dash%';

-- 2) Show what remains
SELECT id, name, bundle, path, active
FROM ir_asset
WHERE path ILIKE '%greenhub_dash%'
   OR path ILIKE '%Greenhub_dash%'
ORDER BY id;

COMMIT;
