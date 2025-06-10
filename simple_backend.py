import os
import json
import requests
from flask import Flask, request, jsonify
from flask_cors import CORS
import googlemaps
import openai
from dotenv import load_dotenv
from geopy.distance import geodesic

load_dotenv()

app = Flask(__name__)
CORS(app)

GOOGLE_MAPS_API_KEY = os.getenv("GOOGLE_MAPS_API_KEY")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")

print(f"Google Maps API Key: {'Found' if GOOGLE_MAPS_API_KEY else 'Missing'}")
print(f"OpenAI API Key: {'Found' if OPENAI_API_KEY else 'Missing'}")

gmaps = googlemaps.Client(key=GOOGLE_MAPS_API_KEY)
openai.api_key = OPENAI_API_KEY

@app.route('/')
def root():
    return jsonify({"message": "Backend is running!", "status": "ok"})

@app.route('/api/health', methods=['GET'])
def health():
    return jsonify({
        "status": "healthy",
        "apis": {
            "google_maps": "configured" if GOOGLE_MAPS_API_KEY else "missing",
            "openai": "configured" if OPENAI_API_KEY else "missing"
        }
    })

@app.route('/test')
def test():
    return jsonify({"message": "Test route works!"})

def get_search_terms(service):
    """Get appropriate search terms based on service type"""
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

def search_places(query, lat, lng):
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
        'maxResultCount': 20
    }
    
    try:
        response = requests.post(url, headers=headers, json=payload)
        print(f"API Response Status: {response.status_code}")
        if response.status_code != 200:
            print(f"API Response Error: {response.text}")
        response.raise_for_status()
        return response.json()
    except requests.RequestException as e:
        print(f"Places API error: {e}")
        return None

def analyze_with_ai(name, types, service):
    try:
        # Create service-specific prompts
        if service == 'emergency':
            ai_prompt = f"""Is "{name}" with types {types} a medical facility suitable for emergency stroke care?
            
            Respond with JSON: {{"is_medical": true/false, "score": 0-100, "reason": "brief explanation"}}"""
        elif service == 'rehab_therapy':
            ai_prompt = f"""Is "{name}" with types {types} a rehabilitation or therapy facility suitable for stroke recovery (physical therapy, speech therapy, occupational therapy)?
            
            Respond with JSON: {{"is_medical": true/false, "score": 0-100, "reason": "brief explanation"}}"""
        elif service == 'support_groups':
            ai_prompt = f"""Is "{name}" with types {types} a facility that could host stroke support groups or provide mental health support?
            
            Respond with JSON: {{"is_medical": true/false, "score": 0-100, "reason": "brief explanation"}}"""
        else:
            ai_prompt = f"""Is "{name}" with types {types} a medical facility suitable for {service}?
            
            Respond with JSON: {{"is_medical": true/false, "score": 0-100, "reason": "brief explanation"}}"""
        
        ai_response = openai.ChatCompletion.create(
            model="gpt-3.5-turbo",
            messages=[
                {"role": "system", "content": "Analyze facilities and respond only with valid JSON."},
                {"role": "user", "content": ai_prompt}
            ],
            max_tokens=100,
            temperature=0.1
        )
        
        result = json.loads(ai_response.choices[0].message.content.strip())
        return result
        
    except Exception as e:
        print(f"AI error: {e}")
        return {"is_medical": False, "score": 0, "reason": "Analysis failed"}

@app.route('/api/search', methods=['POST'])
def search():
    data = request.json
    location = data.get('location')
    service = data.get('service', 'emergency')
    
    print(f"Search: {location}, {service}")
    
    try:
        # Geocode
        geocode_result = gmaps.geocode(location)
        if not geocode_result:
            return jsonify({"error": "Location not found"}), 400
            
        lat = geocode_result[0]['geometry']['location']['lat']
        lng = geocode_result[0]['geometry']['location']['lng']
        print(f"Geocoded to: {lat}, {lng}")
        
        # Get service-specific search terms
        search_terms = get_search_terms(service)
        print(f"Search terms for {service}: {search_terms}")
        
        all_places = []
        for term in search_terms:
            print(f"Searching for: {term}")
            result = search_places(term, lat, lng)
            if result and result.get('places'):
                all_places.extend(result['places'])
                print(f"Found {len(result['places'])} results")
        
        # Remove duplicates
        unique_places = {}
        for place in all_places:
            place_id = place.get('id')
            if place_id and place_id not in unique_places:
                unique_places[place_id] = place
        
        print(f"Total unique places: {len(unique_places)}")
        
        results = []
        for place in list(unique_places.values())[:15]:
            try:
                name = place.get('displayName', {}).get('text', 'Unknown')
                types = place.get('types', [])
                
                # AI analysis with service-specific prompts
                ai_result = analyze_with_ai(name, types, service)
                
                if not ai_result.get('is_medical', False):
                    print(f"AI rejected: {name}")
                    continue
                
                # Distance
                place_lat = place['location']['latitude']
                place_lng = place['location']['longitude']
                distance = geodesic((lat, lng), (place_lat, place_lng)).miles
                
                if distance > 50:
                    continue
                
                score = ai_result.get('score', 70)
                if distance < 5:
                    score += 10
                
                # Create service-specific services object
                services_obj = {
                    "emergency": service == 'emergency',
                    "rehab_therapy": service == 'rehab_therapy',
                    "support_groups": service == 'support_groups',
                    "stroke_certified": False,
                    "neuro_icu": service == 'emergency',
                    "rehabilitation": service == 'rehab_therapy'
                }
                
                # Add service-specific details based on types and AI analysis
                if service == 'rehab_therapy':
                    services_obj.update({
                        "physical_therapy": any(t in ['physiotherapist', 'physical_therapy'] for t in types),
                        "speech_therapy": any(t in ['speech_therapist', 'speech_therapy'] for t in types),
                        "occupational_therapy": any(t in ['occupational_therapy'] for t in types)
                    })
                
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
                    "rating_count": place.get('userRatingCount', 0),  # Add this line
                    "hours": "Contact for hours",
                    "place_id": place.get('id', 'unknown'),
                    "facility_types": types,
                    "service_type": service  # Add this to help frontend distinguish
                }
                results.append(result)
                print(f"Added: {name} (Score: {score})")
                
            except Exception as e:
                print(f"Error processing: {e}")
                continue
        
        results.sort(key=lambda x: x['relevance_score'], reverse=True)
        
        return jsonify({
            "results": results,
            "search_metadata": {
                "query": location,
                "service": service,
                "total_found": len(results),
                "coordinates": {"lat": lat, "lng": lng},
                "search_terms_used": search_terms
            }
        })
        
    except Exception as e:
        print(f"Search error: {e}")
        return jsonify({"error": str(e)}), 500

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=3000, debug=False)
