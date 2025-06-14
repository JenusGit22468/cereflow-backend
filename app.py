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
# SPEECH FUNCTIONALITY - ALL REAL APIs
# =============================================================================

class OptimizedSpeechProcessor:
    def __init__(self):
        self.elevenlabs_base_url = "https://api.elevenlabs.io/v1"
        self._warmup()
        
    def _warmup(self):
        """Pre-warm APIs to reduce first-request latency"""
        try:
            threading.Thread(target=self._warmup_openai, daemon=True).start()
            threading.Thread(target=self._warmup_elevenlabs, daemon=True).start()
        except:
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
        
    def transcribe_audio_fast(self, audio_file_path: str) -> str:
        """REAL OpenAI Whisper transcription"""
        try:
            with open(audio_file_path, "rb") as audio_file:
                result = openai.Audio.transcribe(
                    model="whisper-1",
                    file=audio_file,
                    response_format="text",
                    temperature=0
                )
            
            if isinstance(result, dict):
                return result.get("text", str(result))
            return str(result)
            
        except Exception as e:
            raise Exception(f"Transcription failed: {str(e)}")
    
    def enhance_text_fast(self, text: str) -> str:
        """Minimal text enhancement - preserve original language"""
        try:
            # Language-preserving prompt
            prompt = f"""Only fix unclear or garbled words in this speech. KEEP THE SAME LANGUAGE - do not translate. Keep everything else exactly the same including the original language, natural speaking style, slang, and sentence structure:

    Original: "{text}"

    Fixed (same language):"""
            
            response = openai.ChatCompletion.create(
                model="gpt-3.5-turbo",
                messages=[
                    {"role": "system", "content": "You only fix unclear/garbled words while preserving the original language. NEVER translate to a different language. Keep the person's natural speech patterns and original language."},
                    {"role": "user", "content": prompt}
                ],
                max_tokens=100,
                temperature=0,
                top_p=1,
                frequency_penalty=0,
                presence_penalty=0
            )
            
            enhanced_text = response.choices[0].message.content.strip()
            
            # Safety check - if AI changed too much, return original
            original_words = text.lower().split()
            enhanced_words = enhanced_text.lower().split()
            
            # If more than 30% of words changed, probably over-edited
            if len(enhanced_words) == 0 or len(set(original_words) & set(enhanced_words)) / len(original_words) < 0.7:
                print("AI over-edited, returning original")
                return text
                
            return enhanced_text
            
        except Exception as e:
            print(f"Enhancement error: {str(e)}")
            return text
    
    def generate_speech_fast(self, text: str, voice_id: str = None) -> bytes:
        """REAL ElevenLabs speech generation"""
        try:
            if not voice_id:
                voice_id = "29vD33N1CtxCmqQRPOHJ"
            
            print(f"Generating speech with voice ID: {voice_id}")
            
            url = f"{self.elevenlabs_base_url}/text-to-speech/{voice_id}"
            
            headers = {
                "Accept": "audio/mpeg",
                "Content-Type": "application/json",
                "xi-api-key": ELEVENLABS_API_KEY
            }
            
            data = {
                "text": text,
                "model_id": "eleven_multilingual_v2",
                "voice_settings": {
                    "stability": 0.7,
                    "similarity_boost": 0.9,
                    "style": 0.1,
                    "use_speaker_boost": False
                }
            }
            
            response = requests.post(url, json=data, headers=headers, timeout=15)
            
            if response.status_code == 200:
                return response.content
            else:
                print(f"Speech generation error: {response.status_code} - {response.text}")
                raise Exception(f"ElevenLabs API error: {response.status_code} - {response.text}")
                        
        except Exception as e:
            print(f"Speech generation failed: {str(e)}")
            raise Exception(f"Speech generation failed: {str(e)}")
    
    def clone_voice(self, name: str, audio_file_path: str) -> str:
        """REAL ElevenLabs voice cloning"""
        try:
            url = f"{self.elevenlabs_base_url}/voices/add"
            
            headers = {
                "xi-api-key": ELEVENLABS_API_KEY
            }
            
            with open(audio_file_path, "rb") as audio_file:
                files = {
                    "files": (os.path.basename(audio_file_path), audio_file, "audio/mpeg")
                }
                data = {
                    "name": name,
                    "description": f"Professional clone for {name} - preserves emotions and speaking style",
                    "remove_background_noise": "true",
                }
                
                response = requests.post(url, headers=headers, files=files, data=data, timeout=60)
            
            if response.status_code == 200:
                result = response.json()
                print(f"Voice cloned successfully: {result['voice_id']}")
                return result["voice_id"]
            else:
                print(f"Voice cloning failed: {response.status_code} - {response.text}")
                raise Exception(f"ElevenLabs clone error: {response.status_code} - {response.text}")
                
        except Exception as e:
            print(f"Voice cloning error: {str(e)}")
            raise Exception(f"Voice cloning failed: {str(e)}")

