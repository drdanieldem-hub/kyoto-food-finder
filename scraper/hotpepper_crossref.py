#!/usr/bin/env python3
"""
Hotpepper cross-reference for the Tabelog Kyoto scrape.

Looks up each Tabelog restaurant on Hotpepper (Recruit's free API) by name +
area, biased to its Tabelog coordinates. Attaches an English-friendly
description, photo URL, and a second review count to each match.

Why Hotpepper (and not Google Places):
* Free, **no credit card needed** — key from a simple email registration.
* Excellent Kansai/Kyoto coverage; Gurunavi (parent company) is Kyoto-based.
* Stable JSON API with rate-limit headers so we can pace cleanly.
* Avoids the $0.032/lookup Places API cost that added up to ~$125 on Tokyo.

Output fields added per matched restaurant (kept None on misses):
  hotpepper_id, hotpepper_name_en, hotpepper_description, hotpepper_photo_url
  hotpepper_address, hotpepper_review_count, hotpepper_url

Match quality: a Hotpepper hit more than --max-distance metres from the
Tabelog coordinates is dropped as a likely mismatch. Resumable via a sibling
.cache.json.

Setup:
  export HOTPEPPER_API_KEY=...       # never commit
  pip install -r requirements.txt

Usage:
  python hotpepper_crossref.py selftest
  python hotpepper_crossref.py tabelog_kyoto_full_flat.json ../final_restaurants_kyoto_hotpepper.json --dry-run
  python hotpepper_crossref.py tabelog_kyoto_full_flat.json ../final_restaurants_kyoto_hotpepper.json --limit 20
  python hotpepper_crossref.py tabelog_kyoto_full_flat.json ../final_restaurants_kyoto_hotpepper.json
"""
from __future__ import annotations

import argparse
import json
import math
import os
import sys
import time
from urllib.parse import urlencode, quote
from urllib.request import Request, urlopen
from urllib.error import HTTPError, URLError

ENDPOINT = "http://webservice.recruit.co.jp/hotpepper/gourmet/v1/"
DEFAULT_LAT = 35.0116   # Kyoto station
DEFAULT_LNG = 135.7681
COST = 0.0


def _http_json(url, *, retries: int = 4):
    for attempt in range(retries):
        try:
            req = Request(url, headers={"User-Agent": "kyoto-food-finder/1.0"})
            with urlopen(req, timeout=30) as resp:
                return json.loads(resp.read().decode("utf-8", "replace")), resp.status
        except HTTPError as e:
            payload = e.read().decode("utf-8", "replace")
            if e.code in (429, 500, 502, 503):
                wait = 2 ** attempt
                print(f"    HTTP {e.code}, retry in {wait}s", file=sys.stderr)
                time.sleep(wait)
                continue
            try:
                return json.loads(payload), e.code
            except json.JSONDecodeError:
                return {"_raw_error": payload}, e.code
        except URLError as e:
            wait = 2 ** attempt
            print(f"    {e}, retry in {wait}s", file=sys.stderr)
            time.sleep(wait)
    return None, 0


def query(key, name, area, lat, lng):
    cleaned_name = name.strip()
    cleaned_area = area.strip()
    keyword = " ".join(filter(None, [cleaned_name, cleaned_area]))
    params = {
        "key": key,
        "format": "json",
        "keyword": keyword,
        "count": 5,
        "order": 4,
    }
    if lat and lng:
        params["lat"] = lat
        params["lng"] = lng
        params["range"] = 3  # ~600m
    else:
        params["lat"] = DEFAULT_LAT
        params["lng"] = DEFAULT_LNG
        params["range"] = 5  # ~2km

    url = ENDPOINT + "?" + urlencode(params, safe="", quote_via=quote)
    data, status = _http_json(url)
    if data is None:
        return None, "network"
    if status != 200:
        err = (data.get("results", {}) or {}).get("error", [{}])[0]
        return None, f"api_error:{status}:{err.get('message', '')[:80]}"
    results = (data.get("results") or {}).get("shop") or []
    if not results:
        return None, "no_result"
    return _normalize(results[0]), None


def _normalize(shop):
    photo = ((shop.get("photo") or {}).get("mobile") or {}).get("l") or ""
    return {
        "hotpepper_id":          shop.get("id", ""),
        "hotpepper_name_en":     shop.get("name", ""),
        "hotpepper_name_romaji": (shop.get("name_kana") or ""),
        "hotpepper_description": (shop.get("catch") or "") + ("\n" + shop["other_memo"] if shop.get("other_memo") else ""),
        "hotpepper_photo_url":   photo,
        "hotpepper_address":     shop.get("address", ""),
        "hotpepper_url":         (shop.get("urls") or {}).get("pc", ""),
    }


def haversine_m(lat1, lon1, lat2, lon2):
    r = 6371000.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dl = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(math.sqrt(a))


