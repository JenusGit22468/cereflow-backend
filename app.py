import os
import json
import requests
from flask import Flask, request, jsonify, Response
from flask_cors import CORS
import googlemaps
import openai
from dotenv import load_dotenv
from geopy.distance import geodesic
from concurrent.futures import ThreadPoolExecutor, as_completed
import time
import tempfile
import threading

load_dotenv()

app = Flask(__name__)
CORS(app)

# API Keys
GOOGLE_MAPS_API_KEY = os.getenv("GOOGLE_MAPS_API_KEY")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
ELEVENLABS_API_KEY = os.getenv("ELEVENLABS_API_KEY")

print(f"Google Maps API Key: {'Found' if GOOGLE_MAPS_API_KEY else 'Missing'}")
print(f"OpenAI API Key: {'Found' if OPENAI_API_KEY else 'Missing'}")
print(f"ElevenLabs API Key: {'Found' if ELEVENLABS_API_KEY else 'Missing'}")

gmaps = googlemaps.Client(key=GOOGLE_MAPS_API_KEY)
openai.api_key = OPENAI_API_KEY

# Thread pool for concurrent operations
executor = ThreadPoolExecutor(max_workers=10)

# =============================================================================
# HEALTH CHECK
# =============================================================================

@app.route('/')
def root():
    return jsonify({"message": "Backend is running!", "status": "ok"})

@app.route('/api/health')
def health():
    return jsonify({
        "status": "healthy",
        "apis": {
            "google_maps": "configured" if GOOGLE_MAPS_API_KEY else "missing",
            "openai": "configured" if OPENAI_API_KEY else "missing",
            "elevenlabs": "configured" if ELEVENLABS_API_KEY else "missing"
        }
    })

# =============================================================================
# SEARCH FUNCTIONALITY - REAL DATA, NO MOCKS
# =============================================================================

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
        return ['hospital', 'medical center', 'clinic', 'emergency room']

def search_places_threaded(query, lat, lng):
    """Thread-safe version of search_places using REAL Google Places API"""
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
    """Get all places using ThreadPoolExecutor for concurrent REAL API calls"""
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
    """Analyze multiple places in one REAL OpenAI API call"""
    if not places_batch:
        return {}
    
    try:
        # Prepare batch data
        batch_text = ""
        for i, (name, types) in enumerate(places_batch):
            batch_text += f"{i+1}. Name: \"{name}\", Types: {types}\n"
        
        # Create service-specific prompts
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
        
        # REAL OpenAI API call
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
        return {i: {"is_medical": False, "score": 0, "reason": "Analysis failed"} 
                for i in range(len(places_batch))}

@app.route('/api/search', methods=['POST'])
def search():
    """REAL search using Google Places API and OpenAI - NO MOCK DATA"""
    start_time = time.time()
    data = request.json
    location = data.get('location')
    service = data.get('service', 'emergency')
    
    print(f"Search: {location}, {service}")
    
    try:
        # REAL Geocoding with Google Maps
        geocode_result = gmaps.geocode(location)
        if not geocode_result:
            return jsonify({"error": "Location not found"}), 400
            
        lat = geocode_result[0]['geometry']['location']['lat']
        lng = geocode_result[0]['geometry']['location']['lng']
        print(f"Geocoded to: {lat}, {lng}")
        
        # Get service-specific search terms
        search_terms = get_search_terms(service)
        print(f"Search terms for {service}: {search_terms}")
        
        # REAL concurrent places search
        places_start = time.time()
        all_places = get_all_places_concurrent(search_terms, lat, lng)
        places_time = time.time() - places_start
        print(f"Concurrent places search took: {places_time:.2f}s")
        
        # Remove duplicates
        unique_places = {}
        for place in all_places:
            place_id = place.get('id')
            if place_id and place_id not in unique_places:
                unique_places[place_id] = place
        
        print(f"Total unique places: {len(unique_places)}")
        
        # Process places with REAL AI analysis
        places_list = list(unique_places.values())[:15]
        
        # Prepare data for batch AI analysis
        ai_start = time.time()
        places_for_ai = []
        place_details = []
        
        for place in places_list:
            name = place.get('displayName', {}).get('text', 'Unknown')
            types = place.get('types', [])
            places_for_ai.append((name, types))
            place_details.append(place)
        
        # REAL AI analysis
        ai_results = batch_analyze_with_ai(places_for_ai, service)
        ai_time = time.time() - ai_start
        print(f"Batch AI analysis took: {ai_time:.2f}s")
        
        # Process results
        results = []
        for i, place in enumerate(place_details):
            try:
                name = place.get('displayName', {}).get('text', 'Unknown')
                types = place.get('types', [])
                
                # Get AI analysis result for this place
                ai_result = ai_results.get(i, {"is_medical": False, "score": 0, "reason": "Analysis failed"})
                
                if not ai_result.get('is_medical', False):
                    print(f"AI rejected: {name}")
                    continue
                
                # REAL distance calculation
                place_lat = place['location']['latitude']
                place_lng = place['location']['longitude']
                distance = geodesic((lat, lng), (place_lat, place_lng)).miles
                
                if distance > 50:
                    continue
                
                # Score calculation
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
                
                if service == 'rehab_therapy':
                    services_obj.update({
                        "physical_therapy": any(t in ['physiotherapist', 'physical_therapy'] for t in types),
                        "speech_therapy": any(t in ['speech_therapist', 'speech_therapy'] for t in types),
                        "occupational_therapy": any(t in ['occupational_therapy'] for t in types)
                    })
                
                # REAL result object with actual data
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
        
        # Sort by relevance score
        results.sort(key=lambda x: x['relevance_score'], reverse=True)
        
        total_time = time.time() - start_time
        print(f"TOTAL REQUEST TIME: {total_time:.2f}s")
        
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

