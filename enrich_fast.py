#!/usr/bin/env python3
"""
Fast cuisine enrichment script for Kyoto restaurants.
Uses Google Places API text search - faster than detailed lookups.
"""
import json
import os
import time
from datetime import datetime

# Load API key
with open('.env') as f:
    for line in f:
        if line.startswith('GOOGLE_PLACES'):
            API_KEY = line.split('=')[1].strip()
            break

import requests

# Load restaurants needing enrichment
with open('kyoto_geojson.json') as f:
    data = json.load(f)

# Find restaurants that only have 'Japanese' category
needs_enrichment = []
for i, feat in enumerate(data['features']):
    cats = feat['properties'].get('categories', [])
    if cats == ['Japanese'] or not cats:
        needs_enrichment.append({
            'index': i,
            'place_id': feat['properties'].get('place_id'),
            'name': feat['properties'].get('name'),
            'address': feat['properties'].get('address', '')
        })

print(f"Total needing enrichment: {len(needs_enrichment)}")

# Load progress if exists
progress_file = 'enrichment_progress.json'
processed = set()
if os.path.exists(progress_file):
    with open(progress_file) as f:
        progress = json.load(f)
        processed = set(progress.get('processed', []))
        print(f"Resuming - already processed: {len(processed)}")

# Filter to process
to_process = [r for r in needs_enrichment if r['place_id'] not in processed]
print(f"Remaining to process: {len(to_process)}")

# Cuisine keywords to search for
CUISINE_KEYWORDS = {
    'Sushi': ['sushi', '寿司'],
    'Ramen': ['ramen', 'ラーメン'],
    'Udon': ['udon', '饂饨'],
    'Soba': ['soba', '蕎麦'],
    'Tempura': ['tempura', '天ぷら'],
    'Unagi': ['unagi', 'うなぎ', '鳗鱼'],
    'Yakitori': ['yakitori', '焼き鳥'],
    'Yakiniku': ['yakiniku', '焼肉'],
    'Tonkatsu': ['tonkatsu', '豚かつ'],
    'Kaiseki': ['kaiseki', '懐石'],
    'Curry': ['curry', 'カレー'],
    'Nabe': ['nabe', '鍋'],
    'Izakaya': ['izakaya', '居酒屋'],
    'Cafe': ['cafe', '咖啡', 'coffee'],
    'Tea House': ['tea house', '茶屋', '茶房'],
    'Bakery': ['bakery', 'パン', '面包'],
    'Sweets': ['sweets', '甘味', ' sweets'],
    'Italian': ['italian', 'イタリアン'],
    'French': ['french', 'フレンチ'],
    'Chinese': ['chinese', '中華'],
    'Pizza': ['pizza', 'ピザ'],
    'Steak': ['steak', 'ステーキ'],
}

def search_cuisine(place_id, name, address):
    """Use text search to find cuisine type."""
    try:
        # Search by name + "Kyoto" + cuisine keywords
        search_query = f"{name} Kyoto"
        
        url = "https://maps.googleapis.com/maps/api/place/textsearch/json"
        params = {
            'query': search_query,
            'key': API_KEY,
            'language': 'en'
        }
        
        resp = requests.get(url, params=params, timeout=10)
        results = resp.json().get('results', [])
        
        if not results:
            return None
            
        # Get the place types
        place_types = results[0].get('types', [])
        
        # Map Google types to our categories
        type_mapping = {
            'cafe': 'Cafe',
            'coffee_shop': 'Cafe',
            'bakery': 'Bakery',
            'restaurant': None,  # Too generic
            'food': None,
            'meal_takeaway': None,
            'meal_delivery': None,
        }
        
        found_cuisines = set()
        for ptype in place_types:
            if ptype in type_mapping and type_mapping[ptype]:
                found_cuisines.add(type_mapping[ptype])
        
        # Also search for specific cuisines in name
        name_lower = name.lower()
        for cuisine, keywords in CUISINE_KEYWORDS.items():
            for kw in keywords:
                if kw.lower() in name_lower:
                    found_cuisines.add(cuisine)
        
        return list(found_cuisines) if found_cuisines else None
        
    except Exception as e:
        print(f"  Error: {e}")
        return None

# Process in batches
BATCH_SIZE = 25
batch_num = 0

for i in range(0, len(to_process), BATCH_SIZE):
    batch = to_process[i:i+BATCH_SIZE]
    batch_num += 1
    
    print(f"\n--- Batch {batch_num} ({i+1}-{min(i+BATCH_SIZE, len(to_process))}) ---")
    
    for restaurant in batch:
        place_id = restaurant['place_id']
        name = restaurant['name']
        
        if place_id in processed:
            continue
            
        # Search for cuisine
        cuisines = search_cuisine(place_id, name, restaurant.get('address', ''))
        
        if cuisines and cuisines != ['Japanese']:
            # Update the restaurant's categories
            idx = restaurant['index']
            old_cats = data['features'][idx]['properties'].get('categories', [])
            data['features'][idx]['properties']['categories'] = cuisines
            print(f"  ✓ {name}: {old_cats} → {cuisines}")
        else:
            print(f"  - {name}: No specific cuisine found")
        
        processed.add(place_id)
        
        # Save progress
        with open(progress_file, 'w') as f:
            json.dump({'processed': list(processed), 'timestamp': datetime.now().isoformat()}, f)
        
        # Rate limiting
        time.sleep(0.1)
    
    # Save intermediate results
    with open('kyoto_geojson.json', 'w') as f:
        json.dump(data, f)
    
    print(f"Saved progress - {len(processed)}/{len(needs_enrichment)}")

print(f"\n=== DONE ===")
print(f"Processed: {len(processed)} restaurants")

# Final summary
from collections import Counter
cat_counts = Counter()
for feat in data['features']:
    cats = feat['properties'].get('categories', [])
    for c in cats:
        cat_counts[c] += 1

print("\nFinal category counts:")
for cat, count in cat_counts.most_common():
    print(f"  {cat}: {count}")