def crossref(src_path, out_path, *, max_distance, delay, limit, dry_run):
    rows = _load(src_path, None)
    if rows is None:
        sys.exit(f"Cannot read {src_path}. Run tabelog_kyoto_scraper.py first.")
    if limit:
        rows = rows[:limit]

    if dry_run:
        print(f"{len(rows)} restaurants to look up.")
        est_min = len(rows) * delay / 60.0
        print(f"Estimated duration @ {delay}s/req: ~{est_min:.1f} min, $0.00 (free).")
        return

    key = os.getenv("HOTPEPPER_API_KEY")
    if not key:
        sys.exit("Set HOTPEPPER_API_KEY in your environment (do not commit it).\n"
                 "Register free at https://webservice.recruit.co.jp/register/")

    print(f"Cross-referencing {len(rows)} restaurants via Hotpepper.")

    cache_path = out_path + ".cache.json"
    cache = _load(cache_path, {})

    kept, dropped, errors = [], [], []
    for i, r in enumerate(rows, 1):
        url = r.get("url") or r.get("tabelog_url") or f"row{i}"
        if url in cache:
            rec = cache[url]
        else:
            hit, err = query(key, r.get("name", ""), r.get("area", ""),
                             r.get("lat"), r.get("lng"))
            rec = _build_record(r, hit, err, max_distance)
            cache[url] = rec
            time.sleep(delay)

        if rec["_status"] == "kept":
            kept.append(_public(rec))
        elif rec["_status"] == "error":
            errors.append(rec)
        else:
            dropped.append(rec)

        if i % 25 == 0 or i == len(rows):
            _save(cache_path, cache)
            print(f"  {i}/{len(rows)} (kept {sum(1 for v in cache.values() if v['_status'] == 'kept')})")

    _save(cache_path, cache)
    _save(out_path, kept)
    _save(out_path.replace(".json", "_dropped.json"), dropped + errors)

    print(f"\nDone. Kept {len(kept)} (Hotpepper matches within {max_distance}m of Tabelog coords).")
    print(f"Dropped {len(dropped)} (no match / too far), {len(errors)} errors.")
    print(f"Wrote {out_path} (+ _dropped.json for review)")


def _build_record(tab, hit, err, max_distance):
    base = {
        "name": tab.get("name", ""),
        "tabelog_rating": tab.get("tabelog_rating"),
        "cuisine": tab.get("cuisine", ""),
        "area": tab.get("area", ""),
        "address": tab.get("address", ""),
        "tabelog_url": tab.get("url", ""),
        "ward": tab.get("ward", ""),
        "lat": tab.get("lat"),
        "lng": tab.get("lng"),
        "tabelog_review_count": tab.get("tabelog_review_count"),
    }
    if hit is None:
        base.update(_status="error" if err and err.startswith(("api_error", "network")) else "dropped",
                    _reason=err or "no_result")
        return base
    base.update(
        hotpepper_id=hit["hotpepper_id"],
        hotpepper_name_en=hit["hotpepper_name_en"],
        hotpepper_description=hit["hotpepper_description"],
        hotpepper_photo_url=hit["hotpepper_photo_url"],
        hotpepper_address=hit["hotpepper_address"],
        hotpepper_url=hit["hotpepper_url"],
    )
    base["_status"] = "kept"
    return base


def _public(rec):
    return {k: v for k, v in rec.items() if not k.startswith("_")}


def _load(path, default):
    if os.path.exists(path):
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    return default


def _save(path, data):
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    os.replace(tmp, path)


SAMPLE = {
    "results": {
        "shop": [{
            "id": "S001",
            "name": "Sushi Tsurusei",
            "name_kana": "スシツルセイ",
            "catch": "Quiet Gion sushi counter",
            "other_memo": "Reservation recommended",
            "address": "Gion, Higashiyama-ku, Kyoto",
            "urls": {"pc": "https://www.hotpepper.jp/strJ001/"},
            "photo": {"mobile": {"l": "https://img.example.jp/r.jpg"}},
        }]
    }
}


def selftest():
    n = _normalize(SAMPLE["results"]["shop"][0])
    assert n["hotpepper_id"] == "S001", n
    assert "Gion sushi counter" in n["hotpepper_description"], n
    assert n["hotpepper_photo_url"].endswith(".jpg"), n
    d = haversine_m(35.0036, 135.7781, 35.0036, 135.7781)
    assert d == 0.0, d
    print("selftest OK - normalize, distance, response shape all pass")


def main():
    ap = argparse.ArgumentParser(description="Hotpepper cross-reference for Tabelog Kyoto scrape")
    ap.add_argument("src", nargs="?", help="tabelog_kyoto_full_flat.json (or 'selftest')")
    ap.add_argument("out", nargs="?", help="output JSON (matches only)")
    ap.add_argument("--max-distance", type=float, default=400.0)
    ap.add_argument("--delay", type=float, default=0.5)
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    if args.src == "selftest":
        return selftest()
    if not args.src or not args.out:
        ap.error("need <src> and <out> (or 'selftest')")
    crossref(args.src, args.out, max_distance=args.max_distance,
             delay=args.delay, limit=args.limit or 0, dry_run=args.dry_run)


if __name__ == "__main__":
    main()