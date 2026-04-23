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
CURATED_JSON = REPO / "curated.json"
OUT_JSON = REPO / "products.json"


def load_curated() -> dict:
    if not CURATED_JSON.exists():
        raise RuntimeError(f"Missing {CURATED_JSON}")
    data = json.loads(CURATED_JSON.read_text())
    return data.get("products", {})


def tokens(s: str) -> set:
    s = re.sub(r"[^a-z0-9]+", " ", s.lower())
    out = set()
    for w in s.split():
        out.add(w)
        # Also add singular form so "husk" matches "husks", "shell" matches "shells"
        if len(w) > 3 and w.endswith("s") and not w.endswith("ss"):
            out.add(w[:-1])
    return out


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
    curated = load_curated()
    print(f"Loaded {len(odoo_products)} Odoo products, {len(curated)} curated density entries")

    by_cat = {}
    match_count = 0
    with_supplier = 0
    for p in odoo_products:
        name = (p.get("name") or "").strip()
        code = (p.get("default_code") or "").strip()
        if not name or not code:
            continue
        # Prices: list of supplier prices sorted most-recently-updated first
        # (per SQL ORDER BY odoo_write_date DESC). Default to prices[0].price.
        # Fall back to standard_price if no supplier_info entry exists.
        prices = p.get("prices") or []
        if prices:
            price = round(float(prices[0]["price"]), 4)
            price_source = "supplier"
            with_supplier += 1
        else:
            price = round(float(p.get("standard_price") or 0), 4)
            price_source = "standard"
        entry = {
            "code": code,
            "name": name,
            "price": price,
            "priceSource": price_source,
        }
        origin = p.get("origin_country")
        if origin:
            entry["originCountry"] = origin
            entry["originSource"] = p.get("origin_source") or "unknown"
        if len(prices) > 1:
            # Pass full list so UI can show alternatives when user hits ambiguity
            entry["prices"] = [
                {
                    "price": round(float(pr["price"]), 4),
                    "minQty": float(pr.get("min_qty") or 0),
                    "updated": pr.get("updated") or None,
                }
                for pr in prices
            ]
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
        "with_supplier_price": with_supplier,
        "categories": {cat: by_cat[cat] for cat in ordered},
    }
    OUT_JSON.write_text(json.dumps(payload, ensure_ascii=False, separators=(",", ":")))

    print(f"Wrote {OUT_JSON.relative_to(REPO)} ({OUT_JSON.stat().st_size} bytes)")
    print(f"Matched {match_count}/{payload['total_products']} products with curated density")
    print(f"Supplier prices: {with_supplier}/{payload['total_products']} from supplier_info (rest = standard_price)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