# =============================================================================
# STROKE-OPTIMIZED SPEECH FUNCTIONALITY WITH ENHANCED VOICE CLONING
# =============================================================================

class StrokeOptimizedSpeechProcessor:
    def __init__(self):
        self.elevenlabs_base_url = "https://api.elevenlabs.io/v1"
        # Voice IDs for fallback voices that sound natural for different demographics
        self.fallback_voices = {
            "mature_male": "29vD33N1CtxCmqQRPOHJ",     # Default male voice
            "mature_female": "21m00Tcm4TlvDq8ikWAM",   # Default female voice
            "young_male": "CYw3kZ02Hs0563khs1Fj",      # Younger male voice
            "young_female": "pNInz6obpgDQGcFmaJgB"     # Younger female voice
        }
        self._warmup()
        
    def _warmup(self):
        """Pre-warm APIs to reduce first-request latency"""
        try:
            threading.Thread(target=self._warmup_openai, daemon=True).start()
            threading.Thread(target=self._warmup_elevenlabs, daemon=True).start()
        except Exception:
            pass
    
    def _warmup_openai(self):
        try:
            openai.ChatCompletion.create(
                model="gpt-3.5-turbo",
                messages=[{"role": "user", "content": "Hi"}],
                max_tokens=1
            )
        except:
            pass
    
    def _warmup_elevenlabs(self):
        try:
            requests.get(f"{self.elevenlabs_base_url}/voices", 
                        headers={"xi-api-key": ELEVENLABS_API_KEY}, timeout=5)
        except:
            pass
    
    def assess_speech_clarity(self, file_path):
        """Assess if speech is clear enough for voice cloning"""
        try:
            import wave
            
            file_size = os.path.getsize(file_path)
            print(f"STROKE DEBUG: Audio file size: {file_size} bytes")
            
            # Basic file size checks
            if file_size == 0:
                return False, "Audio file is empty"
            if file_size > 25 * 1024 * 1024:  # 25MB limit
                return False, "Audio file too large (max 25MB)"
            if file_size < 15000:  # Increased minimum for stroke patients
                return False, "Audio too short - need at least 15-30 seconds for stroke voice cloning"
            
            # Try to read as WAV and get duration
            try:
                with wave.open(file_path, 'rb') as wav_file:
                    frames = wav_file.getnframes()
                    sample_rate = wav_file.getframerate()
                    duration = frames / float(sample_rate)
                    channels = wav_file.getnchannels()
                    
                    print(f"STROKE DEBUG: Audio duration: {duration:.2f}s, channels: {channels}, sample_rate: {sample_rate}")
                    
                    if duration < 10.0:  # Increased minimum for stroke patients
                        return False, f"Audio too short ({duration:.1f}s) - stroke patients need at least 15-30 seconds for good cloning"
                    
                    if duration > 300:  # More than 5 minutes
                        print(f"STROKE WARNING: Audio very long ({duration:.1f}s) - may take time to process")
                    
                    # Additional checks for stroke speech
                    if sample_rate < 16000:
                        return False, f"Sample rate too low ({sample_rate}Hz) - need at least 16kHz for clear voice cloning"
                    
                    return True, f"Audio quality acceptable: {duration:.1f}s at {sample_rate}Hz"
                    
            except wave.Error:
                # If not a valid WAV, still might work
                print("STROKE WARNING: Could not parse as WAV, but will attempt processing")
                return True, "Audio format unknown but will attempt cloning"
                
        except Exception as e:
            print(f"STROKE ERROR: Audio assessment failed: {e}")
            return False, f"Audio assessment failed: {e}"
    
    def detect_language(self, text: str) -> str:
        """Detect the language of the input text"""
        try:
            # Simple language detection based on character patterns
            import re
            
            # Check for common language patterns
            if re.search(r'[අ-ෆ]', text):  # Sinhala
                return "Sinhala"
            elif re.search(r'[ग-ॿ]', text):  # Nepali (Devanagari script)
                # Try to distinguish Nepali from Hindi by common words
                if any(word in text for word in ['छ', 'छु', 'छन्', 'हुन्छ', 'गर्छ', 'भन्छ', 'आउँछ']):
                    return "Nepali"
                elif any(word in text for word in ['है', 'हैं', 'करता', 'करते', 'होता', 'होते']):
                    return "Hindi"
                else:
                    return "Nepali/Hindi"  # Could be either
            elif re.search(r'[अ-ॿ]', text):  # Hindi/Devanagari (broader range)
                return "Hindi"
            elif re.search(r'[ก-๛]', text):  # Thai
                return "Thai"
            elif re.search(r'[ა-ჿ]', text):  # Georgian
                return "Georgian"
            elif re.search(r'[አ-ፚ]', text):  # Amharic
                return "Amharic"
            elif re.search(r'[ا-ي]', text):  # Arabic
                return "Arabic"
            elif re.search(r'[一-龯]', text):  # Chinese
                return "Chinese"
            elif re.search(r'[ひらがなカタカナ]|[一-龯]', text):  # Japanese
                return "Japanese"
            elif re.search(r'[가-힣]', text):  # Korean
                return "Korean"
            elif re.search(r'[а-я]', text, re.IGNORECASE):  # Russian/Cyrillic
                return "Russian"
            elif re.search(r'[α-ω]', text, re.IGNORECASE):  # Greek
                return "Greek"
            elif re.search(r'[а-щъьюя]', text, re.IGNORECASE):  # Bulgarian
                return "Bulgarian"
            elif re.search(r'[ć-ž]', text, re.IGNORECASE):  # Croatian/Serbian
                return "Croatian"
            elif re.search(r'[à-ÿ]', text, re.IGNORECASE):  # French/Spanish/etc
                # Try to distinguish between Romance languages
                if any(word in text.lower() for word in ['que', 'de', 'la', 'el', 'en', 'es', 'para']):
                    return "Spanish"
                elif any(word in text.lower() for word in ['que', 'de', 'le', 'la', 'et', 'en', 'pour']):
                    return "French"
                elif any(word in text.lower() for word in ['che', 'di', 'la', 'il', 'e', 'in', 'per']):
                    return "Italian"
                else:
                    return "Romance Language"
            elif re.search(r'[a-zA-Z]', text):  # English or other Latin script
                return "English"
            else:
                return "Unknown"
                
        except Exception as e:
            print(f"Language detection failed: {e}")
            return "Unknown"

    def enhance_text_for_stroke_patients(self, text: str) -> str:
        """Enhanced text processing specifically for stroke speech patterns - MULTILINGUAL"""
        try:
            # First detect the language
            detected_language = self.detect_language(text)
            print(f"STROKE DEBUG: Detected language: {detected_language}")
            
            # Check if the text looks like garbled/repeated characters (common transcription error)
            if len(set(text.replace(' ', ''))) <= 3 and len(text) > 10:
                print("STROKE WARNING: Text appears to be garbled transcription, returning as-is")
                return text
            
            # SAFETY CHECK: If text is clearly English, force English processing
            english_words = ['the', 'and', 'is', 'to', 'of', 'a', 'in', 'that', 'have', 'for', 'not', 'with', 'he', 'as', 'you', 'do', 'at', 'this', 'but', 'his', 'by', 'from', 'they', 'we', 'say', 'her', 'she', 'or', 'an', 'will', 'my', 'one', 'all', 'would', 'there', 'their', 'what', 'so', 'up', 'out', 'if', 'about', 'who', 'get', 'which', 'go', 'me', 'when', 'make', 'can', 'like', 'time', 'no', 'just', 'him', 'know', 'take', 'people', 'into', 'year', 'your', 'good', 'some', 'could', 'them', 'see', 'other', 'than', 'then', 'now', 'look', 'only', 'come', 'its', 'over', 'think', 'also', 'back', 'after', 'use', 'two', 'how', 'our', 'work', 'first', 'well', 'way', 'even', 'new', 'want', 'because', 'any', 'these', 'give', 'day', 'most', 'us', 'hello', 'tried', 'called', 'speech', 'works', 'thing', 'stroke', 'fix', 'slurred']
            
            text_lower = text.lower()
            english_word_count = sum(1 for word in english_words if word in text_lower)
            total_words = len(text.split())
            
            if english_word_count >= 3 or (total_words > 0 and english_word_count / total_words > 0.3):
                detected_language = "English"
                print(f"STROKE OVERRIDE: Text contains English words, forcing English processing")
            
            # More conservative approach - only enhance if we're confident about the language
            if detected_language == "English":
                system_prompt = "You are helping a stroke patient communicate more clearly in English. ONLY fix unclear or garbled words. DO NOT translate to any other language. Keep everything else exactly the same."
                user_prompt = f"""Fix ONLY unclear or garbled words in this English speech from a stroke patient. Keep the EXACT same meaning, style, and language. DO NOT translate or change the language:

Original English: "{text}"

Fixed English (same language):"""
                
            elif detected_language == "Sinhala":
                system_prompt = "You are helping a stroke patient communicate more clearly in Sinhala. Fix unclear words while keeping the same meaning and natural style. DO NOT translate to any other language."
                user_prompt = f"""සිංහල භාෂාවෙන් කතා කරන ආ​ඝාත රෝගියෙකුට පැහැදිලිව සන්නිවේදනය කිරීමට උදව් කරන්න. අර්ථය සහ ස්වාභාවික විලාසය එසේම තබා ගෙන අපැහැදිලි වචන නිවැරදි කරන්න. වෙනත් භාෂාවකට පරිවර්තනය නොකරන්න:

මුල් කථනය: "{text}"

නිවැරදි කළ සිංහල:"""

            elif detected_language == "Nepali" or detected_language == "Nepali/Hindi":
                system_prompt = "You are helping a stroke patient communicate more clearly in Nepali. Fix unclear words while keeping the same meaning and natural style. DO NOT translate to any other language."
                user_prompt = f"""नेपाली भाषामा स्ट्रोकका बिरामीलाई स्पष्ट रूपमा सञ्चार गर्न मद्दत गर्नुहोस्। अर्थ र प्राकृतिक शैली उस्तै राखेर अस्पष्ट शब्दहरू सुधार गर्नुहोस्। अन्य भाषामा अनुवाद नगर्नुहोस्:

मूल भाषण: "{text}"

सुधारिएको नेपाली:"""

            elif detected_language in ["Hindi", "Devanagari"]:
                system_prompt = "You are helping a stroke patient communicate more clearly in Hindi. Fix unclear words while keeping the same meaning and natural style. DO NOT translate to any other language."
                user_prompt = f"""स्ट्रोक के मरीज़ को हिंदी में स्पष्ट रूप से संवाद करने में मदद करें। अर्थ और प्राकृतिक शैली को बनाए रखते हुए अस्पष्ट शब्दों को ठीक करें। किसी अन्य भाषा में अनुवाद न करें:

मूल भाषण: "{text}"

सुधारा गया हिंदी:"""

            else:
                # For any other language or uncertain cases, be VERY conservative
                print(f"STROKE WARNING: Uncertain language detection ({detected_language}), minimal processing")
                
                system_prompt = "You are helping a stroke patient. ONLY fix obvious transcription errors like repeated characters or garbled text. DO NOT translate to any other language. DO NOT change the meaning or style. If the text seems fine, return it unchanged."
                user_prompt = f"""ONLY fix obvious transcription errors in this text. DO NOT translate to any other language. DO NOT change the meaning. If it looks fine, return it exactly as is:

Original: "{text}"

Fixed (same language):"""
            
            # Make the API call with extra safety
            response = openai.ChatCompletion.create(
                model="gpt-3.5-turbo",
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt}
                ],
                max_tokens=150,
                temperature=0.0,  # Zero temperature for more predictable results
                top_p=1,
                frequency_penalty=0,
                presence_penalty=0
            )
            
            enhanced_text = response.choices[0].message.content.strip()
            
            # Remove any quotes that AI might add
            if enhanced_text.startswith('"') and enhanced_text.endswith('"'):
                enhanced_text = enhanced_text[1:-1]
            if enhanced_text.startswith("'") and enhanced_text.endswith("'"):
                enhanced_text = enhanced_text[1:-1]
            
            # STRICT VALIDATION - check if AI translated
            if detected_language == "English":
                # Check if response is still in English
                english_response_count = sum(1 for word in english_words if word.lower() in enhanced_text.lower())
                if english_response_count < 2 and len(enhanced_text.split()) > 3:
                    print(f"STROKE ERROR: AI translated English to another language! Returning original.")
                    return text
            
            # Check for dramatic length changes (sign of translation)
            if len(enhanced_text) > len(text) * 2 or len(enhanced_text) < len(text) * 0.4:
                print(f"STROKE WARNING: Enhanced text length very different ({len(text)} -> {len(enhanced_text)}), returning original")
                return text
            
            # Check if completely different character sets (translation)
            original_chars = set(text.replace(' ', '').lower())
            enhanced_chars = set(enhanced_text.replace(' ', '').lower())
            
            if len(original_chars & enhanced_chars) == 0 and len(original_chars) > 5:
                print(f"STROKE ERROR: AI changed character set completely (translation), returning original")
                return text
                
            print(f"STROKE SUCCESS ({detected_language}): Enhanced '{text}' to '{enhanced_text}'")
            return enhanced_text
            
        except Exception as e:
            print(f"STROKE ERROR: Multilingual text enhancement failed: {str(e)}")
            return text
    
    def clone_voice_with_enhancement(self, name: str, audio_file_path: str) -> str:
        """Enhanced voice cloning specifically optimized for stroke patients"""
        try:
            print(f"STROKE DEBUG: Starting enhanced voice clone for '{name}'")
            print(f"STROKE DEBUG: File path: {audio_file_path}")
            
            url = f"{self.elevenlabs_base_url}/voices/add"
            headers = {"xi-api-key": ELEVENLABS_API_KEY}
            
            # Prepare the request with stroke-specific enhancements
            with open(audio_file_path, "rb") as audio_file:
                files = {
                    "files": (f"{name}_stroke_voice.wav", audio_file, "audio/wav")
                }
                data = {
                    "name": f"Stroke_{name}_{int(time.time())}",  # Unique naming
                    "description": f"Stroke patient voice clone for {name} - enhanced for clarity",
                    # Enhanced settings for stroke speech
                    "remove_background_noise": "true",
                    "enhance_audio_quality": "true",
                    "optimize_streaming_latency": "0",  # Prioritize quality over speed
                    "voice_settings": {
                        "stability": 0.6,  # Higher stability for stroke speech
                        "similarity_boost": 0.9,  # Max similarity
                        "style": 0.3,  # Lower style to avoid artifacts
                        "use_speaker_boost": True
                    }
                }
                
                print(f"STROKE DEBUG: Sending enhanced clone request to ElevenLabs...")
                response = requests.post(url, headers=headers, files=files, data=data, timeout=180)  # Longer timeout
            
            print(f"STROKE DEBUG: Clone response status: {response.status_code}")
            
            if response.status_code == 200:
                result = response.json()
                print(f"STROKE DEBUG: Clone success response: {result}")
                voice_id = result.get("voice_id")
                if voice_id:
                    print(f"STROKE SUCCESS: Voice cloned with ID: {voice_id}")
                    return voice_id
                else:
                    raise Exception("No voice_id in successful response")
                    
            elif response.status_code == 422:
                # For stroke patients, provide more specific guidance
                try:
                    error_detail = response.json()
                    print(f"STROKE DEBUG: Validation error details: {error_detail}")
                    raise Exception("Speech not clear enough for cloning - this is common with stroke speech. Try recording in a very quiet room, speak slowly and clearly, or use the practice mode first.")
                except json.JSONDecodeError:
                    raise Exception("Audio quality insufficient for voice cloning - try recording 20-30 seconds of your clearest speech")
                    
            elif response.status_code == 400:
                # Check if it's the voice limit error
                try:
                    error_detail = response.json()
                    if "voice_limit_reached" in str(error_detail):
                        raise Exception("Voice limit reached - the app will use a similar-sounding voice instead")
                    else:
                        raise Exception(f"Voice cloning failed: {error_detail}")
                except json.JSONDecodeError:
                    raise Exception("Voice cloning request failed - will use backup voice")
                    
            elif response.status_code == 401:
                raise Exception("Voice cloning service temporarily unavailable")
                
            elif response.status_code == 429:
                raise Exception("Too many voice cloning requests - please wait a moment and try again")
                
            else:
                print(f"STROKE DEBUG: Unexpected error response: {response.text}")
                raise Exception(f"Voice cloning failed with error {response.status_code} - will use backup voice")
                
        except requests.exceptions.Timeout:
            raise Exception("Voice cloning timed out - audio may be too long or service busy")
        except requests.exceptions.ConnectionError:
            raise Exception("Cannot connect to voice cloning service - check internet connection")
        except Exception as e:
            print(f"STROKE ERROR: Voice cloning failed: {str(e)}")
            raise Exception(str(e))
    
    def select_best_fallback_voice(self, original_text):
        """Select the most appropriate fallback voice based on speech patterns"""
        # Simple heuristics to choose appropriate voice
        text_lower = original_text.lower()
        
        # Try to detect age/gender from speech patterns (very basic)
        if any(word in text_lower for word in ['son', 'daughter', 'grandchildren', 'retirement']):
            # Likely older person
            if any(word in text_lower for word in ['she', 'her', 'mom', 'wife', 'sister']):
                return self.fallback_voices["mature_female"]
            else:
                return self.fallback_voices["mature_male"]
        else:
            # Default to mature voices for stroke patients (typically older)
            return self.fallback_voices["mature_male"]
    
    def transcribe_audio_fast(self, audio_file_path: str) -> str:
        """REAL OpenAI Whisper transcription optimized for stroke speech"""
        try:
            with open(audio_file_path, "rb") as audio_file:
                # Enhanced settings for stroke speech recognition
                result = openai.Audio.transcribe(
                    model="whisper-1",
                    file=audio_file,
                    response_format="text",
                    temperature=0.2,  # Slightly higher for unclear speech
                    prompt="This is speech from a stroke patient that may be slurred or unclear. Please transcribe as accurately as possible."
                )
            
            if isinstance(result, dict):
                return result.get("text", str(result))
            return str(result)
            
        except Exception as e:
            raise Exception(f"Speech recognition failed: {str(e)}")
    
    def generate_speech_fast(self, text: str, voice_id: str = None) -> bytes:
        """REAL ElevenLabs speech generation optimized for clarity"""
        try:
            if not voice_id:
                voice_id = self.fallback_voices["mature_male"]
            
            print(f"STROKE DEBUG: Generating clear speech with voice ID: {voice_id}")
            
            url = f"{self.elevenlabs_base_url}/text-to-speech/{voice_id}"
            
            headers = {
                "Accept": "audio/mpeg",
                "Content-Type": "application/json",
                "xi-api-key": ELEVENLABS_API_KEY
            }
            
            # Optimized settings for stroke patients (prioritize clarity)
            data = {
                "text": text,
                "model_id": "eleven_multilingual_v2",
                "voice_settings": {
                    "stability": 0.7,  # Higher stability for clarity
                    "similarity_boost": 0.8,
                    "style": 0.4,  # Lower style to avoid artifacts
                    "use_speaker_boost": True
                },
                "pronunciation_dictionary_locators": [],
                "seed": None,
                "previous_text": None,
                "next_text": None,
                "previous_request_ids": [],
                "next_request_ids": []
            }
            
            response = requests.post(url, json=data, headers=headers, timeout=20)
            
            if response.status_code == 200:
                print(f"STROKE SUCCESS: Generated clear speech for stroke patient")
                return response.content
            else:
                print(f"STROKE ERROR: Speech generation failed: {response.status_code} - {response.text}")
                raise Exception(f"Speech generation failed: {response.status_code}")
                        
        except Exception as e:
            print(f"STROKE ERROR: Speech generation failed: {str(e)}")
            raise Exception(f"Speech generation failed: {str(e)}")
    
    def delete_voice(self, voice_id: str) -> bool:
        """Delete a cloned voice from ElevenLabs"""
        try:
            url = f"{self.elevenlabs_base_url}/voices/{voice_id}"
            headers = {"xi-api-key": ELEVENLABS_API_KEY}
            
            response = requests.delete(url, headers=headers, timeout=30)
            
            if response.status_code == 200:
                print(f"STROKE DEBUG: Voice {voice_id} deleted successfully")
                return True
            elif response.status_code == 422:
                print(f"STROKE DEBUG: Voice {voice_id} not found or already deleted")
                return True  # Consider this success since voice is gone
            else:
                print(f"STROKE WARNING: Failed to delete voice {voice_id}: {response.status_code}")
                return False
        except Exception as e:
            print(f"STROKE WARNING: Error deleting voice {voice_id}: {e}")
            return False

