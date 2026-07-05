#!/usr/bin/env python3
"""
Tabelog scraper for Kyoto (11 wards, Tabelog rating >= 3.4).

Kyoto port of tokyo-food-finder/scraper/tabelog_scraper.py. Same two-stage
structure (list scrape → detail enrichment), same anti-bot guidance, same
checkpoint/resume mechanics. Only the ward list and base URL change.

Stages
------
  list     Stage 1 - walk each ward's rating-sorted list, collect every
           restaurant with rating >= MIN_RATING. Fast. No coordinates yet.
  details  Stage 2 - visit each restaurant page to pull lat/lng, full
           address and Tabelog review count from the page's JSON-LD.
  all      list, then details.

Both stages checkpoint to disk and resume, so an interrupted run continues
where it left off (important on flaky connections / anti-bot throttling).

Why this script exists
----------------------
Tabelog's ranked restaurant list is capped at 60 pages / 1,200 results per
query. A single Kyoto-wide list therefore only ever exposes the top ~1,200
restaurants. By segmenting the search by ward (11 queries), each stays
under the cap and the union covers far more of the 3.4+ long tail.

Anti-bot note
-------------
Tabelog blocks many datacenter IPs with HTTP 403 regardless of headers.
From a normal residential connection the default `requests` engine usually
works. If you still get 403s, install Playwright and pass `--engine playwright`
to drive a real headless browser.

Usage
-----
  python tabelog_kyoto_scraper.py selftest                          # offline
  python tabelog_kyoto_scraper.py all --delay 2.5                   # full run
  python tabelog_kyoto_scraper.py list --min-rating 3.5            # tune threshold
  python tabelog_kyoto_scraper.py details
  python tabelog_kyoto_scraper.py all --engine playwright --delay 3 # if blocked

  python tabelog_kyoto_scraper.py debug-html C26104                # save one ward
                                                                 # page for inspection

Outputs
-------
- tabelog_kyoto_list.json / _flat.json    - stage 1
- tabelog_kyoto_full.json / _flat.json    - stage 2 (with coordinates)

Then run hotpepper_crossref.py (optional, free API) and to_map_format.py to
produce final_restaurants_merged.json for build.py.
"""
from __future__ import annotations

import argparse
import json
import os
import random
import re
import sys
import time

try:
    import requests
except ImportError:  # pragma: no cover
    requests = None

try:
    from bs4 import BeautifulSoup
except ImportError:  # pragma: no cover
    BeautifulSoup = None


# --- Kyoto wards -> Tabelog municipality codes -------------------------------
# Same JIS scheme as Tokyo: codes C26xxx (Kyoto-fu = 26), one per ward.
# URL form: https://tabelog.com/kyoto/<CODE>/rstLst/1/?SrtT=rt
WARDS: list[tuple[str, str]] = [
    ("C26101", "Kamigyo"),
    ("C26102", "Nakagyo"),
    ("C26103", "Sakyo"),
    ("C26104", "Higashiyama"),
    ("C26105", "Shimogyo"),
    ("C26106", "Minami"),
    ("C26107", "Ukyo"),
    ("C26108", "Kita"),
    ("C26109", "Fushimi"),
    ("C26110", "Nishikyo"),
    ("C26111", "Yamashina"),
]

# Kyoto city center; useful as a default map view later.
DEFAULT_CENTER = (35.0116, 135.7681)
MAX_PAGES = 60       # Tabelog's hard cap; stop scanning if we hit it.
BASE = "https://tabelog.com"

HEADERS = {
    "User-Agent": ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                   "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0 Safari/537.36"),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
    "Accept-Language": "ja,en-US;q=0.9,en;q=0.8",
    "Referer": "https://tabelog.com/kyoto/",
    "Upgrade-Insecure-Requests": "1",
}


