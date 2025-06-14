import os
import json
import requests
from flask import Flask, request, jsonify
from flask_cors import CORS
import googlemaps
import openai
from dotenv import load_dotenv
from geopy.distance import geodesic
from concurrent.futures import ThreadPoolExecutor, as_completed
import time

load_dotenv()

app = Flask(__name__)
CORS(app)

GOOGLE_MAPS_API_KEY = os.getenv("GOOGLE_MAPS_API_KEY")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")

print(f"Google Maps API Key: {'Found' if GOOGLE_MAPS_API_KEY else 'Missing'}")
print(f"OpenAI API Key: {'Found' if OPENAI_API_KEY else 'Missing'}")

gmaps = googlemaps.Client(key=GOOGLE_MAPS_API_KEY)
openai.api_key = OPENAI_API_KEY

# Thread pool for concurrent operations
executor = ThreadPoolExecutor(max_workers=10)

@app.route('/api/health')
def health():
    return jsonify({
        "status": "healthy",
        "apis": {
            "google_maps": "configured" if GOOGLE_MAPS_API_KEY else "missing",
            "openai": "configured" if OPENAI_API_KEY else "missing"
        }
    })

def get_search_terms(service):
    """UNCHANGED: Get appropriate search terms based on service type"""
    if service == 'emergency':
        return ['hospital', 'medical center', 'clinic', 'emergency room']
    elif service == 'rehab_therapy':
        return [
            'physical therapy', 
            'rehabilitation center', 
            'speech therapy', 
            'occupational therapy',
            'physiotherapy clinic',
            'stroke rehabilitation',
            'neuro rehabilitation'
        ]
    elif service == 'support_groups':
        return [
            'stroke support group',
            'community center',
            'rehabilitation center',
            'mental health center',
            'counseling center',
            'support group meeting'
        ]
    else:
        # Default to emergency
        return ['hospital', 'medical center', 'clinic', 'emergency room']

def search_places_threaded(query, lat, lng):
    """Thread-safe version of search_places using requests (no aiohttp needed)"""
    url = "https://places.googleapis.com/v1/places:searchText"
    headers = {
        'Content-Type': 'application/json',
        'X-Goog-Api-Key': GOOGLE_MAPS_API_KEY,
        'X-Goog-FieldMask': 'places.displayName,places.formattedAddress,places.location,places.rating,places.userRatingCount,places.types,places.id,places.nationalPhoneNumber,places.websiteUri'
    }
    payload = {
        'textQuery': query,
        'locationBias': {
            'circle': {
                'center': {'latitude': lat, 'longitude': lng},
                'radius': 40000
            }
        },
        'maxResultCount': 20  # UNCHANGED: Keep original 20
    }
    
    try:
        response = requests.post(url, headers=headers, json=payload, timeout=8)
        print(f"API Response Status for '{query}': {response.status_code}")
        if response.status_code != 200:
            print(f"API Response Error for '{query}': {response.text}")
            return []
        result = response.json()
        places = result.get('places', [])
        print(f"Found {len(places)} results for '{query}'")
        return places
    except Exception as e:
        print(f"Places API error for '{query}': {e}")
        return []

def get_all_places_concurrent(search_terms, lat, lng):
    """Get all places using ThreadPoolExecutor instead of asyncio"""
    all_places = []
    
    # Submit all search tasks concurrently
    future_to_term = {
        executor.submit(search_places_threaded, term, lat, lng): term 
        for term in search_terms
    }
    
    # Collect results as they complete
    for future in as_completed(future_to_term, timeout=30):
        term = future_to_term[future]
        try:
            places = future.result()
            all_places.extend(places)
        except Exception as e:
            print(f"Error searching for '{term}': {e}")
    
    return all_places