# Initialize stroke-optimized speech processor
speech_processor = StrokeOptimizedSpeechProcessor()

@app.route('/api/create-voice-profile', methods=['POST'])
def create_voice_profile():
    """Create a permanent voice profile for stroke patients"""
    try:
        # Check if file was uploaded
        if 'audio' not in request.files:
            return jsonify({"error": "No audio file provided"}), 400
        
        audio_file = request.files['audio']
        name = request.form.get('name', 'StrokePatient')
        
        if audio_file.filename == '':
            return jsonify({"error": "No file selected"}), 400
        
        # Save uploaded audio
        with tempfile.NamedTemporaryFile(delete=False, suffix=".wav") as temp_file:
            audio_file.save(temp_file.name)
            temp_audio_path = temp_file.name
        
        try:
            # Enhanced voice cloning for stroke patients
            voice_id = speech_processor.clone_voice_with_enhancement(name, temp_audio_path)
            
            return jsonify({
                "success": True,
                "voice_id": voice_id,
                "message": f"Voice profile '{name}' created successfully! This voice will sound clear and natural.",
                "recommendation": "Save this voice ID for future use. You can now speak naturally and the app will respond in your clear voice."
            })
            
        finally:
            # Clean up
            try:
                os.unlink(temp_audio_path)
            except:
                pass
                
    except Exception as e:
        return jsonify({
            "error": str(e),
            "recommendation": "For best results, record 20-30 seconds in a very quiet room, speaking as clearly as possible."
        }), 500

