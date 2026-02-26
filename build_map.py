#!/usr/bin/env python3
"""
Build static HTML map with embedded restaurant data
"""
import json

# Load restaurant data
with open('kyoto_final.json', 'r', encoding='utf-8') as f:
    restaurants = json.load(f)

print(f"Loading {len(restaurants)} restaurants...")

# Cuisine mapping (Japanese → English categories)
cuisine_categories = {
    'Sushi': ['寿司', 'すし', 'スシ', 'Sushi'],
    'Ramen': ['ラーメン', 'らーめん', 'つけ麺', 'Ramen'],
    'Tempura': ['天ぷら', 'てんぷら', 'Tempura'],
    'Yakitori': ['焼き鳥', 'やきとり', 'Yakitori', '鳥料理'],
    'Yakiniku': ['焼肉', 'やきにく', 'Yakiniku', 'ホルモン'],
    'Tonkatsu': ['とんかつ', 'トンカツ', 'Tonkatsu', 'カツ'],
    'Unagi': ['うなぎ', 'ウナギ', 'Unagi', '鰻'],
    'Japanese': ['日本料理', '和食', 'Japanese', '懐石', '割烹'],
    'Soba': ['そば', 'ソバ', 'Soba', '蕎麦'],
    'Udon': ['うどん', 'ウドン', 'Udon'],
    'Curry': ['カレー', 'Curry', 'カリー'],
    'Bakery': ['パン', 'ブーランジェリー', 'Bakery', 'ベーカリー'],
    'Desserts': ['ケーキ', '和菓子', 'スイーツ', 'Dessert', 'パティスリー', 'たい焼き'],
    'Pizza': ['ピザ', 'Pizza', 'Pizzeria', 'ピッツェリア', 'Trattoria', 'Italian']
}

def categorize_cuisine(cuisine_text):
    """Categorize a restaurant's cuisine into filter categories"""
    if not cuisine_text:
        return []
    
    categories = []
    cuisine_lower = cuisine_text.lower()
    
    for category, keywords in cuisine_categories.items():
        for keyword in keywords:
            if keyword.lower() in cuisine_lower:
                categories.append(category)
                break
    
    return categories

# Create GeoJSON and categorize
features = []
category_counts = {}

for r in restaurants:
    if 'lat' in r and 'lng' in r:
        categories = categorize_cuisine(r.get('cuisine', ''))
        
        # Count categories
        for cat in categories:
            category_counts[cat] = category_counts.get(cat, 0) + 1
        
        feature = {
            "type": "Feature",
            "geometry": {
                "type": "Point",
                "coordinates": [r['lng'], r['lat']]
            },
            "properties": {
                "name": r.get('google_name', r['name']),  # Use English name from Google
                "tabelog_rating": r['tabelog_rating'],
                "google_rating": r['google_rating'],
                "google_reviews": r.get('google_user_ratings_total', 0),
                "cuisine": r.get('cuisine', ''),
                "area": r.get('area', ''),
                "address": r.get('google_address', ''),
                "categories": categories,
                "place_id": r.get('google_place_id', ''),
                "price_level": r.get('price_level'),
                "opening_hours": r.get('opening_hours', []),
                "open_now": r.get('open_now'),
                "photo_urls": r.get('photo_urls', [])
            }
        }
        features.append(feature)

geojson = {
    "type": "FeatureCollection",
    "features": features
}

print(f"Created GeoJSON with {len(features)} restaurants")
print(f"\nCategory counts:")
for cat, count in sorted(category_counts.items(), key=lambda x: -x[1]):
    print(f"  {cat}: {count}")

