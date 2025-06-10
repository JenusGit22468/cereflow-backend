from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import List, Optional, Dict
import googlemaps
import openai
import json
import re
from geopy.geocoders import Nominatim
from geopy.distance import geodesic
import asyncio
import aiohttp
import os
from datetime import datetime
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

# Initialize FastAPI app
app = FastAPI(title="Ctrl+Z Stroke Care API", version="1.0.0")

# CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # In production, specify your frontend domain
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Configuration from environment variables
GOOGLE_MAPS_API_KEY = os.getenv("GOOGLE_MAPS_API_KEY")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")

if not GOOGLE_MAPS_API_KEY or not OPENAI_API_KEY:
    print(f"Google Maps API Key: {'Found' if GOOGLE_MAPS_API_KEY else 'Missing'}")
    print(f"OpenAI API Key: {'Found' if OPENAI_API_KEY else 'Missing'}")
    raise ValueError("Missing required API keys in environment variables")

# Initialize clients
gmaps = googlemaps.Client(key=GOOGLE_MAPS_API_KEY)
openai.api_key = OPENAI_API_KEY
geolocator = Nominatim(user_agent="ctrl_z_stroke_locator")

# Pydantic models
class SearchRequest(BaseModel):
    location: str
    service: str  # 'emergency', 'rehab_therapy', 'support_groups'
    language: str
    radius_miles: Optional[int] = 25

class Contact(BaseModel):
    phone: Optional[str] = None
    website: Optional[str] = None
    email: Optional[str] = None

class Services(BaseModel):
    emergency: bool = False
    rehab_therapy: bool = False
    support_groups: bool = False
    stroke_certified: bool = False
    neuro_icu: bool = False
    rehabilitation: bool = False

class FacilityResult(BaseModel):
    name: str
    address: str
    distance_miles: float
    relevance_score: int
    services: Services
    languages: List[str]
    ai_reasoning: str
    contact: Contact
    rating: Optional[float] = None
    hours: Optional[str] = None
    place_id: str

class SearchResponse(BaseModel):
    results: List[FacilityResult]
    search_metadata: Dict

# Service type mappings for Google Places search
SERVICE_KEYWORDS = {
    'emergency': [
        'hospital emergency room',
        'emergency department',
        'stroke center',
        'trauma center',
        'medical center emergency'
    ],
    'rehab_therapy': [
        'stroke rehabilitation center',
        'neurological rehabilitation',
        'physical therapy stroke',
        'occupational therapy',
        'speech therapy clinic',
        'neurorehabilitation center'
    ],
    'support_groups': [
        'stroke support group',
        'stroke survivor organization',
        'brain injury support',
        'neurological support center',
        'stroke foundation local chapter'
    ]
}

# Stroke-specific facility classifications
STROKE_FACILITY_TYPES = {
    'comprehensive_stroke_center': {
        'keywords': ['comprehensive stroke center', 'CSC'],
        'score_boost': 25
    },
    'primary_stroke_center': {
        'keywords': ['primary stroke center', 'PSC', 'stroke certified'],
        'score_boost': 20
    },
    'thrombectomy_capable': {
        'keywords': ['thrombectomy', 'endovascular', 'neuro interventional'],
        'score_boost': 15
    },
    'level_1_trauma': {
        'keywords': ['level 1 trauma', 'level I trauma'],
        'score_boost': 10
    }
}

def geocode_location(location: str) -> tuple:
    """Convert location string to coordinates"""
    try:
        print(f"Geocoding location: {location}")
        geocode_result = gmaps.geocode(location)
        if geocode_result:
            lat = geocode_result[0]['geometry']['location']['lat']
            lng = geocode_result[0]['geometry']['location']['lng']
            print(f"Geocoded to: {lat}, {lng}")
            return lat, lng
        else:
            raise HTTPException(status_code=400, detail=f"Could not geocode location: {location}")
    except Exception as e:
        print(f"Geocoding error: {e}")
        raise HTTPException(status_code=400, detail=f"Geocoding error: {str(e)}")

def search_places_by_service(lat: float, lng: float, service_type: str, radius_miles: int = 25) -> List[Dict]:
    """Search for places using Google Places API based on service type"""
    radius_meters = radius_miles * 1609.34  # Convert miles to meters
    all_results = []
    
    keywords = SERVICE_KEYWORDS.get(service_type, ['hospital'])
    print(f"Searching for {service_type} with keywords: {keywords}")
    
    for keyword in keywords:
        try:
            # Text search for more specific results
            places_result = gmaps.places_nearby(
                location=(lat, lng),
                radius=radius_meters,
                keyword=keyword,
                type='hospital'
            )
            
            if places_result.get('results'):
                print(f"Found {len(places_result['results'])} results for keyword: {keyword}")
                all_results.extend(places_result['results'])
            
            # Also try a text search for better keyword matching
            text_search = gmaps.places(
                query=f"{keyword} near {lat},{lng}",
                location=(lat, lng),
                radius=radius_meters
            )
            
            if text_search.get('results'):
                print(f"Found {len(text_search['results'])} text search results for: {keyword}")
                all_results.extend(text_search['results'])
                
        except Exception as e:
            print(f"Error searching for {keyword}: {e}")
            continue
    
    # Remove duplicates based on place_id
    unique_results = {}
    for place in all_results:
        place_id = place.get('place_id')
        if place_id and place_id not in unique_results:
            unique_results[place_id] = place
    
    print(f"Total unique places found: {len(unique_results)}")
    return list(unique_results.values())