def batch_analyze_with_ai(places_batch, service):
    """UNCHANGED: Analyze multiple places in one AI call to reduce API overhead"""
    if not places_batch:
        return {}
    
    try:
        # Prepare batch data
        batch_text = ""
        for i, (name, types) in enumerate(places_batch):
            batch_text += f"{i+1}. Name: \"{name}\", Types: {types}\n"
        
        # Create service-specific prompts (UNCHANGED logic)
        if service == 'emergency':
            ai_prompt = f"""Analyze these medical facilities for emergency stroke care suitability. For each facility, determine if it's medical and rate 0-100:

{batch_text}

Respond with JSON array: [{{"index": 1, "is_medical": true/false, "score": 0-100, "reason": "brief explanation"}}, {{"index": 2, "is_medical": true/false, "score": 0-100, "reason": "brief explanation"}}, ...]"""
        elif service == 'rehab_therapy':
            ai_prompt = f"""Analyze these facilities for stroke rehabilitation therapy suitability (physical therapy, speech therapy, occupational therapy). For each facility, determine if it's medical and rate 0-100:

{batch_text}

Respond with JSON array: [{{"index": 1, "is_medical": true/false, "score": 0-100, "reason": "brief explanation"}}, {{"index": 2, "is_medical": true/false, "score": 0-100, "reason": "brief explanation"}}, ...]"""
        elif service == 'support_groups':
            ai_prompt = f"""Analyze these facilities for stroke support groups or mental health support suitability. For each facility, determine if it's medical and rate 0-100:

{batch_text}

Respond with JSON array: [{{"index": 1, "is_medical": true/false, "score": 0-100, "reason": "brief explanation"}}, {{"index": 2, "is_medical": true/false, "score": 0-100, "reason": "brief explanation"}}, ...]"""
        else:
            ai_prompt = f"""Analyze these medical facilities for {service} suitability. For each facility, determine if it's medical and rate 0-100:

{batch_text}

Respond with JSON array: [{{"index": 1, "is_medical": true/false, "score": 0-100, "reason": "brief explanation"}}, {{"index": 2, "is_medical": true/false, "score": 0-100, "reason": "brief explanation"}}, ...]"""
        
        ai_response = openai.ChatCompletion.create(
            model="gpt-3.5-turbo",
            messages=[
                {"role": "system", "content": "Analyze facilities and respond only with valid JSON array. Be consistent with the original individual analysis criteria."},
                {"role": "user", "content": ai_prompt}
            ],
            max_tokens=800,
            temperature=0.1
        )
        
        results_array = json.loads(ai_response.choices[0].message.content.strip())
        
        # Convert to dictionary for easy lookup
        results_dict = {}
        for result in results_array:
            idx = result.get('index', 0) - 1  # Convert to 0-based
            if 0 <= idx < len(places_batch):
                results_dict[idx] = result
        
        return results_dict
        
    except Exception as e:
        print(f"Batch AI error: {e}")
        # Fallback: return default for all (same as original behavior when AI fails)
        return {i: {"is_medical": False, "score": 0, "reason": "Analysis failed"} 
                for i in range(len(places_batch))}

