#!/usr/bin/env python3
"""
Kyoto Food Finder — Map Generator
=================================

Kyoto-adapted build.py. Reads final_restaurants_merged.json (produced by
scraper/to_map_format.py) and writes a self-contained index.html with an
interactive Leaflet map, clustering, popups, and filters.

What's Kyoto-specific vs. Tokyo
-------------------------------
* Map default center is Kyoto Station (35.0116, 135.7681) at zoom 12.
* Stats line says "Tabelog 3.4+" instead of "Tabelog 3.4+ ∩ Google 4.2+"
  because we don't enforce a Google review floor (Hotpepper is optional).
* Top-picks threshold is **Tabelog rating only**, no combined Google score
  (no Google rating field).
* "Open now" filter is gated on whether hours data is present; if hours
  are absent (the default for Tabelog-only), the filter is disabled and
  a small note explains why.
* Hotpepper description / photo URLs are rendered in the popup when
  present.
* Color palette is unchanged (green/blue/purple Tabelog rating buckets).
"""
from __future__ import annotations

import json
import os
import sys

# ── Cuisine mapping (Japanese → English categories) ──────────────────────
# Kyoto additions:
#   "Kaiseki": the headline category — Kyoto's signature cuisine
#   "Shojin": Buddhist vegetarian cuisine, also uniquely Kyoto
#   "Tofu": ryōri (e.g. Sagano-yu) — distinctly Kansai
#
# Important: Tabelog's `cuisine` field never tags "懐石"/"京料理" explicitly.
# Tokyo-area restaurants get "和食" or "日本料理"; we treat high-rated
# "日本料理" (>= 4.0) as Kaiseki by default since that's effectively what
# Kyoto's top Japanese restaurants ARE. Lower-rated 日本料理 stays in
# the broad "Japanese" bucket. The '_kaiseki' helper uses rating context.
CATEGORY_KEYWORDS = {
    "Kaiseki":  ["懐石", "会席", "kaiseki", "Kaiseki", "京料理", "京懐石"],
    "Shojin":   ["精進", "shojin", "Shojin", "精進料理"],
    "Tofu":     ["豆腐", "湯葉", "Yuba", "yuba"],
    "Sushi":    ["寿司", "すし", "スシ", "Sushi"],
    "Ramen":    ["ラーメン", "らーめん", "つけ麺", "Ramen"],
    "Tempura":  ["天ぷら", "てんぷら", "Tempura"],
    "Yakitori": ["焼き鳥", "やきとり", "Yakitori", "鳥料理"],
    "Yakiniku": ["焼肉", "やきにく", "Yakiniku", "ホルモン"],
    "Tonkatsu": ["とんかつ", "トンカツ", "Tonkatsu", "カツ"],
    "Unagi":    ["うなぎ", "ウナギ", "Unagi", "鰻"],
    "Japanese": ["日本料理", "和食", "Japanese"],
    "Soba":     ["そば", "ソバ", "Soba", "蕎麦"],
    "Udon":     ["うどん", "ウドン", "Udon"],
    "Curry":    ["カレー", "Curry", "カリー"],
    "Bakery":   ["パン", "ベーカリー", "Bakery", "たい焼き"],
    "Desserts": ["ケーキ", "和菓子", "スイーツ", "Dessert", "パティスリー"],
    "Pizza":    ["ピザ", "Pizza", "Pizzeria", "ピッツェリア", "Trattoria", "Italian"],
}
ALL_CATEGORIES = list(CATEGORY_KEYWORDS.keys())
KAISEKI_RATING_MIN = 4.0  # "日本料理" ≥ 4.0 = kaiseki (Kyoto convention)


def classify(cuisine_text: str, tabelog_rating: float | None = None) -> list[str]:
    cats: list[str] = []
    for cat, keywords in CATEGORY_KEYWORDS.items():
        for kw in keywords:
            if kw in cuisine_text:
                cats.append(cat)
                break
    # Promote high-rated "日本料理" / "和食" to Kaiseki — Tabelog doesn't tag
    # kaiseki explicitly in the Kyoto area; these are signature fine-dining
    # spots by definition.
    if (tabelog_rating or 0) >= KAISEKI_RATING_MIN:
        if "日本料理" in cuisine_text or "和食" in cuisine_text:
            if "Kaiseki" not in cats:
                cats.append("Kaiseki")
    if not cats:
        cats = ["Other"]
    return cats