# --- Fetching ---------------------------------------------------------------
class Fetcher:
    """HTML fetcher with retry/backoff. Engine: 'requests' or 'playwright'."""

    def __init__(self, engine: str = "requests", delay: float = 2.0, retries: int = 4):
        self.engine = engine
        self.delay = delay
        self.retries = retries
        self._session = None
        self._pw = None  # (playwright, browser, context) tuple when used

    def _session_requests(self):
        if self._session is None:
            if requests is None:
                sys.exit("The 'requests' package is required. pip install -r requirements.txt")
            self._session = requests.Session()
            self._session.headers.update(HEADERS)
        return self._session

    def _ensure_playwright(self):
        if self._pw is None:
            try:
                from playwright.sync_api import sync_playwright
            except ImportError:
                sys.exit("Playwright not installed. pip install playwright && playwright install chromium")
            pw = sync_playwright().start()
            browser = pw.chromium.launch(headless=True)
            ctx = browser.new_context(
                user_agent=HEADERS["User-Agent"],
                locale="ja-JP,en-US",
                extra_http_headers={"Accept-Language": HEADERS["Accept-Language"]},
            )
            self._pw = (pw, browser, ctx)
        return self._pw

    def get(self, url: str) -> str:
        if self.engine == "requests":
            return self._get_requests(url)
        return self._get_playwright(url)

    def _get_requests(self, url: str) -> str:
        s = self._session_requests()
        for attempt in range(self.retries):
            try:
                r = s.get(url, timeout=30)
                if r.status_code == 200:
                    return r.text
                if r.status_code in (403, 429):
                    wait = 2 ** attempt
                    print(f"    HTTP {r.status_code}, retry in {wait}s (consider --engine playwright)",
                          file=sys.stderr)
                    time.sleep(wait)
                    continue
                # Other 4xx / 5xx - don't retry
                print(f"    HTTP {r.status_code} for {url}", file=sys.stderr)
                return ""
            except requests.RequestException as e:
                wait = 2 ** attempt
                print(f"    {type(e).__name__}, retry in {wait}s", file=sys.stderr)
                time.sleep(wait)
        return ""

    def _get_playwright(self, url: str) -> str:
        pw, browser, ctx = self._ensure_playwright()
        page = ctx.new_page()
        try:
            page.goto(url, timeout=30000, wait_until="domcontentloaded")
            return page.content()
        except Exception as e:
            print(f"    playwright error: {e}", file=sys.stderr)
            return ""
        finally:
            page.close()

    def close(self):
        if self._pw is not None:
            try:
                self._pw[1].close()
                self._pw[0].stop()
            except Exception:
                pass


# --- Parsers (identical to tokyo-food-finder; reused verbatim) ------------
def parse_list_page(html: str) -> list[dict]:
    """Parse one ward list page. Returns list of partial restaurants."""
    if BeautifulSoup is None:
        sys.exit("Install deps first: pip install -r requirements.txt")
    soup = BeautifulSoup(html, "html.parser")
    rows: list[dict] = []
    items = soup.select(".list-rst__wrap")
    for it in items:
        a = (it.select_one("a.list-rst__rst-name-target")
             or it.select_one("a.list-rst__rst-name")
             or it.select_one("a[href*='/rstLst/'][href*='A']")
             or it.select_one(".list-rst__rst-name-target")
             or it.select_one("h3 a"))
        if not a:
            continue
        href = a.get("href", "")
        if "/A" not in href:
            continue
        name_el = a
        url = href if href.startswith("http") else f"{BASE}{href}"
        rating_el = (it.select_one(".c-rating__val")
                     or it.select_one(".list-rst__rating-val")
                     or it.select_one(".c-rating-v3__val"))
        rating = _to_float(rating_el.get_text(strip=True)) if rating_el else None

        area = cuisine = ""
        ag = it.select_one(".list-rst__area-genre")
        if ag:
            text = ag.get_text(" ", strip=True)
            parts = [p.strip() for p in re.split(r"[/・]", text) if p.strip()]
            if parts:
                area = parts[0]
                cuisine = " / ".join(parts[1:]) if len(parts) > 1 else ""
        else:
            a_el = it.select_one(".list-rst__area")
            g_el = it.select_one(".list-rst__genre")
            area = a_el.get_text(strip=True) if a_el else ""
            cuisine = g_el.get_text(strip=True) if g_el else ""

        rows.append({
            "name": name_el.get_text(strip=True),
            "tabelog_rating": rating,
            "area": area,
            "cuisine": cuisine,
            "url": url.split("?")[0],
        })
    return rows


def has_next_page(html: str) -> bool:
    soup = BeautifulSoup(html, "html.parser")
    nxt = soup.select_one("a.c-pagination__target--next, a.c-pagination__arrow--next")
    if not nxt:
        return False
    cls = nxt.get("class", [])
    return "is-disabled" not in cls and "c-pagination__arrow--disable" not in " ".join(cls)