@app.route('/api/process-speech-fast', methods=['POST'])
def process_speech_fast():
    """STROKE-OPTIMIZED speech processing with enhanced clarity"""
    start_time = time.time()
    cloned_voice_id = None
    
    try:
        # Check if file was uploaded
        if 'audio' not in request.files:
            return jsonify({"error": "No audio file provided"}), 400
        
        audio_file = request.files['audio']
        voice_id = request.form.get('voice_id')
        auto_clone = request.form.get('auto_clone', 'true').lower() == 'true'
        
        if audio_file.filename == '':
            return jsonify({"error": "No file selected"}), 400
        
        # Save uploaded audio
        temp_audio_path = None
        try:
            with tempfile.NamedTemporaryFile(delete=False, suffix=".wav", prefix="stroke_voice_") as temp_file:
                audio_file.save(temp_file.name)
                temp_audio_path = temp_file.name
                
            print(f"STROKE DEBUG: Processing speech file: {temp_audio_path}")
            print(f"STROKE DEBUG: File size: {os.path.getsize(temp_audio_path)} bytes")
            
            # Step 1: Enhanced transcription for stroke speech
            transcribe_start = time.time()
            original_text = speech_processor.transcribe_audio_fast(temp_audio_path)
            transcribe_time = time.time() - transcribe_start
            
            print(f"STROKE DEBUG: Transcribed: '{original_text}' in {transcribe_time:.2f}s")
            
            # Step 2: Smart voice cloning strategy
            clone_time = 0
            auto_cloned = False
            clone_error = None
            
            if not voice_id and auto_clone:
                # Assess if speech is clear enough for cloning
                can_clone, assessment_message = speech_processor.assess_speech_clarity(temp_audio_path)
                print(f"STROKE DEBUG: Speech assessment: {assessment_message}")
                
                if can_clone:
                    try:
                        clone_start = time.time()
                        print("STROKE DEBUG: Attempting enhanced voice clone...")
                        
                        cloned_voice_id = speech_processor.clone_voice_with_enhancement("AutoStroke", temp_audio_path)
                        voice_id = cloned_voice_id
                        
                        clone_time = time.time() - clone_start
                        auto_cloned = True
                        print(f"STROKE SUCCESS: Voice cloned successfully in {clone_time:.2f}s")
                        
                    except Exception as e:
                        clone_error = str(e)
                        print(f"STROKE WARNING: Auto-cloning failed: {clone_error}")
                        # Select best fallback voice
                        voice_id = speech_processor.select_best_fallback_voice(original_text)
                        auto_cloned = False
                        print(f"STROKE FALLBACK: Using optimized voice: {voice_id}")
                else:
                    clone_error = f"Speech clarity insufficient: {assessment_message}"
                    voice_id = speech_processor.select_best_fallback_voice(original_text)
                    print(f"STROKE FALLBACK: Using optimized voice due to clarity: {voice_id}")
            
            # Step 3: Enhanced text processing for stroke patients
            process_start = time.time()
            enhanced_text = speech_processor.enhance_text_for_stroke_patients(original_text)
            
            # Generate clear speech
            try:
                audio_data = speech_processor.generate_speech_fast(enhanced_text, voice_id)
                speech_generation_success = True
                print(f"STROKE SUCCESS: Generated clear speech response")
            except Exception as e:
                print(f"STROKE WARNING: Speech generation failed: {e}")
                # Ultimate fallback
                audio_data = speech_processor.generate_speech_fast(enhanced_text, speech_processor.fallback_voices["mature_male"])
                speech_generation_success = False
                clone_error = f"Used backup voice due to generation error: {e}"
            
            process_time = time.time() - process_start
            total_time = time.time() - start_time
            
            response_data = {
                "success": True,
                "original_text": original_text,
                "enhanced_text": enhanced_text,
                "audio_base64": audio_data.hex(),
                "timing": {
                    "transcription": round(transcribe_time, 2),
                    "voice_cloning": round(clone_time, 2),
                    "processing": round(process_time, 2),
                    "total": round(total_time, 2)
                },
                "voice_used": voice_id or "default",
                "auto_cloned": auto_cloned,
                "speech_generation_success": speech_generation_success,
                "stroke_optimized": True,
                "clarity_enhanced": enhanced_text != original_text,
                "detected_language": getattr(speech_processor, 'detected_language', 'unknown'),
                "language_supported": speech_processor.is_language_well_supported(getattr(speech_processor, 'detected_language', 'en')),
                "model_used": speech_processor.get_best_model_for_language(getattr(speech_processor, 'detected_language', 'en'))
            }
            
            # Add helpful information for stroke patients
            if clone_error:
                response_data["voice_info"] = clone_error
            elif auto_cloned:
                response_data["voice_info"] = "Successfully used your cloned voice for clear speech"
            else:
                response_data["voice_info"] = "Used optimized voice for maximum clarity"
                
            return jsonify(response_data)
            
        finally:
            # Clean up temp file
            if temp_audio_path and os.path.exists(temp_audio_path):
                try:
                    os.unlink(temp_audio_path)
                    print(f"STROKE DEBUG: Cleaned up temp file")
                except Exception as e:
                    print(f"STROKE WARNING: Could not delete temp file: {e}")
            
            # Immediately delete temporary cloned voice
            if cloned_voice_id:
                try:
                    speech_processor.delete_voice(cloned_voice_id)
                    print(f"STROKE DEBUG: Deleted temporary voice clone")
                except Exception as e:
                    print(f"STROKE WARNING: Could not delete temporary voice: {e}")
                    
    except Exception as e:
        error_msg = str(e)
        print(f"STROKE ERROR: Speech processing failed: {error_msg}")
        
        # Clean up on error
        if cloned_voice_id:
            try:
                speech_processor.delete_voice(cloned_voice_id)
            except:
                pass
                
        return jsonify({
            "error": error_msg,
            "success": False,
            "stroke_optimized": True,
            "recommendation": "Try speaking more slowly and clearly, or record in a quieter environment."
        }), 500