def get_place_details(place_id: str) -> Dict:
    """Get detailed information about a place"""
    try:
        print(f"Getting details for place: {place_id}")
        details = gmaps.place(
            place_id=place_id,
            fields=[
                'name', 'formatted_address', 'formatted_phone_number',
                'website', 'rating', 'opening_hours', 'types',
                'reviews', 'geometry', 'business_status'
            ]
        )
        return details.get('result', {})
    except Exception as e:
        print(f"Error getting place details for {place_id}: {e}")
        return {}

def calculate_relevance_score(place: Dict, place_details: Dict, service_type: str, user_lat: float, user_lng: float) -> int:
    """Calculate relevance score based on multiple factors"""
    base_score = 50
    
    name = place.get('name', '').lower()
    address = place_details.get('formatted_address', '').lower()
    types = place.get('types', [])
    
    # Service type matching
    service_keywords = SERVICE_KEYWORDS.get(service_type, [])
    for keyword in service_keywords:
        if any(word in name for word in keyword.lower().split()):
            base_score += 15
        if any(word in address for word in keyword.lower().split()):
            base_score += 5
    
    # Stroke facility type bonuses
    for facility_type, info in STROKE_FACILITY_TYPES.items():
        for keyword in info['keywords']:
            if keyword.lower() in name or keyword.lower() in address:
                base_score += info['score_boost']
    
    # Hospital/medical facility type bonus
    medical_types = ['hospital', 'doctor', 'health', 'medical_care']
    if any(t in types for t in medical_types):
        base_score += 10
    
    # Rating bonus
    rating = place.get('rating', 0)
    if rating > 4.0:
        base_score += 10
    elif rating > 3.5:
        base_score += 5
    
    # Distance penalty (closer is better)
    place_lat = place['geometry']['location']['lat']
    place_lng = place['geometry']['location']['lng']
    distance = geodesic((user_lat, user_lng), (place_lat, place_lng)).miles
    
    if distance <= 5:
        base_score += 5
    elif distance <= 10:
        base_score += 2
    elif distance > 20:
        base_score -= 5
    
    # Business status check
    if place_details.get('business_status') == 'CLOSED_PERMANENTLY':
        base_score -= 50
    
    return min(max(base_score, 0), 100)  # Clamp between 0-100

def analyze_facility_with_ai(place: Dict, place_details: Dict, service_type: str) -> tuple:
    """Use AI to analyze facility and generate reasoning"""
    try:
        print(f"Analyzing facility with AI: {place.get('name')}")
        
        facility_info = {
            'name': place.get('name'),
            'address': place_details.get('formatted_address'),
            'types': place.get('types'),
            'rating': place.get('rating'),
            'phone': place_details.get('formatted_phone_number'),
            'website': place_details.get('website'),
            'service_requested': service_type
        }
        
        # Get recent reviews for context
        reviews = place_details.get('reviews', [])[:3]  # Last 3 reviews
        review_text = ""
        if reviews:
            review_text = "\n".join([f"- {review.get('text', '')[:200]}..." for review in reviews])
        
        prompt = f"""
        As a medical facility expert, analyze this healthcare facility for stroke care services.
        
        Facility Information:
        {json.dumps(facility_info, indent=2)}
        
        Recent Reviews:
        {review_text}
        
        Service Requested: {service_type}
        
        Please provide:
        1. A brief assessment (2-3 sentences) of why this facility is suitable for the requested service
        2. Determine what services they likely offer (emergency, rehab_therapy, support_groups, stroke_certified)
        3. Estimate what languages they might support based on location and type
        
        Return a JSON object with:
        {{
            "reasoning": "Brief explanation of suitability",
            "services": {{
                "emergency": boolean,
                "rehab_therapy": boolean,
                "support_groups": boolean,
                "stroke_certified": boolean,
                "neuro_icu": boolean,
                "rehabilitation": boolean
            }},
            "languages": ["list", "of", "likely", "languages"]
        }}
        """
        
        response = openai.ChatCompletion.create(
            model="gpt-3.5-turbo",
            messages=[
                {"role": "system", "content": "You are a medical facility expert specializing in stroke care assessment. Always respond with valid JSON."},
                {"role": "user", "content": prompt}
            ],
            max_tokens=500,
            temperature=0.3
        )
        
        ai_response = response.choices[0].message.content
        print(f"AI Response: {ai_response[:100]}...")
        
        # Parse JSON response
        try:
            ai_data = json.loads(ai_response)
            return ai_data.get('reasoning', ''), ai_data.get('services', {}), ai_data.get('languages', ['English'])
        except json.JSONDecodeError:
            # Fallback if AI doesn't return valid JSON
            return ai_response[:200] + "...", {service_type: True}, ['English']
            
    except Exception as e:
        print(f"AI analysis error: {e}")
        # Fallback analysis
        fallback_reasoning = f"Medical facility offering {service_type.replace('_', ' ')} services in the area."
        fallback_services = {service_type: True}
        return fallback_reasoning, fallback_services, ['English']