@app.route('/api/search', methods=['POST'])
def search():
    start_time = time.time()
    data = request.json
    location = data.get('location')
    service = data.get('service', 'emergency')
    
    print(f"Search: {location}, {service}")
    
    try:
        # Geocode (UNCHANGED)
        geocode_result = gmaps.geocode(location)
        if not geocode_result:
            return jsonify({"error": "Location not found"}), 400
            
        lat = geocode_result[0]['geometry']['location']['lat']
        lng = geocode_result[0]['geometry']['location']['lng']
        print(f"Geocoded to: {lat}, {lng}")
        
        # Get service-specific search terms (UNCHANGED)
        search_terms = get_search_terms(service)
        print(f"Search terms for {service}: {search_terms}")
        
        # OPTIMIZED: Concurrent places search using threading
        places_start = time.time()
        all_places = get_all_places_concurrent(search_terms, lat, lng)
        places_time = time.time() - places_start
        print(f"Concurrent places search took: {places_time:.2f}s")
        
        # Remove duplicates (UNCHANGED logic)
        unique_places = {}
        for place in all_places:
            place_id = place.get('id')
            if place_id and place_id not in unique_places:
                unique_places[place_id] = place
        
        print(f"Total unique places: {len(unique_places)}")
        
        # Process places with BATCHED AI analysis
        places_list = list(unique_places.values())[:15]  # UNCHANGED: limit to 15
        
        # Prepare data for batch AI analysis
        ai_start = time.time()
        places_for_ai = []
        place_details = []
        
        for place in places_list:
            name = place.get('displayName', {}).get('text', 'Unknown')
            types = place.get('types', [])
            places_for_ai.append((name, types))
            place_details.append(place)
        
        # OPTIMIZED: Batch AI analysis instead of individual calls
        ai_results = batch_analyze_with_ai(places_for_ai, service)
        ai_time = time.time() - ai_start
        print(f"Batch AI analysis took: {ai_time:.2f}s")
        
        # Process results (UNCHANGED logic)
        results = []
        for i, place in enumerate(place_details):
            try:
                name = place.get('displayName', {}).get('text', 'Unknown')
                types = place.get('types', [])
                
                # Get AI analysis result for this place
                ai_result = ai_results.get(i, {"is_medical": False, "score": 0, "reason": "Analysis failed"})
                
                # UNCHANGED: Same filtering logic
                if not ai_result.get('is_medical', False):
                    print(f"AI rejected: {name}")
                    continue
                
                # UNCHANGED: Distance calculation
                place_lat = place['location']['latitude']
                place_lng = place['location']['longitude']
                distance = geodesic((lat, lng), (place_lat, place_lng)).miles
                
                if distance > 50:
                    continue
                
                # UNCHANGED: Score calculation
                score = ai_result.get('score', 70)
                if distance < 5:
                    score += 10
                
                # UNCHANGED: Create service-specific services object
                services_obj = {
                    "emergency": service == 'emergency',
                    "rehab_therapy": service == 'rehab_therapy',
                    "support_groups": service == 'support_groups',
                    "stroke_certified": False,
                    "neuro_icu": service == 'emergency',
                    "rehabilitation": service == 'rehab_therapy'
                }
                
                # UNCHANGED: Add service-specific details based on types and AI analysis
                if service == 'rehab_therapy':
                    services_obj.update({
                        "physical_therapy": any(t in ['physiotherapist', 'physical_therapy'] for t in types),
                        "speech_therapy": any(t in ['speech_therapist', 'speech_therapy'] for t in types),
                        "occupational_therapy": any(t in ['occupational_therapy'] for t in types)
                    })
                
                # UNCHANGED: Result object structure
                result = {
                    "name": name,
                    "address": place.get('formattedAddress', 'Address not available'),
                    "distance_miles": round(distance, 1),
                    "relevance_score": min(score, 100),
                    "services": services_obj,
                    "languages": ["English", "Nepali"] if "kathmandu" in location.lower() else ["English"],
                    "ai_reasoning": ai_result.get('reason', f'{service.replace("_", " ").title()} facility'),
                    "contact": {
                        "phone": place.get('nationalPhoneNumber'),
                        "website": place.get('websiteUri')
                    },
                    "rating": place.get('rating'),
                    "rating_count": place.get('userRatingCount', 0),
                    "hours": "Contact for hours",
                    "place_id": place.get('id', 'unknown'),
                    "facility_types": types,
                    "service_type": service
                }
                results.append(result)
                print(f"Added: {name} (Score: {score})")
                
            except Exception as e:
                print(f"Error processing: {e}")
                continue
        
        # UNCHANGED: Sort by relevance score
        results.sort(key=lambda x: x['relevance_score'], reverse=True)
        
        total_time = time.time() - start_time
        print(f"TOTAL REQUEST TIME: {total_time:.2f}s")
        
        # UNCHANGED: Response structure
        return jsonify({
            "results": results,
            "search_metadata": {
                "query": location,
                "service": service,
                "total_found": len(results),
                "coordinates": {"lat": lat, "lng": lng},
                "search_terms_used": search_terms,
                "performance": {
                    "total_time": round(total_time, 2),
                    "places_search_time": round(places_time, 2),
                    "ai_analysis_time": round(ai_time, 2)
                }
            }
        })
        
    except Exception as e:
        print(f"Search error: {e}")
        return jsonify({"error": str(e)}), 500

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=8000, debug=True)