def parse_detail_page(html: str) -> dict:
    """Pull lat/lng, address, Tabelog review count from the JSON-LD on a
    restaurant detail page. Regex fallbacks for inline coords."""
    out: dict = {}
    for block in re.findall(r'<script[^>]+type="application/ld\+json"[^>]*>(.*?)</script>', html, re.S):
        try:
            data = json.loads(block.strip())
        except json.JSONDecodeError:
            continue
        for node in data if isinstance(data, list) else [data]:
            if not isinstance(node, dict):
                continue
            geo = node.get("geo") or {}
            if geo.get("latitude") and geo.get("longitude"):
                out["lat"] = _to_float(geo["latitude"])
                out["lng"] = _to_float(geo["longitude"])
            addr = node.get("address")
            if isinstance(addr, dict):
                out["address"] = " ".join(
                    str(addr.get(k, "")) for k in
                    ("addressRegion", "addressLocality", "streetAddress")
                ).strip()
            elif isinstance(addr, str):
                out["address"] = addr
            agg = node.get("aggregateRating") or {}
            if agg.get("reviewCount"):
                out["tabelog_review_count"] = _to_int(agg["reviewCount"])
            if agg.get("ratingValue") and "tabelog_rating" not in out:
                out["tabelog_rating"] = _to_float(agg["ratingValue"])

    if "lat" not in out:
        m = re.search(r'"latitude":\s*"?(-?\d+\.?\d*)"?', html)
        n = re.search(r'"longitude":\s*"?(-?\d+\.?\d*)"?', html)
        if m and n:
            out["lat"] = float(m.group(1))
            out["lng"] = float(n.group(1))
    return out


def _to_float(text):
    try:
        return float(re.sub(r"[^\d.]", "", str(text)))
    except (ValueError, TypeError):
        return None


def _to_int(text):
    try:
        return int(re.sub(r"[^\d]", "", str(text)))
    except (ValueError, TypeError):
        return None


# --- Stages ----------------------------------------------------------------
def stage_list(fetcher: Fetcher, min_rating: float, out_path: str):
    """Scrape every Kyoto ward's rating-sorted list down to min_rating."""
    state = _load_json(out_path, {"done_wards": [], "restaurants": {}})
    done = set(state["done_wards"])
    by_url: dict[str, dict] = state["restaurants"]

    for code, ward in WARDS:
        if code in done:
            print(f"[skip] {ward} ({code}) already done")
            continue
        print(f"[ward] {ward} ({code})")
        ward_count = 0
        for page in range(1, MAX_PAGES + 1):
            url = f"{BASE}/kyoto/{code}/rstLst/{page}/?SrtT=rt"
            html = fetcher.get(url)
            if not html:
                print(f"    page {page}: no html, stopping ward")
                break
            rows = parse_list_page(html)
            if not rows:
                print(f"    page {page}: no rows, stopping ward")
                break
            stop = False
            for r in rows:
                if r["tabelog_rating"] is None:
                    continue
                if r["tabelog_rating"] < min_rating:
                    stop = True  # rating-sorted → rest are lower
                    break
                r["ward"] = ward
                by_url[r["url"]] = r
                ward_count += 1
            print(f"    page {page}: +{len(rows)} rows (ward kept {ward_count}, total {len(by_url)})")
            if stop or not has_next_page(html):
                break
            time.sleep(fetcher.delay + random.uniform(0, fetcher.delay))
        state["done_wards"] = sorted(done | {code})
        done.add(code)
        state["restaurants"] = by_url
        _save_json(out_path, state)

    flat = list(by_url.values())
    print(f"\nStage 1 complete: {len(flat)} unique restaurants >= {min_rating}")
    _save_json(out_path.replace(".json", "_flat.json"), flat)
    return flat


def stage_details(fetcher: Fetcher, list_path: str, out_path: str):
    """Enrich each restaurant with coordinates/address from its detail page."""
    src = _load_json(list_path, {"restaurants": {}})
    restaurants = src.get("restaurants", src if isinstance(src, dict) else {})
    if isinstance(restaurants, list):
        restaurants = {r["url"]: r for r in restaurants}

    enriched = _load_json(out_path, {})
    urls = [u for u in restaurants if u not in enriched]
    print(f"Stage 2: {len(urls)} to enrich ({len(enriched)} already done)")

    for i, url in enumerate(urls, 1):
        html = fetcher.get(url)
        rec = dict(restaurants[url])
        if html:
            rec.update(parse_detail_page(html))
        enriched[url] = rec
        if i % 25 == 0 or i == len(urls):
            _save_json(out_path, enriched)
            geo = sum(1 for r in enriched.values() if r.get("lat"))
            print(f"    {i}/{len(urls)} done ({geo} with coords)")
        time.sleep(fetcher.delay + random.uniform(0, fetcher.delay))

    _save_json(out_path, enriched)
    flat = list(enriched.values())
    _save_json(out_path.replace(".json", "_flat.json"), flat)
    geo = sum(1 for r in flat if r.get("lat"))
    print(f"\nStage 2 complete: {len(flat)} restaurants, {geo} with coordinates")
    return flat