@app.route('/api/test-voice-clone', methods=['POST'])
def test_voice_clone():
    """Test voice cloning functionality for stroke patients"""
    try:
        if 'audio' not in request.files:
            return jsonify({"error": "No audio file provided"}), 400
        
        audio_file = request.files['audio']
        test_name = request.form.get('name', 'StrokeTest')
        
        with tempfile.NamedTemporaryFile(delete=False, suffix=".wav") as temp_file:
            audio_file.save(temp_file.name)
            temp_path = temp_file.name
        
        try:
            # Test speech clarity assessment
            can_clone, assessment = speech_processor.assess_speech_clarity(temp_path)
            
            if can_clone:
                # Test cloning
                voice_id = speech_processor.clone_voice_with_enhancement(test_name, temp_path)
                
                return jsonify({
                    "success": True,
                    "voice_id": voice_id,
                    "assessment": assessment,
                    "message": "Voice cloning successful! Your speech is clear enough for cloning.",
                    "recommendation": "You can use auto-cloning for the best results."
                })
            else:
                return jsonify({
                    "success": False,
                    "assessment": assessment,
                    "message": "Voice cloning not recommended with current audio quality.",
                    "recommendation": "Try recording 20-30 seconds in a very quiet room, speaking slowly and clearly. The app will still work with optimized backup voices."
                })
            
        finally:
            os.unlink(temp_path)
            
    except Exception as e:
        return jsonify({
            "error": str(e), 
            "success": False,
            "recommendation": "For best results with stroke speech, record in a quiet environment and speak as clearly as possible."
        }), 500

