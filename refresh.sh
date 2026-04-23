#!/bin/bash
# Regenerate products.json from a fresh Odoo export, commit & push to deploy.
#
# PREREQUISITE:
#   Ask Claude Code (with the hubcycle-db MCP) to run this SQL and save
#   the result as /tmp/odoo_products.json:
#
#     WITH all_prices AS (
#       SELECT template_odoo_id,
#              jsonb_agg(
#                jsonb_build_object(
#                  'price', price,
#                  'min_qty', min_qty,
#                  'updated', to_char(odoo_write_date, 'YYYY-MM-DD')
#                )
#                ORDER BY odoo_write_date DESC NULLS LAST, sequence ASC
#              ) AS prices
#       FROM supplier_info
#       GROUP BY template_odoo_id
#     )
#     SELECT pt.default_code, pt.name, pt.categ_name,
#            COALESCE(pt.standard_price, 0) AS standard_price,
#            ap.prices
#     FROM product_templates pt
#     LEFT JOIN all_prices ap ON ap.template_odoo_id = pt.odoo_id
#     WHERE pt.is_active = true AND pt.categ_name != 'Service'
#       AND pt.default_code IS NOT NULL AND pt.default_code != ''
#     ORDER BY pt.categ_name, pt.name;
#
# Then run this script.

set -euo pipefail

REPO_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$REPO_DIR"

if [ ! -f /tmp/odoo_products.json ]; then
  echo "[ERROR] /tmp/odoo_products.json not found."
  echo ""
  echo "Open Claude Code in this repo and say:"
  echo "  \"refresh les produits Odoo\""
  echo ""
  echo "Claude will run the SQL via the hubcycle-db MCP and save the result."
  exit 1
fi

echo "▶ Regenerating products.json from /tmp/odoo_products.json …"
python3 scripts/refresh_products.py

if git diff --quiet products.json; then
  echo "✓ products.json is already up to date — nothing to commit."
  exit 0
fi

DIFF_STAT=$(git diff --stat products.json)
echo ""
echo "Changes detected:"
echo "$DIFF_STAT"
echo ""

echo "▶ Committing and pushing …"
git add products.json
git commit -m "Refresh Odoo products ($(date -u +%Y-%m-%dT%H:%MZ))"
git push origin main

echo ""
echo "✓ Done. Render will auto-deploy in ~1 minute."