# Initialize speech processor
speech_processor = OptimizedSpeechProcessor()

@app.route('/api/create-voice-profile', methods=['POST'])
def create_voice_profile():
    """REAL voice profile creation using ElevenLabs"""
    try:
        # Check if file was uploaded
        if 'audio' not in request.files:
            return jsonify({"error": "No audio file provided"}), 400
        
        audio_file = request.files['audio']
        name = request.form.get('name', 'UnknownVoice')
        
        if audio_file.filename == '':
            return jsonify({"error": "No file selected"}), 400
        
        # Save uploaded audio
        with tempfile.NamedTemporaryFile(delete=False, suffix=".wav") as temp_file:
            audio_file.save(temp_file.name)
            temp_audio_path = temp_file.name
        
        try:
            # REAL voice cloning
            voice_id = speech_processor.clone_voice(name, temp_audio_path)
            
            return jsonify({
                "success": True,
                "voice_id": voice_id,
                "message": f"Voice profile '{name}' created successfully!"
            })
            
        finally:
            # Clean up
            try:
                os.unlink(temp_audio_path)
            except:
                pass
                
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route('/api/process-speech-fast', methods=['POST'])
def process_speech_fast():
    """REAL speech processing with all real APIs"""
    start_time = time.time()
    
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
        with tempfile.NamedTemporaryFile(delete=False, suffix=".wav") as temp_file:
            audio_file.save(temp_file.name)
            temp_audio_path = temp_file.name
        
        try:
            # Step 1: REAL transcription
            transcribe_start = time.time()
            original_text = speech_processor.transcribe_audio_fast(temp_audio_path)
            transcribe_time = time.time() - transcribe_start
            
            # Step 2: REAL auto voice cloning if needed
            clone_time = 0
            if not voice_id and auto_clone:
                try:
                    clone_start = time.time()
                    print("Auto-cloning voice from user's speech...")
                    voice_id = speech_processor.clone_voice("AutoClone", temp_audio_path)
                    clone_time = time.time() - clone_start
                    print(f"Auto-cloned voice: {voice_id} in {clone_time:.2f}s")
                except Exception as e:
                    print(f"Auto-cloning failed, using default voice: {str(e)}")
                    voice_id = None
            
            # Step 3: REAL text enhancement and speech generation
            process_start = time.time()
            enhanced_text = speech_processor.enhance_text_fast(original_text)
            audio_data = speech_processor.generate_speech_fast(enhanced_text, voice_id)
            process_time = time.time() - process_start
            
            total_time = time.time() - start_time
            
            return jsonify({
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
                "auto_cloned": voice_id is not None and auto_clone,
                "speed_optimized": True
            })
            
        finally:
            # Clean up
            try:
                os.unlink(temp_audio_path)
            except:
                pass
                
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route('/api/voices', methods=['GET'])
def get_voices():
    """Get REAL voices from ElevenLabs"""
    try:
        response = requests.get(
            f"{speech_processor.elevenlabs_base_url}/voices",
            headers={"xi-api-key": ELEVENLABS_API_KEY}
        )

        if response.status_code == 200:
            data = response.json()
            return jsonify({
                "success": True,
                "voices": [
                    {
                        "voice_id": voice["voice_id"],
                        "name": voice["name"],
                        "category": voice.get("category", "cloned")
                    }
                    for voice in data["voices"]
                ]
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
    """Test REAL API response times"""
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
        "status": "APIs are warmed up!" if isinstance(openai_time, float) and isinstance(el_time, float) else "Some APIs may be slow"
    })

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 8000))
    app.run(host='0.0.0.0', port=port, debug=True)