@app.route('/api/voices', methods=['GET'])
def get_voices():
    """Get available voices including stroke-optimized options"""
    try:
        response = requests.get(
            f"{speech_processor.elevenlabs_base_url}/voices",
            headers={"xi-api-key": ELEVENLABS_API_KEY}
        )

        if response.status_code == 200:
            data = response.json()
            voices = []
            
            # Add user's cloned voices
            for voice in data["voices"]:
                voices.append({
                    "voice_id": voice["voice_id"],
                    "name": voice["name"],
                    "category": voice.get("category", "cloned"),
                    "stroke_optimized": "Stroke" in voice["name"]
                })
            
            # Add fallback voices with descriptions
            voices.extend([
                {
                    "voice_id": speech_processor.fallback_voices["mature_male"],
                    "name": "Mature Male (Optimized)",
                    "category": "stroke_fallback",
                    "stroke_optimized": True
                },
                {
                    "voice_id": speech_processor.fallback_voices["mature_female"],
                    "name": "Mature Female (Optimized)",
                    "category": "stroke_fallback",
                    "stroke_optimized": True
                }
            ])
            
            return jsonify({
                "success": True,
                "voices": voices,
                "stroke_info": "Stroke-optimized voices prioritize clarity and natural speech patterns"
            })
        else:
            return jsonify({
                "success": False,
                "error": f"API error: {response.status_code}",
                "voices": []
            })
    except Exception as e:
        return jsonify({
            "success": False,
            "error": str(e),
            "voices": []
        })

