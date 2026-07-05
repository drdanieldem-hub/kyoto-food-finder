#!/usr/bin/env python3
"""
Adapter: project the Tabelog/Hotpepper pipeline output into the record shape
that ../build.py expects.

If a Hotpepper cross-ref was run, prefer its English/photo/URL fields; fall
back to Tabelog-only otherwise. The result is what build.py loads as
final_restaurants_merged.json.
"""
from __future__ import annotations

import argparse
import json
import os
import sys


def project(tab: dict, hp: dict | None) -> dict:
    """Combine a Tabelog row + optional Hotpepper row into a build.py record."""
    # Lat/lng come from Tabelog (which has them on every restaurant); Hotpepper
    # is only cross-reference metadata.
    lat = tab.get("lat")
    lng = tab.get("lng")

    out = {
        "name": tab.get("name", ""),
        # Hotpepper English-friendly name when available; else Tabelog (Japanese)
        "google_name": (hp or {}).get("hotpepper_name_en", ""),  # reuse field name for build.py compat
        "tabelog_rating": tab.get("tabelog_rating"),
        "google_rating": 0.0,                                     # not collected
        "google_user_ratings_total": tab.get("tabelog_review_count", 0),  # reuse as proxy
        "cuisine": tab.get("cuisine", ""),
        "area": tab.get("area", ""),
        "address": tab.get("address", ""),
        "google_address": (hp or {}).get("hotpepper_address", ""),
        "google_place_id": (hp or {}).get("hotpepper_id", ""),
        "tabelog_url": tab.get("url", ""),
        "ward": tab.get("ward", ""),
        "lat": lat,
        "lng": lng,
        # Hotpepper extras (used by build.py if present)
        "hotpepper_description": (hp or {}).get("hotpepper_description", ""),
        "hotpepper_photo_url": (hp or {}).get("hotpepper_photo_url", ""),
        "hotpepper_url": (hp or {}).get("hotpepper_url", ""),
        "tabelog_review_count": tab.get("tabelog_review_count", 0),
        # No hours data unless we layer that on later
        "regular_opening_hours": [],
        "current_open_now": None,
        "hours_source": "",
    }
    return out


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--tabelog", default="tabelog_kyoto_full_flat.json",
                    help="tabelog_kyoto_full_flat.json (Stage 2 output)")
    ap.add_argument("--hotpepper", default="final_restaurants_kyoto_hotpepper.json",
                    help="hotpepper cross-ref output (optional — empty/None skips)")
    ap.add_argument("--out", default="final_restaurants_merged.json",
                    help="projected output for build.py")
    args = ap.parse_args()

    base = os.path.dirname(os.path.abspath(__file__))
    tabelog_path = os.path.join(base, args.tabelog)
    hotpepper_path = os.path.join(base, args.hotpepper)
    out_path = os.path.join(base, "..", args.out)

    if not os.path.exists(tabelog_path):
        sys.exit(f"Missing {tabelog_path}. Run tabelog_kyoto_scraper.py first.")

    tabelog_rows = json.load(open(tabelog_path, encoding="utf-8"))
    hp_rows = []
    if os.path.exists(hotpepper_path):
        hp_rows = json.load(open(hotpepper_path, encoding="utf-8"))
        # Index by Tabelog URL for quick join
        by_url = {r.get("tabelog_url"): r for r in hp_rows if r.get("tabelog_url")}
        print(f"Loaded {len(tabelog_rows)} Tabelog rows, {len(hp_rows)} Hotpepper rows")
    else:
        by_url = {}
        print(f"Loaded {len(tabelog_rows)} Tabelog rows (no Hotpepper cross-ref)")

    projected = [project(t, by_url.get(t.get("url", ""))) for t in tabelog_rows]
    geo = sum(1 for p in projected if p.get("lat"))
    matched = sum(1 for p in projected if p.get("google_place_id"))
    print(f"Projected {len(projected)} records ({geo} with coords, {matched} with Hotpepper)")

    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(projected, f, ensure_ascii=False, indent=2)
    print(f"Wrote {out_path}")


if __name__ == "__main__":
    main()