# ── GeoJSON projection ───────────────────────────────────────────────────
def build_geojson(restaurants: list[dict]) -> dict:
    """Project the dataset into Leaflet-friendly GeoJSON. Restaurants missing
    lat/lng are silently dropped — they're useless on a map."""
    features: list[dict] = []
    skipped = 0
    for r in restaurants:
        lat = r.get("lat")
        lng = r.get("lng")
        if lat is None or lng is None:
            skipped += 1
            continue
        name_en = (r.get("google_name") or "").strip() or r["name"]
        name_jp = r["name"]
        # Prefer Hotpepper address if available (English-friendly), else Tabelog
        addr = (r.get("google_address") or "").strip() or r.get("address", "")
        cuisine = r.get("cuisine", "")
        cats = classify(cuisine, r.get("tabelog_rating"))
        feat = {
            "type": "Feature",
            "geometry": {"type": "Point", "coordinates": [lng, lat]},
            "properties": {
                "name":              name_en,
                "name_jp":           name_jp,
                "tabelog_rating":    r.get("tabelog_rating", 0),
                "google_rating":     r.get("google_rating", 0),
                "google_reviews":    r.get("google_user_ratings_total", 0),
                "cuisine":           cuisine,
                "area":              r.get("area", ""),
                "address":           addr,
                "categories":        cats,
                "place_id":          r.get("google_place_id", ""),
                "lat":               lat,
                "lng":               lng,
                # Hotpepper extras
                "hotpepper_description": r.get("hotpepper_description", ""),
                "hotpepper_photo_url":   r.get("hotpepper_photo_url", ""),
                "hotpepper_url":         r.get("hotpepper_url", ""),
                "tabelog_review_count":  r.get("tabelog_review_count", 0),
                # Hours (empty by default; google_hours enhancement may add)
                "regular_opening_hours": r.get("regular_opening_hours") or [],
                "current_open_now":      r.get("current_open_now"),
                "hours_source":          r.get("hours_source", ""),
            },
        }
        features.append(feat)
    if skipped:
        print(f"  Dropped {skipped} restaurants without coords")
    return {"type": "FeatureCollection", "features": features}


def category_counts(restaurants: list[dict]) -> dict[str, int]:
    counts = {cat: 0 for cat in ALL_CATEGORIES}
    counts["Other"] = 0
    for r in restaurants:
        cats = classify(r.get("cuisine", ""), r.get("tabelog_rating"))
        for c in cats:
            counts[c] = counts.get(c, 0) + 1
    return counts


# ── Top-picks scoring (Tabelog-only, no Google) ──────────────────────────
def top_picks_threshold(features: list[dict]) -> float:
    """Top 15% by Tabelog rating alone (no Google to combine with)."""
    scores = [f["properties"]["tabelog_rating"] for f in features if f["properties"].get("tabelog_rating")]
    scores.sort(reverse=True)
    if not scores:
        return 0.0
    return scores[max(0, int(len(scores) * 0.15) - 1)]


def main():
    base = os.path.dirname(os.path.abspath(__file__))
    data_path = os.path.join(base, "final_restaurants_merged.json")
    if not os.path.exists(data_path):
        sys.exit(f"Missing {data_path}. Run scraper/to_map_format.py first.")
    out_path = os.path.join(base, "index.html")

    with open(data_path, encoding="utf-8") as f:
        restaurants = json.load(f)

    total = len(restaurants)
    print(f"Loaded {total} restaurants")

    geojson = build_geojson(restaurants)
    counts = category_counts(restaurants)
    threshold = top_picks_threshold(geojson["features"])
    has_hours = any(f["properties"].get("regular_opening_hours") for f in geojson["features"])

    print("\nCategory counts:")
    for cat in ALL_CATEGORIES + ["Other"]:
        print(f"  {cat}: {counts.get(cat, 0)}")
    print(f"\nHours data: {'present' if has_hours else 'absent (Open Now filter disabled)'}")

    geojson_str = json.dumps(geojson, ensure_ascii=False, separators=(",", ":"))
    counts_str  = json.dumps(counts,   ensure_ascii=False)
    cats_str    = json.dumps(ALL_CATEGORIES, ensure_ascii=False)

    html = build_html(
        geojson_str=geojson_str,
        counts_str=counts_str,
        cats_str=cats_str,
        total=len(geojson["features"]),  # after coord drop
        raw_total=total,
        top_threshold=threshold,
        has_hours=has_hours,
    )

    with open(out_path, "w", encoding="utf-8") as f:
        f.write(html)

    print(f"\nWrote {out_path}")
    print(f"Total features in GeoJSON: {len(geojson['features'])}")