# --- IO helpers ------------------------------------------------------------
def _load_json(path, default):
    if os.path.exists(path):
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    return default


def _save_json(path, data):
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    os.replace(tmp, path)


# --- Self test (offline) ---------------------------------------------------
SAMPLE_LIST_HTML = """
<div class="list-rst__wrap">
  <a class="list-rst__rst-name-target" href="/kyoto/A2601/A260101/26000001/">鮨 鶴清</a>
  <span class="c-rating__val">3.85</span>
  <div class="list-rst__area-genre">祇園 / 寿司</div>
</div>
<div class="list-rst__wrap">
  <a class="list-rst__rst-name-target" href="https://tabelog.com/kyoto/A2605/A260501/26000002/">ら麺 太郎</a>
  <span class="c-rating__val">3.42</span>
  <div class="list-rst__area-genre">四条 / ラーメン</div>
</div>
"""

SAMPLE_DETAIL_HTML = """
<script type="application/ld+json">
{"@type":"Restaurant","name":"鮨 鶴清",
 "address":{"addressRegion":"京都府","addressLocality":"京都市東山区","streetAddress":"祇園1-2-3"},
 "geo":{"@type":"GeoCoordinates","latitude":35.0036,"longitude":135.7781},
 "aggregateRating":{"ratingValue":"3.85","reviewCount":"214"}}
</script>
"""


def selftest():
    if BeautifulSoup is None:
        sys.exit("Install deps first: pip install -r requirements.txt")
    rows = parse_list_page(SAMPLE_LIST_HTML)
    assert len(rows) == 2, rows
    assert rows[0]["name"] == "鮨 鶴清", rows[0]
    assert rows[0]["tabelog_rating"] == 3.85, rows[0]
    assert rows[0]["area"] == "祇園" and "寿司" in rows[0]["cuisine"], rows[0]
    assert "/kyoto/" in rows[1]["url"], rows[1]
    det = parse_detail_page(SAMPLE_DETAIL_HTML)
    assert det["lat"] == 35.0036 and det["lng"] == 135.7781, det
    assert det["tabelog_review_count"] == 214, det
    assert "祇園" in det["address"], det
    # Kyoto-specific assertions
    assert "京都" in det["address"], det
    print("selftest OK - list, detail, and Kyoto-specific assertions pass")


# --- CLI --------------------------------------------------------------------
def main():
    ap = argparse.ArgumentParser(description="Tabelog Kyoto scraper (rating >= 3.4)")
    ap.add_argument("command", choices=["list", "details", "all", "selftest", "debug-html"])
    ap.add_argument("ward_code", nargs="?", help="ward code for debug-html, e.g. C26104")
    ap.add_argument("--min-rating", type=float, default=3.4)
    ap.add_argument("--engine", choices=["requests", "playwright"], default="requests")
    ap.add_argument("--delay", type=float, default=2.0, help="base polite delay (seconds)")
    ap.add_argument("--list-out", default="tabelog_kyoto_list.json")
    ap.add_argument("--details-out", default="tabelog_kyoto_full.json")
    args = ap.parse_args()

    if args.command == "selftest":
        return selftest()

    fetcher = Fetcher(engine=args.engine, delay=args.delay)
    try:
        if args.command == "debug-html":
            code = args.ward_code or "C26104"
            html = fetcher.get(f"{BASE}/kyoto/{code}/rstLst/1/?SrtT=rt")
            if not html:
                sys.exit("Fetch failed (likely 403). Try --engine playwright.")
            with open("debug_page.html", "w", encoding="utf-8") as f:
                f.write(html)
            rows = parse_list_page(html)
            print(f"Saved debug_page.html ({len(html)} bytes). Parser found {len(rows)} rows.")
            for r in rows[:5]:
                print(" ", r)
            return
        if args.command in ("list", "all"):
            stage_list(fetcher, args.min_rating, args.list_out)
        if args.command in ("details", "all"):
            stage_details(fetcher, args.list_out, args.details_out)
    finally:
        fetcher.close()


if __name__ == "__main__":
    main()