@app.route('/api/speed-test', methods=['GET'])
def speed_test():
    """Test API response times"""
    start = time.time()
    
    # Test OpenAI
    try:
        openai_start = time.time()
        openai.ChatCompletion.create(
            model="gpt-3.5-turbo",
            messages=[{"role": "user", "content": "Hi"}],
            max_tokens=1
        )
        openai_time = time.time() - openai_start
    except Exception as e:
        openai_time = f"Error: {str(e)}"
    
    # Test ElevenLabs
    try:
        el_start = time.time()
        requests.get(
            f"{speech_processor.elevenlabs_base_url}/voices",
            headers={"xi-api-key": ELEVENLABS_API_KEY}
        )
        el_time = time.time() - el_start
    except Exception as e:
        el_time = f"Error: {str(e)}"
    
    total = time.time() - start
    
    return jsonify({
        "openai_ping": openai_time,
        "elevenlabs_ping": el_time,
        "total_test_time": round(total, 2),
        "status": "Stroke-optimized APIs ready!" if isinstance(openai_time, float) and isinstance(el_time, float) else "Some APIs may be slow",
        "stroke_optimized": True
    })

@app.route('/api/delete-voice/<voice_id>', methods=['DELETE'])
def delete_voice(voice_id):
    """Delete a voice"""
    try:
        success = speech_processor.delete_voice(voice_id)
        if success:
            return jsonify({"success": True, "message": "Voice deleted successfully"})
        else:
            return jsonify({"success": False, "error": "Failed to delete voice"}), 400
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500

