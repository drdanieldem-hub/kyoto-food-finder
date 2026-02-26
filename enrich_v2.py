#!/usr/bin/env python3
"""
Enhanced cuisine enrichment - search specifically for each cuisine type.
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

# Load restaurants
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
            'name': feat['properties'].get('name', ''),
            'address': feat['properties'].get('address', '')
        })

print(f"Total needing enrichment: {len(needs_enrichment)}")

# Load progress
progress_file = 'enrich_v2_progress.json'
processed = {}
if os.path.exists(progress_file):
    with open(progress_file) as f:
        processed = json.load(f)
        print(f"Resuming - already processed: {len(processed)}")

CUISINES = ['Sushi', 'Ramen', 'Udon', 'Soba', 'Tempura', 'Unagi', 'Yakitori', 
            'Yakiniku', 'Tonkatsu', 'Kaiseki', 'Curry', 'Nabe', 'Izakaya', 
            'Cafe', 'Tea House', 'Bakery', 'Sweets', 'Italian', 'French', 
            'Chinese', 'Pizza', 'Steak']

def find_cuisine_for_place(name, address):
    """Search for specific cuisine matches near the place."""
    # Clean name for search
    search_name = name.replace('(', ' ').replace(')', ' ').split(',')[0][:30]
    
    # Try searching for "cuisine + name" in Kyoto
    for cuisine in CUISINES:
        try:
            query = f"{cuisine} {search_name} Kyoto"
            url = "https://maps.googleapis.com/maps/api/place/textsearch/json"
            params = {'query': query, 'key': API_KEY, 'language': 'en'}
            
            resp = requests.get(url, params=params, timeout=8)
            results = resp.json().get('results', [])
            
            if results:
                # Check if result matches our place reasonably well
                result_name = results[0].get('name', '').lower()
                if search_name.lower()[:10] in result_name or result_name[:10] in search_name.lower():
                    return cuisine
                    
        except Exception as e:
            continue
        
        time.sleep(0.05)  # Rate limit
    
    return None

# Process
total = len(needs_enrichment)
start_idx = len(processed)

print(f"Starting from index {start_idx}/{total}")

for i in range(start_idx, min(start_idx + 100, total)):  # Process 100 at a time
    restaurant = needs_enrichment[i]
    place_id = restaurant['place_id']
    name = restaurant['name']
    
    if place_id in processed:
        continue
    
    cuisine = find_cuisine_for_place(name, restaurant.get('address', ''))
    
    if cuisine:
        idx = restaurant['index']
        old_cats = data['features'][idx]['properties'].get('categories', [])
        data['features'][idx]['properties']['categories'] = [cuisine]
        print(f"  ✓ {name}: {cuisine}")
    else:
        print(f"  - {name}: (keep Japanese)")
    
    processed[place_id] = cuisine
    time.sleep(0.05)
    
    # Save progress every 10
    if (i + 1) % 10 == 0:
        with open(progress_file, 'w') as f:
            json.dump(processed, f)
        with open('kyoto_geojson.json', 'w') as f:
            json.dump(data, f)
        print(f"Saved progress: {i+1}/{total}")

# Final save
with open(progress_file, 'w') as f:
    json.dump(processed, f)
with open('kyoto_geojson.json', 'w') as f:
    json.dump(data, f)

print(f"\n=== DONE ({i+1} processed) ===")

# Summary
from collections import Counter
cat_counts = Counter()
for feat in data['features']:
    cats = feat['properties'].get('categories', [])
    for c in cats:
        cat_counts[c] += 1

print('\nCategory counts:')
for cat, count in cat_counts.most_common(25):
    print(f"  {cat}: {count}")
