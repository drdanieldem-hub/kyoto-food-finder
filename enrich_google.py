#!/usr/bin/env python3
"""
Enrich Kyoto restaurants with Google Places data
"""
import requests
import time
import json
import os
from dotenv import load_dotenv

load_dotenv()

GOOGLE_API_KEY = os.getenv('GOOGLE_PLACES_API_KEY')

def search_google_places(name, city="Kyoto"):
    """Search Google Places API for restaurant"""
    if not GOOGLE_API_KEY:
        return None
    
    url = "https://maps.googleapis.com/maps/api/place/textsearch/json"
    params = {
        'query': f"{name} {city} Japan",
        'key': GOOGLE_API_KEY
    }
    
    try:
        response = requests.get(url, params=params, timeout=10)
        data = response.json()
        
        if data['status'] == 'OK' and data['results']:
            place = data['results'][0]
            place_id = place.get('place_id')
            
            # Get place details
            details_url = "https://maps.googleapis.com/maps/api/place/details/json"
            details_params = {
                'place_id': place_id,
                'fields': 'name,rating,user_ratings_total,formatted_address,geometry,place_id,opening_hours,price_level,photos',
                'key': GOOGLE_API_KEY
            }
            
            details_response = requests.get(details_url, params=details_params, timeout=10)
            details_data = details_response.json()
            
            if details_data['status'] == 'OK':
                result = details_data['result']
                
                # Get up to 5 photo URLs
                photo_urls = []
                if 'photos' in result:
                    for photo in result['photos'][:5]:
                        photo_ref = photo['photo_reference']
                        photo_url = f"https://maps.googleapis.com/maps/api/place/photo?maxwidth=800&photo_reference={photo_ref}&key={GOOGLE_API_KEY}"
                        photo_urls.append(photo_url)
                
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
    except Exception as e:
        print(f"  Google error: {e}")
    
    return None

def main():
    print("Loading Kyoto restaurants...")
    
    with open('kyoto_raw.json', 'r', encoding='utf-8') as f:
        restaurants = json.load(f)
    
    print(f"Found {len(restaurants)} restaurants to enrich\n")
    
    enriched = []
    not_found = []
    
    for i, restaurant in enumerate(restaurants, 1):
        print(f"[{i}/{len(restaurants)}] {restaurant['name']}")
        
        google_data = search_google_places(restaurant['name'])
        
        if not google_data:
            print("  ❌ Not found")
            not_found.append(restaurant)
            time.sleep(0.5)
            continue
        
        # Filter by Google rating
        if google_data['google_rating'] and google_data['google_rating'] >= 4.2:
            combined = {**restaurant, **google_data}
            enriched.append(combined)
            print(f"  ✅ Google {google_data['google_rating']} ⭐")
        else:
            print(f"  ❌ Google {google_data.get('google_rating', 'N/A')} ⭐")
            not_found.append(restaurant)
        
        time.sleep(0.5)
        
        # Save progress every 100 restaurants
        if i % 100 == 0:
            with open('kyoto_progress.json', 'w', encoding='utf-8') as f:
                json.dump({'enriched': enriched, 'not_found': not_found, 'last_index': i}, f, ensure_ascii=False, indent=2)
            print(f"\n💾 Progress saved: {len(enriched)} enriched so far\n")
    
    print(f"\n\n=== FINAL RESULTS ===")
    print(f"Total scraped (Tabelog 3.5+): {len(restaurants)}")
    print(f"Passed filters (Tabelog 3.5+ AND Google 4.2+): {len(enriched)}")
    print(f"Failed: {len(not_found)}")
    
    # Save final results
    with open('kyoto_final.json', 'w', encoding='utf-8') as f:
        json.dump(enriched, f, ensure_ascii=False, indent=2)
    
    with open('kyoto_notfound.json', 'w', encoding='utf-8') as f:
        json.dump(not_found, f, ensure_ascii=False, indent=2)
    
    print(f"\n✅ Saved {len(enriched)} Kyoto restaurants to kyoto_final.json")

if __name__ == '__main__':
    main()