# ── HTML generation ──────────────────────────────────────────────────────
def build_html(*, geojson_str, counts_str, cats_str, total, raw_total, top_threshold, has_hours):
    # Notes the JS reads for UI affordances
    hours_blocked = "false" if has_hours else "true"
    stats_label = (f"{raw_total} Restaurants &bull; Tabelog 3.4+"
                   if raw_total == total else
                   f"{raw_total} Restaurants &bull; {total} shown on map &bull; Tabelog 3.4+")
    return (
        "<!DOCTYPE html>\n"
        "<html lang=\"en\">\n"
        "<head>\n"
        "<meta charset=\"UTF-8\">\n"
        "<meta name=\"viewport\" content=\"width=device-width, initial-scale=1.0\">\n"
        "<title>🏯 Kyoto Food Finder</title>\n"
        "<link rel=\"manifest\" href=\"manifest.json\">\n"
        "<meta name=\"theme-color\" content=\"#be185d\">\n"
        "<link rel=\"apple-touch-icon\" href=\"icon-192.png\">\n"
        "<!-- Leaflet CSS -->\n"
        "<link rel=\"stylesheet\" href=\"https://unpkg.com/leaflet@1.9.4/dist/leaflet.css\">\n"
        "<!-- MarkerCluster CSS -->\n"
        "<link rel=\"stylesheet\" href=\"https://unpkg.com/leaflet.markercluster@1.5.3/dist/MarkerCluster.css\">\n"
        "<link rel=\"stylesheet\" href=\"https://unpkg.com/leaflet.markercluster@1.5.3/dist/MarkerCluster.Default.css\">\n"
        "<style>\n"
        "* { box-sizing: border-box; margin: 0; padding: 0; }\n"
        "html, body { height: 100%; font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif; }\n"
        "body { display: flex; flex-direction: column; background: #f8fafc; color: #1e293b; }\n"
        "body.dark { background: #0f172a; color: #e2e8f0; }\n"
        "#header { background: #be185d; color: #fff; padding: 10px 16px; display: flex; align-items: center; gap: 12px; flex-shrink: 0; box-shadow: 0 2px 8px rgba(0,0,0,.2); z-index: 1000; position: relative; }\n"
        "body.dark #header { background: #831843; }\n"
        "#header h1 { font-size: 1.2rem; font-weight: 700; flex: 1; white-space: nowrap; }\n"
        "#stats-line { font-size: 0.78rem; opacity: .9; white-space: nowrap; }\n"
        "#dark-toggle { background: rgba(255,255,255,.2); border: none; color: #fff; border-radius: 8px; padding: 6px 12px; cursor: pointer; font-size: 0.85rem; white-space: nowrap; }\n"
        "#dark-toggle:hover { background: rgba(255,255,255,.35); }\n"
        "#main { display: flex; flex: 1; overflow: hidden; }\n"
        "#sidebar { width: 280px; background: #fff; border-right: 1px solid #e2e8f0; overflow-y: auto; flex-shrink: 0; transition: transform .25s; z-index: 500; }\n"
        "body.dark #sidebar { background: #1e293b; border-color: #334155; }\n"
        "#map { flex: 1; }\n"
        "#sidebar-inner { padding: 14px; }\n"
        ".filter-section { margin-bottom: 14px; }\n"
        ".filter-section h3 { font-size: 0.75rem; text-transform: uppercase; letter-spacing: .08em; color: #64748b; margin-bottom: 6px; }\n"
        "body.dark .filter-section h3 { color: #94a3b8; }\n"
        "select, input[type=text] { width: 100%; padding: 7px 10px; border: 1px solid #cbd5e1; border-radius: 8px; font-size: 0.85rem; background: #f8fafc; color: #1e293b; }\n"
        "body.dark select, body.dark input[type=text] { background: #0f172a; border-color: #475569; color: #e2e8f0; }\n"
        ".checkbox-list { display: flex; flex-direction: column; gap: 5px; max-height: 260px; overflow-y: auto; }\n"
        ".checkbox-list label { display: flex; align-items: center; gap: 7px; font-size: 0.84rem; cursor: pointer; }\n"
        ".checkbox-list input[type=checkbox] { accent-color: #be185d; width: 15px; height: 15px; }\n"
        ".cat-count { color: #94a3b8; font-size: 0.75rem; margin-left: auto; }\n"
        "#top-picks-label { display: flex; align-items: center; gap: 7px; font-size: 0.88rem; cursor: pointer; }\n"
        "#top-picks-label input { accent-color: #be185d; width: 15px; height: 15px; }\n"
        "#open-now-label { display: flex; align-items: center; gap: 7px; font-size: 0.88rem; cursor: pointer; }\n"
        "#open-now-label input { accent-color: #be185d; width: 15px; height: 15px; }\n"
        "#open-now-label.disabled { opacity: .4; cursor: not-allowed; }\n"
        "#open-now-label.disabled input { cursor: not-allowed; }\n"
        ".japan-time { font-size: 0.74rem; color: #64748b; margin-top: 4px; padding-left: 22px; font-variant-numeric: tabular-nums; }\n"
        "body.dark .japan-time { color: #94a3b8; }\n"
        ".japan-time.live { color: #be185d; font-weight: 600; }\n"
        "body.dark .japan-time.live { color: #f472b6; }\n"
        "button.reset-btn { width: 100%; padding: 8px; border: 1px solid #be185d; background: transparent; color: #be185d; border-radius: 8px; cursor: pointer; font-size: 0.85rem; margin-top: 8px; }\n"
        "button.reset-btn:hover { background: #be185d; color: #fff; }\n"
        "body.dark button.reset-btn { border-color: #f472b6; color: #f472b6; }\n"
        "body.dark button.reset-btn:hover { background: #f472b6; color: #0f172a; }\n"
        "#sidebar-toggle { display: none; position: fixed; bottom: 70px; left: 12px; z-index: 2000; background: #be185d; color: #fff; border: none; border-radius: 50%; width: 44px; height: 44px; font-size: 1.2rem; cursor: pointer; box-shadow: 0 2px 8px rgba(0,0,0,.3); }\n"
        "body.dark #sidebar-toggle { background: #831843; }\n"
        "#gps-btn { position: fixed; bottom: 16px; left: 12px; z-index: 2000; background: #3b82f6; color: #fff; border: none; border-radius: 50%; width: 44px; height: 44px; font-size: 1.1rem; cursor: pointer; box-shadow: 0 2px 8px rgba(0,0,0,.3); }\n"
        "#gps-btn.active { background: #ef4444; }\n"
        "#legend { position: fixed; bottom: 16px; right: 12px; z-index: 2000; background: #fff; border-radius: 10px; padding: 10px 14px; box-shadow: 0 2px 8px rgba(0,0,0,.15); font-size: 0.78rem; }\n"
        "body.dark #legend { background: #1e293b; color: #e2e8f0; }\n"
        ".legend-item { display: flex; align-items: center; gap: 6px; margin-bottom: 4px; }\n"
        ".legend-dot { width: 12px; height: 12px; border-radius: 50%; display: inline-block; }\n"
        ".popup-title { font-size: 1rem; font-weight: 700; margin-bottom: 2px; }\n"
        ".popup-name-jp { font-size: 0.8rem; color: #64748b; margin-bottom: 8px; }\n"
        ".popup-ratings { display: flex; gap: 8px; margin-bottom: 8px; flex-wrap: wrap; }\n"
        ".rating-chip { display: inline-flex; align-items: center; gap: 4px; padding: 4px 10px; border-radius: 20px; font-size: 0.82rem; font-weight: 600; text-decoration: none; }\n"
        ".rating-chip.tabelog { background: #fef3c7; color: #92400e; }\n"
        ".rating-chip.hotpepper { background: #fce7f3; color: #831843; }\n"
        ".rating-chip:hover { opacity: .85; }\n"
        ".popup-meta { font-size: 0.82rem; line-height: 1.7; }\n"
        ".popup-meta span { display: block; }\n"
        ".popup-status-row { margin-bottom: 8px; }\n"
        ".status-badge { display: inline-flex; align-items: center; gap: 4px; padding: 5px 12px; border-radius: 14px; font-size: 0.85rem; font-weight: 700; box-shadow: 0 1px 3px rgba(0,0,0,.08); }\n"
        ".status-badge.open { background: #10b981; color: #fff; }\n"
        ".status-badge.closed { background: #6b7280; color: #fff; }\n"
        ".status-badge.unknown { background: #f59e0b; color: #fff; }\n"
        ".popup-desc { margin-top: 6px; font-size: 0.84rem; color: #475569; line-height: 1.45; }\n"
        "body.dark .popup-desc { color: #cbd5e1; }\n"
        "@media (max-width: 767px) {\n"
        "  #sidebar { position: fixed; top: 0; left: 0; height: 100%; transform: translateX(-100%); box-shadow: 2px 0 12px rgba(0,0,0,.2); }\n"
        "  #sidebar.open { transform: translateX(0); }\n"
        "  #sidebar-toggle { display: flex; align-items: center; justify-content: center; }\n"
        "  #header h1 { font-size: 1rem; }\n"
        "  #stats-line { display: none; }\n"
        "}\n"
        "</style>\n"
        "</head>\n"
        "<body>\n"
        "<div id=\"header\">\n"
        "  <h1>🏯 Kyoto Food Finder</h1>\n"
        f"  <span id=\"stats-line\">{stats_label}</span>\n"
        "  <button id=\"dark-toggle\">🌙 Dark</button>\n"
        "</div>\n"
        "<div id=\"main\">\n"
        "  <div id=\"sidebar\">\n"
        "    <div id=\"sidebar-inner\">\n"
        "      <div class=\"filter-section\">\n"
        "        <h3>Tabelog Rating</h3>\n"
        "        <select id=\"tabelog-min\">\n"
        "          <option value=\"3.0\">3.0+</option>\n"
        "          <option value=\"3.4\" selected>3.4+</option>\n"
        "          <option value=\"3.7\">3.7+</option>\n"
        "          <option value=\"4.0\">4.0+</option>\n"
        "        </select>\n"
        "      </div>\n"
        "      <div class=\"filter-section\">\n"
        "        <h3>Min Reviews (Tabelog)</h3>\n"
        "        <input id=\"review-min\" type=\"number\" min=\"0\" step=\"1\" value=\"0\" />\n"
        "      </div>\n"
        "      <div class=\"filter-section\">\n"
        "        <h3>Cuisine</h3>\n"
        "        <div id=\"cuisine-checks\" class=\"checkbox-list\"></div>\n"
        "      </div>\n"
        "      <div class=\"filter-section\">\n"
        "        <label id=\"top-picks-label\"><input id=\"top-picks\" type=\"checkbox\" /> Top picks only (top 15%)</label>\n"
        "      </div>\n"
        "      <div class=\"filter-section\">\n"
        "        <label id=\"open-now-label\""
        + (" disabled" if not has_hours else "")
        + "><input id=\"open-now\" type=\"checkbox\""
        + (" disabled" if not has_hours else "")
        + " /> Open now (Japan)</label>\n"
        + ("        <div class=\"japan-time live\" id=\"open-now-note\">Hours not yet loaded — set HOTPEPPER_API_KEY and run the cross-ref to enable.</div>\n" if not has_hours else
        "        <div class=\"japan-time\" id=\"japan-time\"></div>\n")
        +
        "      </div>\n"
        "      <div class=\"filter-section\">\n"
        "        <h3>Search (name / area)</h3>\n"
        "        <input id=\"search\" type=\"text\" placeholder=\"e.g. Gion, Kaiseki, Ramen\" />\n"
        "      </div>\n"
        "      <button class=\"reset-btn\" id=\"reset-filters\">Reset Filters</button>\n"
        "    </div>\n"
        "  </div>\n"
        "  <div id=\"map\"></div>\n"
        "</div>\n"
        "<button id=\"sidebar-toggle\" title=\"Toggle filters\">⚙</button>\n"
        "<button id=\"gps-btn\" title=\"Toggle GPS\">📍</button>\n"
        "<div id=\"legend\">\n"
        "  <div style=\"font-weight:600;margin-bottom:5px\">Tabelog</div>\n"
        "  <div class=\"legend-item\"><span class=\"legend-dot\" style=\"background:#10b981\"></span> 4.0+</div>\n"
        "  <div class=\"legend-item\"><span class=\"legend-dot\" style=\"background:#3b82f6\"></span> 3.7–3.99</div>\n"
        "  <div class=\"legend-item\"><span class=\"legend-dot\" style=\"background:#8b5cf6\"></span> &lt;3.7</div>\n"
        "</div>\n"
        "<!-- Leaflet JS -->\n"
        "<script src=\"https://unpkg.com/leaflet@1.9.4/dist/leaflet.js\"></script>\n"
        "<script src=\"https://unpkg.com/leaflet.markercluster@1.5.3/dist/leaflet.markercluster.js\"></script>\n"
        "<script>\n"
        "(function() {\n"
        "'use strict';\n"
        "\n"
        f"var GEOJSON = {geojson_str};\n"
        f"var COUNTS  = {counts_str};\n"
        f"var CATS    = {cats_str};\n"
        f"var TOTAL   = {total};\n"
        f"var TOP_THRESHOLD = {top_threshold};\n"
        f"var HAS_HOURS = {str(has_hours).lower()};\n"
        "\n"
        "var darkMode = localStorage.getItem('kyotoDarkMode') === 'true';\n"
        "function applyDark() {\n"
        "  document.body.classList.toggle('dark', darkMode);\n"
        "  document.getElementById('dark-toggle').textContent = darkMode ? '☀ Light' : '🌙 Dark';\n"
        "  if (window.lightLayer && window.darkLayer && window.map) {\n"
        "    if (darkMode) {\n"
        "      if (map.hasLayer(lightLayer)) { map.removeLayer(lightLayer); map.addLayer(darkLayer); }\n"
        "    } else {\n"
        "      if (map.hasLayer(darkLayer)) { map.removeLayer(darkLayer); map.addLayer(lightLayer); }\n"
        "    }\n"
        "  }\n"
        "}\n"
        "applyDark();\n"
        "document.getElementById('dark-toggle').addEventListener('click', function() {\n"
        "  darkMode = !darkMode;\n"
        "  localStorage.setItem('kyotoDarkMode', String(darkMode));\n"
        "  applyDark();\n"
        "});\n"
        "\n"
        "// ── Map init (Kyoto Station default) ─────────────────────────────────\n"
        "var map = L.map('map').setView([35.0116, 135.7681], 13);\n"
        "var lightLayer = L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', {\n"
        "  attribution: '&copy; <a href=\"https://www.openstreetmap.org/copyright\">OpenStreetMap</a> contributors',\n"
        "  maxZoom: 19\n"
        "});\n"
        "var darkLayer = L.tileLayer('https://{s}.basemaps.cartocdn.com/dark_all/{z}/{x}/{y}{r}.png', {\n"
        "  attribution: '&copy; <a href=\"https://www.openstreetmap.org/copyright\">OSM</a> &copy; <a href=\"https://carto.com/\">CARTO</a>',\n"
        "  maxZoom: 19\n"
        "});\n"
        "window.lightLayer = lightLayer;\n"
        "window.darkLayer  = darkLayer;\n"
        "window.map = map;\n"
        "(darkMode ? darkLayer : lightLayer).addTo(map);\n"
        "\n"
        "var container = document.getElementById('cuisine-checks');\n"
        "CATS.forEach(function(cat) {\n"
        "  var lbl = document.createElement('label');\n"
        "  var cb  = document.createElement('input');\n"
        "  cb.type = 'checkbox';\n"
        "  cb.value = cat;\n"
        "  cb.dataset.cat = cat;\n"
        "  cb.className = 'cat-cb';\n"
        "  cb.addEventListener('change', applyFilters);\n"
        "  var cnt = document.createElement('span');\n"
        "  cnt.className = 'cat-count';\n"
        "  cnt.textContent = '(' + (COUNTS[cat] || 0) + ')';\n"
        "  lbl.appendChild(cb);\n"
        "  lbl.appendChild(document.createTextNode(' ' + cat));\n"
        "  lbl.appendChild(cnt);\n"
        "  container.appendChild(lbl);\n"
        "});\n"
        "\n"
        "var clusterGroup = L.markerClusterGroup({\n"
        "  maxClusterRadius: 50,\n"
        "  spiderfyOnMaxZoom: true,\n"
        "  showCoverageOnHover: false,\n"
        "  zoomToBoundsOnClick: true\n"
        "});\n"
        "map.addLayer(clusterGroup);\n"
        "\n"
        "function haversine(lat1, lng1, lat2, lng2) {\n"
        "  var R = 6371;\n"
        "  var dLat = (lat2 - lat1) * Math.PI / 180;\n"
        "  var dLng = (lng2 - lng1) * Math.PI / 180;\n"
        "  var a = Math.sin(dLat/2)*Math.sin(dLat/2) +\n"
        "          Math.cos(lat1*Math.PI/180)*Math.cos(lat2*Math.PI/180)*\n"
        "          Math.sin(dLng/2)*Math.sin(dLng/2);\n"
        "  return R * 2 * Math.atan2(Math.sqrt(a), Math.sqrt(1-a));\n"
        "}\n"
        "function walkTime(km) { return ''; }  // disabled — no GPS user-toggle UX\n"
        "function markerColor(tabelog) {\n"
        "  if (tabelog >= 4.0) return '#10b981';\n"
        "  if (tabelog >= 3.7) return '#3b82f6';\n"
        "  return '#8b5cf6';\n"
        "}\n"
        "function escHtml(s) { return String(s).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/\"/g,'&quot;'); }\n"
        "function slotLabel(slots) { return slots.map(function(s){ return s.open + '–' + (s.close || '24h'); }).join(', '); }\n"
        "\n"
        "// Asia/Tokyo wall-clock helpers (also valid for Kyoto)\n"
        "function getTokyoMinutesNow() {\n"
        "  var parts = new Intl.DateTimeFormat('en-US', {\n"
        "    timeZone: 'Asia/Tokyo', hour12: false,\n"
        "    hour: '2-digit', minute: '2-digit', weekday: 'short'\n"
        "  }).formatToParts(new Date());\n"
        "  var h = 0, m = 0, weekday = 0;\n"
        "  for (var i = 0; i < parts.length; i++) {\n"
        "    if (parts[i].type === 'hour') h = parseInt(parts[i].value, 10) % 24;\n"
        "    if (parts[i].type === 'minute') m = parseInt(parts[i].value, 10);\n"
        "    if (parts[i].type === 'weekday') {\n"
        "      weekday = ['Sun','Mon','Tue','Wed','Thu','Fri','Sat'].indexOf(parts[i].value);\n"
        "    }\n"
        "  }\n"
        "  return { mins: h * 60 + m, dayIdx: weekday };\n"
        "}\n"
        "function isOpenAt(p) {\n"
        "  if (!HAS_HOURS) return null;\n"
        "  var days = p.regular_opening_hours;\n"
        "  if (!days || days.length !== 7) return null;\n"
        "  var t = getTokyoMinutesNow();\n"
        "  var day = days[t.dayIdx];\n"
        "  if (!day || day.closed) return false;\n"
        "  for (var i = 0; i < day.slots.length; i++) {\n"
        "    var s = day.slots[i];\n"
        "    var oh = parseInt(s.open.split(':')[0]);\n"
        "    var om = parseInt(s.open.split(':')[1]);\n"
        "    var openMin = oh * 60 + om;\n"
        "    var closeMin;\n"
        "    if (!s.close) { closeMin = 24 * 60; }\n"
        "    else {\n"
        "      var ch = parseInt(s.close.split(':')[0]);\n"
        "      var cm = parseInt(s.close.split(':')[1]);\n"
        "      closeMin = ch * 60 + cm;\n"
        "      if (closeMin <= openMin) closeMin = 24 * 60;\n"
        "    }\n"
        "    if (t.mins >= openMin && t.mins < closeMin) return true;\n"
        "  }\n"
        "  return false;\n"
        "}\n"
        "\n"
        "function popupHtml(p) {\n"
        "  var nameJp = p.name_jp && p.name_jp !== p.name ? '<div class=\"popup-name-jp\">' + escHtml(p.name_jp) + '</div>' : '';\n"
        "  var rating = '<span class=\"rating-chip tabelog\">★ ' + (p.tabelog_rating || 0).toFixed(2);\n"
        "  if (p.tabelog_review_count) rating += ' · ' + p.tabelog_review_count + ' reviews';\n"
        "  rating += '</span>';\n"
        "  var hpLink = p.hotpepper_url ? '<a class=\"rating-chip hotpepper\" href=\"' + escHtml(p.hotpepper_url) + '\" target=\"_blank\" rel=\"noopener\">Hotpepper</a>' : '';\n"
        "  var tabLink = p.place_id ? '' : '';  // no Google place link\n"
        "  var addrLine = p.address ? '<span>📍 ' + escHtml(p.address) + '</span>' : '';\n"
        "  var areaLine = p.area ? '<span>🏘 ' + escHtml(p.area) + (p.cuisine ? ' · ' + escHtml(p.cuisine) : '') + '</span>' : '';\n"
        "  var catsLine = p.categories && p.categories.length ? '<span>🍽 ' + p.categories.map(escHtml).join(', ') + '</span>' : '';\n"
        "  var photo = p.hotpepper_photo_url ? '<img src=\"' + escHtml(p.hotpepper_photo_url) + '\" style=\"width:100%;border-radius:8px;margin-bottom:6px\" loading=\"lazy\" />' : '';\n"
        "  var desc = p.hotpepper_description ? '<div class=\"popup-desc\">' + escHtml(p.hotpepper_description) + '</div>' : '';\n"
        "  var statusRow = '';\n"
        "  if (HAS_HOURS) {\n"
        "    var open = isOpenAt(p);\n"
        "    if (open === true) statusRow = '<div class=\"popup-status-row\"><span class=\"status-badge open\">● Open now</span></div>';\n"
        "    else if (open === false) statusRow = '<div class=\"popup-status-row\"><span class=\"status-badge closed\">● Closed now</span></div>';\n"
        "    else statusRow = '<div class=\"popup-status-row\"><span class=\"status-badge unknown\">Hours unknown</span></div>';\n"
        "  }\n"
        "  return '<div class=\"popup-title\">' + escHtml(p.name) + '</div>' + nameJp + statusRow +\n"
        "    '<div class=\"popup-ratings\">' + rating + hpLink + '</div>' +\n"
        "    photo + desc +\n"
        "    '<div class=\"popup-meta\">' + addrLine + areaLine + catsLine + '</div>';\n"
        "}\n"
        "\n"
        "function makeMarker(feature, latlng) {\n"
        "  var p = feature.properties;\n"
        "  var marker = L.circleMarker(latlng, {\n"
        "    radius: 6, fillColor: markerColor(p.tabelog_rating || 0),\n"
        "    color: '#fff', weight: 1.5, fillOpacity: 0.92\n"
        "  });\n"
        "  marker.bindPopup(popupHtml(p));\n"
        "  marker.options.feature = feature;\n"
        "  return marker;\n"
        "}\n"
        "\n"
        "var allMarkers = [];\n"
        "GEOJSON.features.forEach(function(f) {\n"
        "  var m = makeMarker(f, L.latLng(f.properties.lat, f.properties.lng));\n"
        "  allMarkers.push(m);\n"
        "});\n"
        "\n"
        "function refreshMap() {\n"
        "  clusterGroup.clearLayers();\n"
        "  allMarkers.forEach(function(m) { clusterGroup.addLayer(m); });\n"
        "}\n"
        "refreshMap();\n"
        "\n"
        "function pass(p) {\n"
        "  if (p.tabelog_rating < parseFloat(document.getElementById('tabelog-min').value)) return false;\n"
        "  var minReviews = parseInt(document.getElementById('review-min').value || '0', 10);\n"
        "  if (minReviews > 0 && (p.tabelog_review_count || 0) < minReviews) return false;\n"
        "  var activeCuisines = Array.prototype.slice.call(document.querySelectorAll('.cat-cb:checked')).map(function(el){return el.value;});\n"
        "  if (activeCuisines.length) {\n"
        "    var hit = false;\n"
        "    for (var i = 0; i < activeCuisines.length; i++) {\n"
        "      if (p.categories.indexOf(activeCuisines[i]) !== -1) { hit = true; break; }\n"
        "    }\n"
        "    if (!hit) return false;\n"
        "  }\n"
        "  if (document.getElementById('top-picks').checked && p.tabelog_rating < TOP_THRESHOLD) return false;\n"
        "  if (HAS_HOURS && document.getElementById('open-now').checked && isOpenAt(p) !== true) return false;\n"
        "  var q = document.getElementById('search').value.trim().toLowerCase();\n"
        "  if (q) {\n"
        "    var blob = ((p.name || '') + ' ' + (p.name_jp || '') + ' ' + (p.area || '') + ' ' + (p.cuisine || '') + ' ' + (p.categories || []).join(' ')).toLowerCase();\n"
        "    if (blob.indexOf(q) === -1) return false;\n"
        "  }\n"
        "  return true;\n"
        "}\n"
        "\n"
        "function applyFilters() {\n"
        "  var visible = 0;\n"
        "  clusterGroup.clearLayers();\n"
        "  allMarkers.forEach(function(m) {\n"
        "    if (pass(m.options.feature.properties)) {\n"
        "      clusterGroup.addLayer(m);\n"
        "      visible++;\n"
        "    }\n"
        "  });\n"
        "  document.getElementById('stats-line').textContent =\n"
        "    visible + ' / ' + TOTAL + ' shown · Tabelog 3.4+';\n"
        "}\n"
        "\n"
        "['change', 'input'].forEach(function(evt) {\n"
        "  ['tabelog-min', 'review-min', 'top-picks', 'open-now', 'search'].forEach(function(id) {\n"
        "    document.getElementById(id).addEventListener(evt, applyFilters);\n"
        "  });\n"
        "});\n"
        "document.querySelectorAll('.cat-cb').forEach(function(cb) {\n"
        "  cb.addEventListener('change', applyFilters);\n"
        "});\n"
        "document.getElementById('reset-filters').addEventListener('click', function() {\n"
        "  document.getElementById('tabelog-min').value = '3.4';\n"
        "  document.getElementById('review-min').value = '0';\n"
        "  document.querySelectorAll('.cat-cb').forEach(function(cb) { cb.checked = false; });\n"
        "  document.getElementById('top-picks').checked = false;\n"
        "  document.getElementById('open-now').checked = false;\n"
        "  document.getElementById('search').value = '';\n"
        "  applyFilters();\n"
        "});\n"
        "\n"
        "// ── Sidebar toggle (mobile) ─────────────────────────────────────────\n"
        "var sidebar = document.getElementById('sidebar');\n"
        "function isMobile() { return window.innerWidth < 768; }\n"
        "if (isMobile()) sidebar.classList.remove('open');\n"
        "document.getElementById('sidebar-toggle').addEventListener('click', function() {\n"
        "  sidebar.classList.toggle('open');\n"
        "});\n"
        "document.getElementById('map').addEventListener('click', function() {\n"
        "  if (isMobile()) sidebar.classList.remove('open');\n"
        "});\n"
        "\n"
        "// ── Japan time display ─────────────────────────────────────────────\n"
        "function updateJapanTime() {\n"
        "  var el = document.getElementById('japan-time');\n"
        "  if (!el) return;\n"
        "  var s = new Intl.DateTimeFormat('en-US', {\n"
        "    timeZone: 'Asia/Tokyo', hour12: false,\n"
        "    hour: '2-digit', minute: '2-digit', second: '2-digit',\n"
        "    weekday: 'short', day: 'numeric', month: 'short'\n"
        "  }).format(new Date());\n"
        "  el.textContent = '🕒 Japan: ' + s;\n"
        "  el.classList.add('live');\n"
        "}\n"
        "if (HAS_HOURS) { updateJapanTime(); setInterval(updateJapanTime, 30000); }\n"
        "\n"
        "// ── GPS (best-effort) ─────────────────────────────────────────────\n"
        "var gpsBtn = document.getElementById('gps-btn');\n"
        "var gpsWatchId = null;\n"
        "var userMarker = null;\n"
        "var firstFix = true;\n"
        "function startGps() {\n"
        "  if (gpsWatchId !== null) return;\n"
        "  if (!navigator.geolocation) { if (gpsBtn) gpsBtn.classList.remove('active'); return; }\n"
        "  if (gpsBtn) gpsBtn.classList.add('active');\n"
        "  firstFix = true;\n"
        "  gpsWatchId = navigator.geolocation.watchPosition(function(pos) {\n"
        "    var uLat = pos.coords.latitude, uLng = pos.coords.longitude;\n"
        "    if (userMarker) { map.removeLayer(userMarker); }\n"
        "    userMarker = L.circleMarker([uLat, uLng], { radius: 9, fillColor: '#ef4444', color: '#fff', weight: 2, fillOpacity: 1 }).addTo(map);\n"
        "    if (firstFix) { map.setView([uLat, uLng], 14); firstFix = false; }\n"
        "  }, function() {}, { enableHighAccuracy: true, maximumAge: 30000, timeout: 27000 });\n"
        "}\n"
        "function stopGps() {\n"
        "  if (gpsWatchId !== null) { navigator.geolocation.clearWatch(gpsWatchId); gpsWatchId = null; }\n"
        "  if (userMarker) { map.removeLayer(userMarker); userMarker = null; }\n"
        "  if (gpsBtn) gpsBtn.classList.remove('active');\n"
        "}\n"
        "if (gpsBtn) {\n"
        "  gpsBtn.addEventListener('click', function() {\n"
        "    if (gpsWatchId === null) startGps(); else stopGps();\n"
        "  });\n"
        "}\n"
        "\n"
        "// Auto-fit to visible bounds\n"
        "if (allMarkers.length) {\n"
        "  var bounds = L.latLngBounds(allMarkers.map(function(m){ return m.getLatLng(); }));\n"
        "  if (bounds.isValid()) map.fitBounds(bounds.pad(0.1));\n"
        "}\n"
        "\n"
        "})();\n"
        "</script>\n"
        "</body>\n"
        "</html>\n"
    )


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "selftest":
        # Lightweight offline test
        sample = [{"name":"鮨 鶴清", "tabelog_rating":3.85, "cuisine":"寿司",
                   "area":"祇園", "address":"...", "lat":35.0036, "lng":135.7781,
                   "url":"x", "ward":"Higashiyama"}]
        cats = classify("寿司", 4.5)
        assert "Sushi" in cats, cats
        # High-rated 日本料理 → Kaiseki promotion
        cats2 = classify("日本料理", 4.5)
        assert "Kaiseki" in cats2 and "Japanese" in cats2, cats2
        cats3 = classify("日本料理", 3.6)
        assert "Kaiseki" not in cats3 and "Japanese" in cats3, cats3
        gj = build_geojson(sample)
        assert gj["features"][0]["properties"]["tabelog_rating"] == 3.85, gj
        thresh = top_picks_threshold(gj["features"])
        assert thresh == 3.85, thresh
        print("selftest OK - classify, kaiseki promotion, build_geojson, top_picks_threshold all pass")
    else:
        main()