@app.post("/api/search", response_model=SearchResponse)
async def search_stroke_facilities(request: SearchRequest):
    """Main search endpoint for stroke care facilities"""
    try:
        print(f"Search request: {request}")
        
        # Geocode the location
        user_lat, user_lng = geocode_location(request.location)
        
        # Search for places
        places = search_places_by_service(
            user_lat, user_lng, 
            request.service, 
            request.radius_miles
        )
        
        if not places:
            print("No places found")
            return SearchResponse(
                results=[],
                search_metadata={
                    "query": request.location,
                    "service": request.service,
                    "radius_miles": request.radius_miles,
                    "total_found": 0,
                    "timestamp": datetime.now().isoformat()
                }
            )
        
        # Process each facility
        facilities = []
        for i, place in enumerate(places[:10]):  # Limit to top 10 results
            try:
                print(f"Processing facility {i+1}/{min(len(places), 10)}: {place.get('name')}")
                
                place_id = place.get('place_id')
                if not place_id:
                    continue
                
                # Get detailed information
                place_details = get_place_details(place_id)
                
                # Calculate distance
                place_lat = place['geometry']['location']['lat']
                place_lng = place['geometry']['location']['lng']
                distance = geodesic((user_lat, user_lng), (place_lat, place_lng)).miles
                
                # Calculate relevance score
                relevance_score = calculate_relevance_score(
                    place, place_details, request.service, user_lat, user_lng
                )
                
                # AI analysis
                ai_reasoning, ai_services, ai_languages = analyze_facility_with_ai(
                    place, place_details, request.service
                )
                
                # Build facility result
                facility = FacilityResult(
                    name=place.get('name', 'Unknown Facility'),
                    address=place_details.get('formatted_address', 'Address not available'),
                    distance_miles=round(distance, 1),
                    relevance_score=relevance_score,
                    services=Services(**ai_services),
                    languages=ai_languages,
                    ai_reasoning=ai_reasoning,
                    contact=Contact(
                        phone=place_details.get('formatted_phone_number'),
                        website=place_details.get('website')
                    ),
                    rating=place.get('rating'),
                    hours=place_details.get('opening_hours', {}).get('weekday_text', [''])[0] if place_details.get('opening_hours') else None,
                    place_id=place_id
                )
                
                facilities.append(facility)
                print(f"Added facility: {facility.name} (Score: {facility.relevance_score})")
                
            except Exception as e:
                print(f"Error processing facility: {e}")
                continue
        
        # Sort by relevance score (highest first)
        facilities.sort(key=lambda x: x.relevance_score, reverse=True)
        
        print(f"Returning {len(facilities)} facilities")
        
        return SearchResponse(
            results=facilities,
            search_metadata={
                "query": request.location,
                "service": request.service,
                "language": request.language,
                "radius_miles": request.radius_miles,
                "total_found": len(facilities),
                "coordinates": {"lat": user_lat, "lng": user_lng},
                "timestamp": datetime.now().isoformat()
            }
        )
        
    except HTTPException:
        raise
    except Exception as e:
        print(f"Search error: {e}")
        raise HTTPException(status_code=500, detail=f"Search error: {str(e)}")

@app.get("/api/health")
async def health_check():
    """Health check endpoint"""
    return {
        "status": "healthy",
        "timestamp": datetime.now().isoformat(),
        "version": "1.0.0",
        "apis": {
            "google_maps": "configured" if GOOGLE_MAPS_API_KEY else "missing",
            "openai": "configured" if OPENAI_API_KEY else "missing"
        }
    }

@app.get("/api/facility/{place_id}")
async def get_facility_details_endpoint(place_id: str):
    """Get detailed information about a specific facility"""
    try:
        place_details = get_place_details(place_id)
        if not place_details:
            raise HTTPException(status_code=404, detail="Facility not found")
        
        return {
            "place_id": place_id,
            "details": place_details,
            "timestamp": datetime.now().isoformat()
        }
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error fetching facility details: {str(e)}")

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000, reload=True)