# Build HTML
html = f'''<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <meta name="theme-color" content="#667eea">
    <meta name="description" content="Discover top-rated restaurants in Kyoto with live GPS tracking, walking times, and filters.">
    <title>Kyoto Food Finder - Top-Rated Restaurants</title>
    
    <!-- PWA Manifest -->
    <link rel="manifest" href="manifest.json">
    
    <!-- Apple Touch Icons -->
    <link rel="apple-touch-icon" href="icon-192.png">
    <meta name="apple-mobile-web-app-capable" content="yes">
    <meta name="apple-mobile-web-app-status-bar-style" content="black-translucent">
    <meta name="apple-mobile-web-app-title" content="Kyoto Food">
    
    <link rel="stylesheet" href="https://unpkg.com/leaflet@1.9.4/dist/leaflet.css" />
    <style>
        * {{
            margin: 0;
            padding: 0;
            box-sizing: border-box;
        }}
        
        body {{
            font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
            overflow: hidden;
            transition: background-color 0.3s ease;
        }}
        
        /* Dark mode styles */
        body.dark-mode {{
            background-color: #1a1a1a;
        }}
        
        body.dark-mode .header {{
            background: linear-gradient(135deg, #1e293b 0%, #0f172a 100%);
        }}
        
        body.dark-mode .controls {{
            background: #1e293b;
            color: #e2e8f0;
        }}
        
        body.dark-mode .controls h3,
        body.dark-mode .filter label {{
            color: #e2e8f0;
        }}
        
        body.dark-mode .filter select {{
            background: #0f172a;
            color: #e2e8f0;
            border-color: #334155;
        }}
        
        body.dark-mode .cuisine-option label {{
            color: #cbd5e1;
        }}
        
        body.dark-mode .toggle-btn {{
            background: #1e293b;
            color: #e2e8f0;
        }}
        
        body.dark-mode .toggle-btn:hover {{
            background: #334155;
        }}
        
        body.dark-mode .gps-btn {{
            background: #475569;
            color: #e2e8f0;
        }}
        
        body.dark-mode .gps-btn:hover {{
            background: #64748b;
        }}
        
        body.dark-mode .gps-btn.active {{
            background: #10b981;
        }}
        
        body.dark-mode .leaflet-popup-content-wrapper {{
            background: #1e293b;
            color: #e2e8f0;
        }}
        
        body.dark-mode .popup-name {{
            color: #e2e8f0;
        }}
        
        body.dark-mode .popup-rating span {{
            background: #334155;
            color: #cbd5e1;
        }}
        
        body.dark-mode .popup-info {{
            color: #94a3b8;
        }}
        
        #map {{
            position: absolute;
            top: 60px;
            left: 0;
            right: 0;
            bottom: 0;
        }}
        
        .header {{
            position: absolute;
            top: 0;
            left: 0;
            right: 0;
            height: 60px;
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            color: white;
            display: flex;
            align-items: center;
            justify-content: space-between;
            padding: 0 20px;
            box-shadow: 0 2px 10px rgba(0,0,0,0.2);
            z-index: 1000;
        }}
        
        .header h1 {{
            font-size: 20px;
            font-weight: 600;
        }}
        
        .stats {{
            font-size: 14px;
            opacity: 0.9;
        }}
        
        .theme-toggle {{
            background: rgba(255,255,255,0.2);
            border: none;
            border-radius: 50%;
            width: 40px;
            height: 40px;
            display: flex;
            align-items: center;
            justify-content: center;
            cursor: pointer;
            font-size: 20px;
            transition: background 0.3s ease;
            margin-left: 10px;
        }}
        
        .theme-toggle:hover {{
            background: rgba(255,255,255,0.3);
        }}
        
        .controls {{
            position: absolute;
            top: 70px;
            right: 10px;
            background: white;
            border-radius: 10px;
            box-shadow: 0 2px 10px rgba(0,0,0,0.2);
            z-index: 1000;
            max-width: 250px;
            transition: all 0.3s ease;
        }}
        
        .controls.collapsed {{
            padding: 0;
            max-height: 0;
            overflow: hidden;
        }}
        
        .controls.expanded {{
            padding: 15px;
            max-height: calc(100vh - 80px);
            overflow-y: auto;
        }}
        
        .toggle-btn {{
            position: absolute;
            top: 70px;
            right: 10px;
            background: white;
            border: none;
            border-radius: 10px;
            width: 50px;
            height: 50px;
            display: flex;
            align-items: center;
            justify-content: center;
            box-shadow: 0 2px 10px rgba(0,0,0,0.2);
            cursor: pointer;
            z-index: 1001;
            font-size: 24px;
        }}
        
        .toggle-btn:hover {{
            background: #f3f4f6;
        }}
        
        .controls.expanded ~ .toggle-btn {{
            display: none;
        }}
        
        .controls h3 {{
            font-size: 14px;
            margin-bottom: 10px;
            color: #333;
        }}
        
        .filter {{
            margin-bottom: 12px;
        }}
        
        .filter label {{
            display: block;
            font-size: 12px;
            color: #666;
            margin-bottom: 5px;
        }}
        
        .filter select {{
            width: 100%;
            padding: 8px;
            border: 1px solid #ddd;
            border-radius: 5px;
            font-size: 14px;
        }}
        
        .cuisine-filter {{
            margin-top: 15px;
            padding-top: 15px;
            border-top: 1px solid #eee;
        }}
        
        .cuisine-options {{
            display: grid;
            grid-template-columns: 1fr;
            gap: 8px;
            margin-top: 10px;
        }}
        
        .cuisine-option {{
            display: flex;
            align-items: center;
            gap: 8px;
            font-size: 13px;
        }}
        
        .cuisine-option input[type="checkbox"] {{
            cursor: pointer;
        }}
        
        .cuisine-option label {{
            cursor: pointer;
            margin: 0;
            flex: 1;
        }}
        
        .cuisine-count {{
            color: #999;
            font-size: 11px;
        }}
        
        .gps-btn {{
            width: 100%;
            padding: 10px;
            background: #667eea;
            color: white;
            border: none;
            border-radius: 5px;
            font-size: 14px;
            cursor: pointer;
            margin-top: 10px;
        }}
        
        .gps-btn:hover {{
            background: #5568d3;
        }}
        
        .gps-btn.active {{
            background: #22c55e;
        }}
        
        .leaflet-popup-content {{
            margin: 15px;
            min-width: 200px;
        }}
        
        .popup-name {{
            font-size: 16px;
            font-weight: 600;
            margin-bottom: 8px;
            color: #333;
        }}
        
        .popup-rating {{
            display: flex;
            gap: 10px;
            margin-bottom: 8px;
            font-size: 13px;
        }}
        
        .popup-rating span {{
            background: #f3f4f6;
            padding: 4px 8px;
            border-radius: 4px;
        }}
        
        .popup-info {{
            font-size: 12px;
            color: #666;
            margin-bottom: 4px;
        }}
        
        .popup-distance {{
            font-size: 14px;
            color: #667eea;
            font-weight: 600;
            margin-top: 8px;
        }}
        
        /* Photo carousel */
        .photo-carousel {{
            position: relative;
            width: 100%;
            height: 150px;
            margin-bottom: 10px;
            border-radius: 8px;
            overflow: hidden;
        }}
        
        .photo-carousel img {{
            width: 100%;
            height: 150px;
            object-fit: cover;
            display: none;
        }}
        
        .photo-carousel img.active {{
            display: block;
        }}
        
        .carousel-btn {{
            position: absolute;
            top: 50%;
            transform: translateY(-50%);
            background: rgba(0,0,0,0.5);
            color: white;
            border: none;
            border-radius: 50%;
            width: 30px;
            height: 30px;
            cursor: pointer;
            font-size: 16px;
            display: flex;
            align-items: center;
            justify-content: center;
            z-index: 10;
        }}
        
        .carousel-btn:hover {{
            background: rgba(0,0,0,0.7);
        }}
        
        .carousel-btn.prev {{
            left: 5px;
        }}
        
        .carousel-btn.next {{
            right: 5px;
        }}
        
        .photo-counter {{
            position: absolute;
            bottom: 5px;
            right: 8px;
            background: rgba(0,0,0,0.6);
            color: white;
            padding: 2px 8px;
            border-radius: 12px;
            font-size: 11px;
            font-weight: 600;
        }}
    </style>
</head>
<body>
    <div class="header">
        <h1>⛩️ Kyoto Food Finder</h1>
        <div style="display: flex; align-items: center; gap: 10px;">
            <div class="stats">{len(features)} Restaurants • Tabelog 3.5+ & Google 4.2+</div>
            <button class="theme-toggle" id="theme-toggle" onclick="toggleTheme()" title="Toggle dark mode">
                <span id="theme-icon">🌙</span>
            </button>
        </div>
    </div>
    
    <button class="toggle-btn" id="toggle-btn" onclick="toggleControls()">
        🎛️
    </button>
    
    <div class="controls expanded" id="controls">
        <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 15px;">
            <h3 style="margin: 0;">Filters</h3>
            <button onclick="toggleControls()" style="background: #f3f4f6; border: none; font-size: 24px; cursor: pointer; padding: 8px; color: #333; border-radius: 5px; width: 40px; height: 40px; display: flex; align-items: center; justify-content: center;">✕</button>
        </div>
        
        <div class="filter">
            <label>Google Rating</label>
            <select id="rating-filter">
                <option value="4.2">4.2+ Stars ({len(features)})</option>
                <option value="4.5">4.5+ Stars</option>
                <option value="4.7">4.7+ Stars</option>
                <option value="4.9">4.9+ Stars</option>
            </select>
        </div>
        
        <div class="filter" style="padding: 10px 0; border-bottom: 1px solid #eee; margin-bottom: 15px;">
            <label style="display: flex; align-items: center; gap: 8px; cursor: pointer;">
                <input type="checkbox" id="open-now-filter" style="cursor: pointer;">
                <span style="font-weight: 600;">🕒 Open Now Only</span>
            </label>
        </div>
        
        <button id="gps-btn" class="gps-btn">📍 Enable GPS Tracking</button>
        <button id="install-btn" class="gps-btn" style="background: #10b981; display: none;">📲 Install App</button>
    </div>
    
    <div id="map"></div>
    
    <script src="https://unpkg.com/leaflet@1.9.4/dist/leaflet.js"></script>
    <script>
        // Embedded restaurant data
        const restaurants = {json.dumps(geojson, ensure_ascii=False)};
        
        // Initialize map (centered on Kyoto)
        const map = L.map('map').setView([35.0116, 135.7681], 12);
        
        // Tile layers
        const lightTiles = L.tileLayer('https://{{s}}.tile.openstreetmap.org/{{z}}/{{x}}/{{y}}.png', {{
            attribution: '© OpenStreetMap contributors',
            maxZoom: 19
        }});
        
        const darkTiles = L.tileLayer('https://cartodb-basemaps-{{s}}.global.ssl.fastly.net/dark_all/{{z}}/{{x}}/{{y}}.png', {{
            attribution: '© OpenStreetMap contributors, © CARTO',
            subdomains: 'abcd',
            maxZoom: 19
        }});
        
        const darkLabels = null;
        
        // Start with light tiles
        let currentTiles = lightTiles;
        currentTiles.addTo(map);
        
        let userMarker = null;
        let userLocation = null;
        let gpsActive = false;
        let markers = [];
        
        // Calculate distance between two points
        function getDistance(lat1, lon1, lat2, lon2) {{
            const R = 6371; // Earth radius in km
            const dLat = (lat2 - lat1) * Math.PI / 180;
            const dLon = (lon2 - lon1) * Math.PI / 180;
            const a = Math.sin(dLat/2) * Math.sin(dLat/2) +
                     Math.cos(lat1 * Math.PI / 180) * Math.cos(lat2 * Math.PI / 180) *
                     Math.sin(dLon/2) * Math.sin(dLon/2);
            const c = 2 * Math.atan2(Math.sqrt(a), Math.sqrt(1-a));
            return R * c;
        }}
        
        // Calculate walking time from distance
        function getWalkingTime(distanceKm) {{
            const walkingSpeed = 5; // km/h (average walking speed)
            const timeHours = distanceKm / walkingSpeed;
            const timeMinutes = Math.round(timeHours * 60);
            
            if (timeMinutes < 1) {{
                return 'less than 1 min';
            }} else if (timeMinutes < 60) {{
                return `${{timeMinutes}} min walk`;
            }} else {{
                const hours = Math.floor(timeMinutes / 60);
                const mins = timeMinutes % 60;
                return mins > 0 ? `${{hours}}h ${{mins}}m walk` : `${{hours}}h walk`;
            }}
        }}
        
        // Create popup content
        function createPopup(props) {{
            let distanceHtml = '';
            if (userLocation) {{
                const [lat, lng] = userLocation;
                const dist = getDistance(lat, lng, props.lat, props.lng);
                const walkTime = getWalkingTime(dist);
                distanceHtml = `<div class="popup-distance">🚶 ${{walkTime}} (${{dist.toFixed(2)}} km)</div>`;
            }}
            
            // Google Maps link - mobile-friendly format
            const mapsUrl = props.place_id 
                ? `https://www.google.com/maps/search/?api=1&query=${{encodeURIComponent(props.name)}}&query_place_id=${{props.place_id}}`
                : `https://www.google.com/maps/search/?api=1&query=${{props.lat}},${{props.lng}}`;
            
            // Price level indicator
            let priceHtml = '';
            if (props.price_level !== null && props.price_level !== undefined) {{
                const priceSymbols = ['¥', '¥¥', '¥¥¥', '¥¥¥¥', '¥¥¥¥¥'];
                const priceLabels = ['Free', 'Inexpensive', 'Moderate', 'Expensive', 'Very Expensive'];
                const priceIndex = Math.min(props.price_level, 4);
                priceHtml = `<div class="popup-info">💴 ${{priceSymbols[priceIndex]}} <span style="color: #999; font-size: 11px;">(${{priceLabels[priceIndex]}})</span></div>`;
            }}
            
            // Photo carousel
            let photoHtml = '';
            if (props.photo_urls && props.photo_urls.length > 0) {{
                const carouselId = `carousel-${{Math.random().toString(36).substr(2, 9)}}`;
                const photos = props.photo_urls.map((url, idx) => 
                    `<img src="${{url}}" class="${{idx === 0 ? 'active' : ''}}" alt="${{props.name}}">`
                ).join('');
                
                const prevBtn = props.photo_urls.length > 1 ? 
                    `<button class="carousel-btn prev" onclick="changePhoto('${{carouselId}}', -1)">‹</button>` : '';
                const nextBtn = props.photo_urls.length > 1 ? 
                    `<button class="carousel-btn next" onclick="changePhoto('${{carouselId}}', 1)">›</button>` : '';
                const counter = props.photo_urls.length > 1 ? 
                    `<div class="photo-counter"><span id="${{carouselId}}-counter">1</span>/${{props.photo_urls.length}}</div>` : '';
                
                photoHtml = `<div class="photo-carousel" id="${{carouselId}}">${{photos}}${{prevBtn}}${{nextBtn}}${{counter}}</div>`;
            }}
            
            // Open/Closed status
            let statusHtml = '';
            if (props.open_now === true) {{
                statusHtml = `<div style="display: inline-block; background: #10b981; color: white; padding: 4px 8px; border-radius: 4px; font-size: 12px; font-weight: 600; margin-bottom: 8px;">🟢 Open now</div>`;
            }} else if (props.open_now === false) {{
                statusHtml = `<div style="display: inline-block; background: #ef4444; color: white; padding: 4px 8px; border-radius: 4px; font-size: 12px; font-weight: 600; margin-bottom: 8px;">🔴 Closed</div>`;
            }} else {{
                statusHtml = `<div style="display: inline-block; background: #94a3b8; color: white; padding: 4px 8px; border-radius: 4px; font-size: 12px; font-weight: 600; margin-bottom: 8px;">⚪ No hours data</div>`;
            }}
            
            return `
                ${{photoHtml}}
                <div class="popup-name">${{props.name}}</div>
                ${{statusHtml}}
                <div class="popup-rating">
                    <span>📊 Tabelog: ${{props.tabelog_rating}}</span>
                    <a href="${{mapsUrl}}" target="_blank" style="text-decoration: none; color: inherit;">
                        <span style="cursor: pointer; border-bottom: 2px solid #667eea;">⭐ Google: ${{props.google_rating}}</span>
                    </a>
                </div>
                ${{priceHtml}}
                <div class="popup-info">🍽️ ${{props.cuisine}}</div>
                <div class="popup-info">📍 ${{props.area}}</div>
                <div class="popup-info">💬 ${{props.google_reviews}} reviews</div>
                ${{distanceHtml}}
            `;
        }}
        
        // Get selected cuisines
        function getSelectedCuisines() {{
            const checkboxes = document.querySelectorAll('.cuisine-option input[type="checkbox"]:checked');
            return Array.from(checkboxes).map(cb => cb.value);
        }}
        
        // Add markers
        function addMarkers() {{
            const minRating = parseFloat(document.getElementById('rating-filter').value);
            const selectedCuisines = getSelectedCuisines();
            const openNowOnly = document.getElementById('open-now-filter').checked;
            
            // Clear existing markers
            markers.forEach(m => map.removeLayer(m));
            markers = [];
            
            // Filter and add new markers
            let count = 0;
            restaurants.features.forEach(feature => {{
                const props = feature.properties;
                const coords = feature.geometry.coordinates;
                
                // Rating filter
                if (props.google_rating < minRating) return;
                
                // Open Now filter - only exclude if explicitly closed
                if (openNowOnly) {{
                    if (props.open_now === false) return;
                }}
                
                // Cuisine filter (if any selected)
                if (selectedCuisines.length > 0) {{
                    const hasMatch = selectedCuisines.some(cuisine => 
                        props.categories && props.categories.includes(cuisine)
                    );
                    if (!hasMatch) return;
                }}
                
                // Adjust marker style for dark mode
                const isDarkMode = document.body.classList.contains('dark-mode');
                const borderColor = isDarkMode ? '#1a1a1a' : '#ffffff';
                
                const marker = L.circleMarker([coords[1], coords[0]], {{
                    radius: 6.4,
                    fillColor: props.google_rating >= 4.7 ? '#10b981' :  // Bright emerald green
                              props.google_rating >= 4.5 ? '#3b82f6' :  // Bright blue
                              '#8b5cf6',  // Bright purple/violet
                    color: borderColor,
                    weight: 2.5,
                    opacity: 1,
                    fillOpacity: 0.95
                }});
                
                marker.bindPopup(createPopup({{
                    ...props,
                    lat: coords[1],
                    lng: coords[0]
                }}));
                
                marker.addTo(map);
                markers.push(marker);
                count++;
            }});
            
            // Update stats
            const cuisineText = selectedCuisines.length > 0 ? 
                ` • ${{selectedCuisines.join(', ')}}` : '';
            document.querySelector('.stats').textContent = 
                `${{count}} Restaurants • Google ${{minRating}}+${{cuisineText}}`;
        }}
        
        // GPS tracking
        function enableGPS() {{
            if (gpsActive) {{
                gpsActive = false;
                document.getElementById('gps-btn').textContent = '📍 Enable GPS Tracking';
                document.getElementById('gps-btn').classList.remove('active');
                if (userMarker) {{
                    map.removeLayer(userMarker);
                    userMarker = null;
                }}
                userLocation = null;
                return;
            }}
            
            if (!navigator.geolocation) {{
                alert('GPS not supported by your browser');
                return;
            }}
            
            gpsActive = true;
            document.getElementById('gps-btn').textContent = '📍 GPS Active';
            document.getElementById('gps-btn').classList.add('active');
            
            navigator.geolocation.watchPosition(
                (position) => {{
                    const lat = position.coords.latitude;
                    const lng = position.coords.longitude;
                    userLocation = [lat, lng];
                    
                    // Update or create user marker
                    if (userMarker) {{
                        userMarker.setLatLng([lat, lng]);
                    }} else {{
                        userMarker = L.marker([lat, lng], {{
                            icon: L.divIcon({{
                                className: 'user-marker',
                                html: '<div style="background: #3b82f6; width: 20px; height: 20px; border-radius: 50%; border: 3px solid white; box-shadow: 0 2px 8px rgba(0,0,0,0.3);"></div>',
                                iconSize: [20, 20]
                            }})
                        }}).addTo(map);
                    }}
                    
                    // Center map on user
                    map.setView([lat, lng], 14);
                }},
                (error) => {{
                    alert('Could not get your location');
                    gpsActive = false;
                    document.getElementById('gps-btn').textContent = '📍 Enable GPS Tracking';
                    document.getElementById('gps-btn').classList.remove('active');
                }},
                {{
                    enableHighAccuracy: true,
                    maximumAge: 10000,
                    timeout: 5000
                }}
            );
        }}
        
        // Event listeners
        document.getElementById('rating-filter').addEventListener('change', addMarkers);
        document.getElementById('open-now-filter').addEventListener('change', addMarkers);
        document.getElementById('gps-btn').addEventListener('click', enableGPS);
        
        // Cuisine filter checkboxes
        document.querySelectorAll('.cuisine-option input[type="checkbox"]').forEach(checkbox => {{
            checkbox.addEventListener('change', addMarkers);
        }});
        
        // Photo carousel navigation
        window.changePhoto = function(carouselId, direction) {{
            const carousel = document.getElementById(carouselId);
            if (!carousel) return;
            
            const images = carousel.querySelectorAll('img');
            const counter = document.getElementById(carouselId + '-counter');
            
            let currentIndex = Array.from(images).findIndex(img => img.classList.contains('active'));
            images[currentIndex].classList.remove('active');
            
            currentIndex = (currentIndex + direction + images.length) % images.length;
            images[currentIndex].classList.add('active');
            
            if (counter) {{
                counter.textContent = currentIndex + 1;
            }}
        }}
        
        // Toggle controls visibility
        function toggleControls() {{
            const controls = document.getElementById('controls');
            const toggleBtn = document.getElementById('toggle-btn');
            
            if (controls.classList.contains('expanded')) {{
                controls.classList.remove('expanded');
                controls.classList.add('collapsed');
                toggleBtn.style.display = 'flex';
            }} else {{
                controls.classList.remove('collapsed');
                controls.classList.add('expanded');
                toggleBtn.style.display = 'none';
            }}
        }}
        
        // Dark mode toggle
        function toggleTheme() {{
            const body = document.body;
            const icon = document.getElementById('theme-icon');
            const isDark = body.classList.toggle('dark-mode');
            
            // Swap map tiles
            map.removeLayer(currentTiles);
            currentTiles = isDark ? darkTiles : lightTiles;
            currentTiles.addTo(map);
            
            // Update icon
            icon.textContent = isDark ? '☀️' : '🌙';
            
            // Refresh markers to update border colors
            addMarkers();
            
            // Save preference
            localStorage.setItem('darkMode', isDark ? 'true' : 'false');
        }}
        
        // Load dark mode preference BEFORE creating markers
        const savedDarkMode = localStorage.getItem('darkMode');
        if (savedDarkMode === 'true') {{
            document.body.classList.add('dark-mode');
            document.getElementById('theme-icon').textContent = '☀️';
            currentTiles = darkTiles;
            map.removeLayer(lightTiles);
            darkTiles.addTo(map);
        }}
        
        // Initial load (markers will check dark mode status)
        addMarkers();
        
        // Auto-collapse on mobile (run after DOM is ready)
        window.addEventListener('load', function() {{
            if (window.innerWidth < 768) {{
                const controls = document.getElementById('controls');
                const toggleBtn = document.getElementById('toggle-btn');
                controls.classList.remove('expanded');
                controls.classList.add('collapsed');
                toggleBtn.style.display = 'flex';
            }}
        }});
        
        // Register Service Worker for PWA
        if ('serviceWorker' in navigator) {{
            window.addEventListener('load', function() {{
                navigator.serviceWorker.register('/tokyo-food-finder/sw.js')
                    .then(registration => {{
                        console.log('ServiceWorker registered:', registration.scope);
                    }})
                    .catch(err => {{
                        console.log('ServiceWorker registration failed:', err);
                    }});
            }});
        }}
        
        // PWA Install Prompt
        let deferredPrompt;
        const installBtn = document.getElementById('install-btn');
        
        window.addEventListener('beforeinstallprompt', (e) => {{
            // Prevent Chrome 67 and earlier from automatically showing the prompt
            e.preventDefault();
            // Stash the event so it can be triggered later
            deferredPrompt = e;
            // Show the install button
            installBtn.style.display = 'block';
        }});
        
        // Handle install button click
        installBtn.addEventListener('click', async (e) => {{
            if (deferredPrompt) {{
                deferredPrompt.prompt();
                // Wait for the user to respond to the prompt
                const {{ outcome }} = await deferredPrompt.userChoice;
                console.log('User response to install prompt:', outcome);
                deferredPrompt = null;
                installBtn.style.display = 'none';
            }}
        }});
        
        // Hide button if app is already installed
        window.addEventListener('appinstalled', (e) => {{
            console.log('App installed successfully!');
            installBtn.style.display = 'none';
        }});
    </script>
</body>
</html>'''

# Save HTML
with open('index.html', 'w', encoding='utf-8') as f:
    f.write(html)

print("\n✅ Built index.html with cuisine filters")
print(f"📊 Total: {len(features)} restaurants with coordinates")
