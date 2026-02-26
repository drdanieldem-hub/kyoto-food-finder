#!/usr/bin/env python3
"""
Scrape Kyoto restaurants from Tabelog (3.5+) and cross-reference with Google (4.2+)
"""
import requests
from bs4 import BeautifulSoup
import time
import json
import os
from dotenv import load_dotenv

load_dotenv()

GOOGLE_API_KEY = os.getenv('GOOGLE_PLACES_API_KEY')

def scrape_tabelog_kyoto(page_num, min_rating=3.5):
    """Scrape a single page of Kyoto Tabelog results"""
    # Kyoto URL - sorted by rating
    url = f"https://tabelog.com/kyoto/rstLst/{page_num}/?SrtT=rt"
    
    headers = {
        'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36'
    }
    
    try:
        response = requests.get(url, headers=headers, timeout=30)
        if response.status_code != 200:
            return None, False
        
        soup = BeautifulSoup(response.content, 'html.parser')
        
        # Find restaurant listings
        listings = soup.find_all('div', class_='list-rst')
        
        if not listings:
            return None, False
        
        restaurants = []
        should_continue = True
        
        for listing in listings:
            try:
                # Extract rating
                rating_elem = listing.find('span', class_='c-rating__val')
                if not rating_elem:
                    continue
                
                rating = float(rating_elem.text.strip())
                
                # Check if we should continue (ratings are descending)
                if rating < min_rating:
                    should_continue = False
                    break
                
                # Extract name
                name_elem = listing.find('a', class_='list-rst__rst-name-target')
                if not name_elem:
                    continue
                
                name = name_elem.text.strip()
                
                # Extract area
                area_elem = listing.find('div', class_='list-rst__area')
                area = area_elem.text.strip() if area_elem else 'Unknown'
                
                # Extract cuisine
                cuisine_elem = listing.find('div', class_='list-rst__genre')
                cuisine = cuisine_elem.text.strip() if cuisine_elem else 'Japanese'
                
                restaurants.append({
                    'name': name,
                    'tabelog_rating': rating,
                    'area': area,
                    'cuisine': cuisine
                })
                
                print(f"  Found: {name} ({rating})")
                
            except Exception as e:
                print(f"  Error parsing listing: {e}")
                continue
        
        return restaurants, should_continue
        
    except Exception as e:
        print(f"Error fetching page {page_num}: {e}")
        return None, False

def search_google_places(name, city="Kyoto"):
    """Search Google Places API for restaurant in Kyoto"""
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
        print(f"  Google Places error: {e}")
    
    return None

def main():
    print("=== KYOTO FOOD FINDER ===")
    print("Scraping Tabelog for Kyoto restaurants (3.5+ rating)...\n")
    
    all_restaurants = []
    page = 1
    
    while True:
        print(f"=== Page {page} ===")
        restaurants, should_continue = scrape_tabelog_kyoto(page, min_rating=3.5)
        
        if not restaurants:
            print("No more results or error, stopping.")
            break
        
        all_restaurants.extend(restaurants)
        
        if not should_continue:
            print(f"Reached restaurants below 3.5 rating, stopping.")
            break
        
        page += 1
        time.sleep(2)  # Be nice to Tabelog
        
        # Safety limit
        if page > 100:
            print("Reached page limit (100), stopping.")
            break
    
    print(f"\n\nFound {len(all_restaurants)} Kyoto restaurants (Tabelog 3.5+)")
    
    # Save raw results
    with open('kyoto_raw.json', 'w', encoding='utf-8') as f:
        json.dump(all_restaurants, f, ensure_ascii=False, indent=2)
    
    print("\nEnriching with Google Places data...")
    
    enriched = []
    not_found = []
    
    for i, restaurant in enumerate(all_restaurants, 1):
        print(f"\n[{i}/{len(all_restaurants)}] Processing: {restaurant['name']}")
        
        # Search Google Places
        google_data = search_google_places(restaurant['name'])
        
        if not google_data:
            print("  ❌ Not found on Google")
            not_found.append(restaurant)
            time.sleep(1)
            continue
        
        # Filter by Google rating
        if google_data['google_rating'] and google_data['google_rating'] >= 4.2:
            combined = {**restaurant, **google_data}
            enriched.append(combined)
            print(f"  ✅ Google {google_data['google_rating']} ⭐ - ADDED")
        else:
            print(f"  ❌ Google {google_data.get('google_rating', 'N/A')} ⭐ - Below 4.2")
            not_found.append(restaurant)
        
        time.sleep(1)  # Rate limiting
    
    print(f"\n\n=== RESULTS ===")
    print(f"Total scraped (Tabelog 3.5+): {len(all_restaurants)}")
    print(f"Passed filters (Tabelog 3.5+ AND Google 4.2+): {len(enriched)}")
    print(f"Failed: {len(not_found)}")
    
    # Save enriched results
    with open('kyoto_final.json', 'w', encoding='utf-8') as f:
        json.dump(enriched, f, ensure_ascii=False, indent=2)
    
    # Save not found
    with open('kyoto_notfound.json', 'w', encoding='utf-8') as f:
        json.dump(not_found, f, ensure_ascii=False, indent=2)
    
    print(f"\n✅ Saved {len(enriched)} Kyoto restaurants to kyoto_final.json")

if __name__ == '__main__':
    main()