@app.route('/api/debug-voice-clone', methods=['POST'])
def debug_voice_clone():
    """Debug endpoint for stroke patients"""
    debug_info = []
    
    try:
        debug_info.append("🔍 Starting stroke-optimized voice clone debug...")
        
        if 'audio' not in request.files:
            return jsonify({"error": "No audio file provided", "debug": debug_info}), 400
        
        audio_file = request.files['audio']
        debug_info.append(f"✅ Audio file received: {audio_file.filename}")
        
        with tempfile.NamedTemporaryFile(delete=False, suffix=".wav") as temp_file:
            audio_file.save(temp_file.name)
            temp_path = temp_file.name
            
        file_size = os.path.getsize(temp_path)
        debug_info.append(f"📁 File saved, size: {file_size} bytes")
        
        try:
            # Test speech clarity assessment
            can_clone, assessment = speech_processor.assess_speech_clarity(temp_path)
            debug_info.append(f"🎯 Speech clarity assessment: {assessment}")
            
            if can_clone:
                debug_info.append("🎤 Attempting stroke-optimized voice clone...")
                
                url = f"{speech_processor.elevenlabs_base_url}/voices/add"
                headers = {"xi-api-key": ELEVENLABS_API_KEY}
                
                with open(temp_path, "rb") as audio_file:
                    files = {"files": ("stroke_debug.wav", audio_file, "audio/wav")}
                    data = {
                        "name": f"StrokeDebug_{int(time.time())}",
                        "description": "Stroke patient debug test",
                        "remove_background_noise": "true",
                        "enhance_audio_quality": "true"
                    }
                    
                    response = requests.post(url, headers=headers, files=files, data=data, timeout=120)
                
                debug_info.append(f"📬 Clone response: {response.status_code}")
                
                if response.status_code == 200:
                    result = response.json()
                    voice_id = result.get("voice_id")
                    debug_info.append(f"🎉 SUCCESS! Stroke voice cloned: {voice_id}")
                    
                    # Test speech generation
                    try:
                        test_audio = speech_processor.generate_speech_fast("This is a test of clear speech for stroke patients.", voice_id)
                        debug_info.append("🔊 Speech generation test: SUCCESS")
                    except Exception as e:
                        debug_info.append(f"🔊 Speech generation test failed: {str(e)}")
                    
                    # Cleanup
                    try:
                        delete_response = requests.delete(f"{speech_processor.elevenlabs_base_url}/voices/{voice_id}", headers=headers)
                        debug_info.append(f"🗑️ Cleanup: {delete_response.status_code}")
                    except:
                        debug_info.append("🗑️ Cleanup failed")
                        
                    return jsonify({
                        "success": True,
                        "message": "Stroke-optimized voice cloning works!",
                        "voice_id": voice_id,
                        "debug": debug_info,
                        "stroke_optimized": True
                    })
                else:
                    debug_info.append(f"❌ Clone failed: {response.status_code}")
                    try:
                        error_detail = response.json()
                        debug_info.append(f"📄 Error details: {error_detail}")
                    except:
                        debug_info.append(f"📄 Error text: {response.text[:300]}")
                        
                    return jsonify({
                        "success": False,
                        "error": f"Clone failed: {response.status_code}",
                        "debug": debug_info,
                        "stroke_optimized": True,
                        "recommendation": "Try recording longer (20-30 seconds) in a very quiet room"
                    })
            else:
                debug_info.append("❌ Speech not suitable for cloning")
                debug_info.append(f"💡 Recommendation: {assessment}")
                
                return jsonify({
                    "success": False,
                    "error": "Speech clarity insufficient",
                    "debug": debug_info,
                    "stroke_optimized": True,
                    "recommendation": "Record 20-30 seconds of your clearest speech in a quiet room"
                })
                
        finally:
            try:
                os.unlink(temp_path)
                debug_info.append("🧹 Temp file cleaned")
            except:
                debug_info.append("🧹 Cleanup failed")
                
    except Exception as e:
        debug_info.append(f"💥 ERROR: {str(e)}")
        return jsonify({
            "success": False,
            "error": str(e),
            "debug": debug_info,
            "stroke_optimized": True
        }), 500
    
@app.route('/api/quick-test', methods=['GET'])
def quick_test():
    try:
        response = requests.get(
            f"{speech_processor.elevenlabs_base_url}/voices",
            headers={"xi-api-key": ELEVENLABS_API_KEY}
        )
        return jsonify({
            "api_key_works": response.status_code == 200,
            "status_code": response.status_code,
            "error": response.text if response.status_code != 200 else None,
            "stroke_optimized": True
        })
    except Exception as e:
        return jsonify({"error": str(e), "stroke_optimized": True})

@app.route('/api/cleanup-voices', methods=['POST'])
def cleanup_voices():
    """Delete all custom voices to free up slots"""
    try:
        response = requests.get(
            f"{speech_processor.elevenlabs_base_url}/voices",
            headers={"xi-api-key": ELEVENLABS_API_KEY}
        )
        
        if response.status_code != 200:
            return jsonify({"error": "Failed to get voices"}), 400
            
        voices = response.json().get("voices", [])
        deleted = []
        
        for voice in voices:
            if voice.get("category") == "cloned":
                try:
                    delete_response = requests.delete(
                        f"{speech_processor.elevenlabs_base_url}/voices/{voice['voice_id']}",
                        headers={"xi-api-key": ELEVENLABS_API_KEY}
                    )
                    if delete_response.status_code in [200, 422]:
                        deleted.append(voice["name"])
                except:
                    pass
        
        return jsonify({
            "success": True,
            "deleted_voices": deleted,
            "message": f"Deleted {len(deleted)} custom voices",
            "stroke_optimized": True
        })
        
    except Exception as e:
        return jsonify({"error": str(e), "stroke_optimized": True}), 500

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 8000))
    app.run(host='0.0.0.0', port=port, debug=True)