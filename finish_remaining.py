#!/usr/bin/env python3
"""Quick finish - remaining restaurants"""
import requests, time, json, os
from dotenv import load_dotenv
load_dotenv()

GOOGLE_API_KEY = os.getenv('GOOGLE_PLACES_API_KEY')

def search_google(name):
    try:
        url = "https://maps.googleapis.com/maps/api/place/textsearch/json"
        r = requests.get(url, params={'query': f"{name} Kyoto Japan", 'key': GOOGLE_API_KEY}, timeout=10)
        data = r.json()
        if data['status'] == 'OK' and data['results']:
            place_id = data['results'][0]['place_id']
            details = requests.get("https://maps.googleapis.com/maps/api/place/details/json",
                params={'place_id': place_id, 'fields': 'name,rating,user_ratings_total,formatted_address,geometry,place_id,opening_hours,price_level,photos', 'key': GOOGLE_API_KEY}, timeout=10).json()
            if details['status'] == 'OK':
                result = details['result']
                photo_urls = []
                if 'photos' in result:
                    for photo in result['photos'][:5]:
                        photo_urls.append(f"https://maps.googleapis.com/maps/api/place/photo?maxwidth=800&photo_reference={photo['photo_reference']}&key={GOOGLE_API_KEY}")
                return {
                    'google_name': result.get('name'),
                    'google_rating': result.get('rating'),
                    'google_user_ratings_total': result.get('user_ratings_total'),
                    'google_address': result.get('formatted_address'),
                    'google_place_id': result.get('place_id'),
                    'lat': result['geometry']['location']['lat'],
                    'lng': result['geometry']['location']['lng'],
                    'price_level': result.get('price_level'),
                    'opening_hours': result.get('opening_hours', {}).get('weekday_text', []),
                    'open_now': result.get('opening_hours', {}).get('open_now'),
                    'photo_urls': photo_urls
                }
    except: pass
    return None

with open('kyoto_progress.json', 'r') as f:
    progress = json.load(f)

enriched, not_found = progress['enriched'], progress['not_found']

with open('kyoto_raw.json', 'r') as f:
    all_rest = json.load(f)

remaining = all_rest[1127:]
print(f"Processing {len(remaining)} restaurants...")

for i, r in enumerate(remaining, 1128):
    print(f"[{i}/1200] {r['name']}", end=' ')
    g = search_google(r['name'])
    if g and g['google_rating'] and g['google_rating'] >= 4.2:
        enriched.append({**r, **g})
        print(f"✅ {g['google_rating']}")
    else:
        not_found.append(r)
        print("❌")
    time.sleep(0.3)

print(f"\n✅ DONE! Total: {len(enriched)} restaurants")

with open('kyoto_final.json', 'w') as f:
    json.dump(enriched, f, ensure_ascii=False, indent=2)
print(f"Saved to kyoto_final.json")
