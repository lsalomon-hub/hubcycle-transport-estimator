#!/usr/bin/env python3
"""
Regenerate products.json from a raw Odoo export.

Input:  /tmp/odoo_products.json  (raw export produced by Claude via the
                                  hubcycle-db MCP query — see refresh.sh)
Output: <repo>/products.json     (fetched at runtime by index.html)

This script performs the name-matching between Odoo products and the
curated PRODUCTS dict embedded in index.html, to pre-fill density/state
where possible.
"""
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
ODOO_JSON = Path("/tmp/odoo_products.json")
INDEX_HTML = REPO / "index.html"
OUT_JSON = REPO / "products.json"


def extract_curated(html_text: str) -> dict:
    m = re.search(r"const PRODUCTS = \{(.*?)\n\s*\};", html_text, re.DOTALL)
    if not m:
        raise RuntimeError("Couldn't find PRODUCTS = { ... } block in index.html")
    entry_re = re.compile(
        r'"([^"]+)":\s*\{\s*density:\s*([\d.]+),\s*marketPrice:\s*([\d.]+),\s*state:\s*"([^"]+)"\s*\}'
    )
    return {
        name: {"density": float(d), "marketPrice": float(p), "state": s}
        for name, d, p, s in entry_re.findall(m.group(1))
    }


def tokens(s: str) -> set:
    s = re.sub(r"[^a-z0-9]+", " ", s.lower())
    return set(s.split())


STOP = {"the","a","of","and","with","for","en","de","la","le","grade","quality","extract","extraction"}
FORM = {
    "whole","powder","crushed","broken","fines","deoiled","granulated","minced",
    "skin","husk","husks","dried","fresh","frozen","concentrate","juice","cake",
    "cakes","pomace","peel","shell","shells","berry","berries","chips","pellets",
    "ht","liquid",
}


def best_match(odoo_name: str, curated: dict):
    best, best_score = None, 0.0
    ot = tokens(odoo_name) - STOP
    if not ot:
        return None
    for cname, _ in curated.items():
        ct = tokens(cname) - STOP
        if not ct:
            continue
        inter = ot & ct
        if not inter or not (inter - FORM):
            continue
        jaccard = len(inter) / len(ot | ct)
        bonus = 0.0
        of, cf = ot & FORM, ct & FORM
        if of and cf:
            bonus += 0.20 if (inter & FORM) else -0.30
        s = jaccard + bonus
        if s > best_score:
            best_score, best = s, cname
    return best if best_score >= 0.35 else None


def main() -> int:
    if not ODOO_JSON.exists():
        print(f"[ERROR] Missing {ODOO_JSON}", file=sys.stderr)
        print("Ask Claude to run the hubcycle-db MCP query first.", file=sys.stderr)
        return 1

    age_s = (datetime.now().timestamp() - ODOO_JSON.stat().st_mtime)
    if age_s > 3600:
        mins = int(age_s / 60)
        print(f"[WARN] {ODOO_JSON} is {mins} min old — data may be stale.", file=sys.stderr)

    odoo_products = json.loads(ODOO_JSON.read_text())
    curated = extract_curated(INDEX_HTML.read_text())
    print(f"Loaded {len(odoo_products)} Odoo products, {len(curated)} curated density entries")

    by_cat = {}
    match_count = 0
    supplier_count = 0
    for p in odoo_products:
        name = (p.get("name") or "").strip()
        code = (p.get("default_code") or "").strip()
        if not name or not code:
            continue
        # Primary purchase price: first supplier (by sequence) from supplier_info.
        # Fall back to standard_price (Odoo cost field) if no supplier is set.
        supplier_price = p.get("supplier_price")
        standard_price = p.get("standard_price")
        if supplier_price is not None:
            price = round(float(supplier_price), 4)
            price_source = "supplier"
            supplier_count += 1
        else:
            price = round(float(standard_price or 0), 4)
            price_source = "standard"
        entry = {
            "code": code,
            "name": name,
            "price": price,
            "priceSource": price_source,
        }
        supplier_name = p.get("supplier_name")
        if supplier_name:
            entry["supplier"] = supplier_name
        mname = best_match(name, curated)
        if mname:
            entry["density"] = curated[mname]["density"]
            entry["state"] = curated[mname]["state"]
            entry["matchedTo"] = mname
            match_count += 1
        cat = p.get("categ_name") or "Other"
        by_cat.setdefault(cat, []).append(entry)

    for cat in by_cat:
        by_cat[cat].sort(key=lambda x: x["name"].lower())

    priority_last = {"All", "Hubcycle products", "Service"}
    ordered = sorted([c for c in by_cat if c not in priority_last])
    ordered += sorted([c for c in by_cat if c in priority_last])

    payload = {
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "total_products": sum(len(v) for v in by_cat.values()),
        "matched_density": match_count,
        "with_supplier_price": supplier_count,
        "categories": {cat: by_cat[cat] for cat in ordered},
    }
    OUT_JSON.write_text(json.dumps(payload, ensure_ascii=False, separators=(",", ":")))

    print(f"Wrote {OUT_JSON.relative_to(REPO)} ({OUT_JSON.stat().st_size} bytes)")
    print(f"Matched {match_count}/{payload['total_products']} products with curated density")
    print(f"Supplier prices: {supplier_count}/{payload['total_products']} from supplier_info (rest = standard_price)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
