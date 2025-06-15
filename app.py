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
# IMPROVED SPEECH FUNCTIONALITY - ALL REAL APIs WITH FIXED VOICE CLONING
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
    
    def validate_audio_for_cloning(self, file_path):
        """Validate audio file is suitable for voice cloning"""
        try:
            import wave
            import audioop
            
            file_size = os.path.getsize(file_path)
            print(f"DEBUG: Audio file size: {file_size} bytes")
            
            # Basic file size checks
            if file_size == 0:
                raise Exception("Audio file is empty")
            if file_size > 25 * 1024 * 1024:  # 25MB limit
                raise Exception("Audio file too large (max 25MB)")
            if file_size < 10000:  # Less than 10KB is probably too short
                raise Exception("Audio file too small - need at least 10-30 seconds of clear speech")
            
            # Try to read as WAV and get duration
            try:
                with wave.open(file_path, 'rb') as wav_file:
                    frames = wav_file.getnframes()
                    sample_rate = wav_file.getframerate()
                    duration = frames / float(sample_rate)
                    channels = wav_file.getnchannels()
                    
                    print(f"DEBUG: Audio duration: {duration:.2f}s, channels: {channels}, sample_rate: {sample_rate}")
                    
                    if duration < 5.0:  # Less than 5 seconds
                        raise Exception(f"Audio too short ({duration:.1f}s) - need at least 10-30 seconds for good cloning")
                    
                    if duration > 300:  # More than 5 minutes
                        print(f"WARNING: Audio very long ({duration:.1f}s) - this may take time to process")
                    
                    return True, duration
                    
            except wave.Error:
                # If not a valid WAV, still try to process
                print("WARNING: Could not parse as WAV, but will attempt cloning anyway")
                return True, None
                
        except Exception as e:
            print(f"Audio validation failed: {e}")
            raise Exception(f"Audio validation failed: {e}")
        
    def transcribe_audio_fast(self, audio_file_path: str) -> str:
        """REAL OpenAI Whisper transcription with auto language detection"""
        try:
            with open(audio_file_path, "rb") as audio_file:
                result = openai.Audio.transcribe(
                    model="whisper-1",
                    file=audio_file,
                    # language="en",  # REMOVE THIS LINE TO AUTO-DETECT
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
                    "stability": 0.4,
                    "similarity_boost": 0.85,
                    "style": 0.6,
                    "use_speaker_boost": True
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
        """IMPROVED voice cloning with better error handling"""
        try:
            # Validate audio first
            self.validate_audio_for_cloning(audio_file_path)
            
            print(f"DEBUG: Starting voice clone for '{name}'")
            print(f"DEBUG: File path: {audio_file_path}")
            
            url = f"{self.elevenlabs_base_url}/voices/add"
            headers = {"xi-api-key": ELEVENLABS_API_KEY}
            
            # Prepare the request
            with open(audio_file_path, "rb") as audio_file:
                files = {
                    "files": (f"{name}_voice.wav", audio_file, "audio/wav")
                }
                data = {
                    "name": f"{name}_{int(time.time())}",  # Make name unique
                    "description": f"Auto-cloned voice for {name}",
                    "remove_background_noise": "true",
                    "enhance_audio_quality": "true"  # Try to improve quality
                }
                
                print(f"DEBUG: Sending clone request to ElevenLabs...")
                response = requests.post(url, headers=headers, files=files, data=data, timeout=120)
            
            print(f"DEBUG: Clone response status: {response.status_code}")
            print(f"DEBUG: Clone response headers: {dict(response.headers)}")
            
            if response.status_code == 200:
                result = response.json()
                print(f"DEBUG: Clone success response: {result}")
                voice_id = result.get("voice_id")
                if voice_id:
                    print(f"SUCCESS: Voice cloned with ID: {voice_id}")
                    return voice_id
                else:
                    raise Exception("No voice_id in successful response")
                    
            elif response.status_code == 422:
                # Validation error - get details
                try:
                    error_detail = response.json()
                    print(f"DEBUG: Validation error details: {error_detail}")
                    error_msg = error_detail.get("detail", {})
                    if isinstance(error_msg, list) and len(error_msg) > 0:
                        specific_error = error_msg[0].get("msg", "Audio quality insufficient")
                        raise Exception(f"Audio not suitable for cloning: {specific_error}")
                    else:
                        raise Exception("Audio quality insufficient for cloning - try recording 10-30 seconds of clear speech")
                except json.JSONDecodeError:
                    raise Exception("Audio validation failed - may need longer or clearer recording")
                    
            elif response.status_code == 401:
                raise Exception("ElevenLabs API key invalid or expired")
                
            elif response.status_code == 429:
                raise Exception("ElevenLabs rate limit exceeded - please wait and try again")
                
            else:
                print(f"DEBUG: Unexpected error response: {response.text}")
                raise Exception(f"ElevenLabs API error {response.status_code}: {response.text[:200]}")
                
        except requests.exceptions.Timeout:
            raise Exception("Voice cloning timed out - audio may be too long or server busy")
        except requests.exceptions.ConnectionError:
            raise Exception("Cannot connect to ElevenLabs - check internet connection")
        except Exception as e:
            print(f"Voice cloning error: {str(e)}")
            raise Exception(f"Voice cloning failed: {str(e)}")
    
    def delete_voice(self, voice_id: str) -> bool:
        """Delete a cloned voice from ElevenLabs"""
        try:
            url = f"{self.elevenlabs_base_url}/voices/{voice_id}"
            headers = {"xi-api-key": ELEVENLABS_API_KEY}
            
            response = requests.delete(url, headers=headers, timeout=30)
            
            if response.status_code == 200:
                print(f"Voice {voice_id} deleted successfully")
                return True
            elif response.status_code == 422:
                print(f"Voice {voice_id} not found or already deleted")
                return True  # Consider this success since voice is gone
            else:
                print(f"Failed to delete voice {voice_id}: {response.status_code} - {response.text}")
                return False
        except Exception as e:
            print(f"Error deleting voice {voice_id}: {e}")
            return False

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
    """IMPROVED speech processing with better auto-cloning"""
    start_time = time.time()
    cloned_voice_id = None  # Track if we need to clean up
    
    try:
        # Check if file was uploaded
        if 'audio' not in request.files:
            return jsonify({"error": "No audio file provided"}), 400
        
        audio_file = request.files['audio']
        voice_id = request.form.get('voice_id')
        auto_clone = request.form.get('auto_clone', 'true').lower() == 'true'
        
        if audio_file.filename == '':
            return jsonify({"error": "No file selected"}), 400
        
        # Save uploaded audio with better naming
        temp_audio_path = None
        try:
            # Create temp file with .wav extension
            with tempfile.NamedTemporaryFile(delete=False, suffix=".wav", prefix="user_voice_") as temp_file:
                audio_file.save(temp_file.name)
                temp_audio_path = temp_file.name
                
            print(f"DEBUG: Saved audio to: {temp_audio_path}")
            print(f"DEBUG: File size: {os.path.getsize(temp_audio_path)} bytes")
            
            # Step 1: REAL transcription
            transcribe_start = time.time()
            original_text = speech_processor.transcribe_audio_fast(temp_audio_path)
            transcribe_time = time.time() - transcribe_start
            
            print(f"DEBUG: Transcribed: '{original_text}' in {transcribe_time:.2f}s")
            
            # Step 2: Auto voice cloning if requested and no voice_id provided
            clone_time = 0
            auto_cloned = False
            clone_error = None
            
            if not voice_id and auto_clone:
                try:
                    clone_start = time.time()
                    print("DEBUG: Starting auto-clone process...")
                    
                    # Try to clone the voice
                    cloned_voice_id = speech_processor.clone_voice("AutoClone", temp_audio_path)
                    voice_id = cloned_voice_id
                    
                    clone_time = time.time() - clone_start
                    auto_cloned = True
                    print(f"SUCCESS: Auto-cloned voice {voice_id} in {clone_time:.2f}s")
                    
                except Exception as e:
                    clone_error = str(e)
                    print(f"WARNING: Auto-cloning failed: {clone_error}")
                    voice_id = None  # Use default voice
                    auto_cloned = False
            
            # Step 3: Text enhancement and speech generation
            process_start = time.time()
            enhanced_text = speech_processor.enhance_text_fast(original_text)
            
            # Generate speech with cloned or default voice
            try:
                audio_data = speech_processor.generate_speech_fast(enhanced_text, voice_id)
                speech_generation_success = True
            except Exception as e:
                print(f"WARNING: Speech generation failed with voice {voice_id}: {e}")
                # Fall back to default voice
                audio_data = speech_processor.generate_speech_fast(enhanced_text, None)
                speech_generation_success = False
                if auto_cloned:
                    clone_error = f"Cloning succeeded but speech generation failed: {e}"
            
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
                "speed_optimized": True
            }
            
            # Add clone error info if there was one
            if clone_error:
                response_data["clone_warning"] = clone_error
                
            return jsonify(response_data)
            
        finally:
            # Clean up temp file
            if temp_audio_path and os.path.exists(temp_audio_path):
                try:
                    os.unlink(temp_audio_path)
                    print(f"DEBUG: Cleaned up temp file: {temp_audio_path}")
                except Exception as e:
                    print(f"WARNING: Could not delete temp file: {e}")
                    
    except Exception as e:
        error_msg = str(e)
        print(f"ERROR: process_speech_fast failed: {error_msg}")
        
        # Clean up any cloned voice if there was an error
        if cloned_voice_id:
            try:
                speech_processor.delete_voice(cloned_voice_id)
                print(f"DEBUG: Cleaned up failed voice clone: {cloned_voice_id}")
            except:
                pass
                
        return jsonify({
            "error": error_msg,
            "success": False,
            "debug_info": {
                "auto_clone_attempted": auto_clone,
                "voice_id_provided": bool(voice_id)
            }
        }), 500

@app.route('/api/test-voice-clone', methods=['POST'])
def test_voice_clone():
    """Test voice cloning functionality separately"""
    try:
        if 'audio' not in request.files:
            return jsonify({"error": "No audio file provided"}), 400
        
        audio_file = request.files['audio']
        test_name = request.form.get('name', 'TestVoice')
        
        # Save temp file
        with tempfile.NamedTemporaryFile(delete=False, suffix=".wav") as temp_file:
            audio_file.save(temp_file.name)
            temp_path = temp_file.name
        
        try:
            # Test validation
            is_valid, duration = speech_processor.validate_audio_for_cloning(temp_path)
            
            # Test cloning
            voice_id = speech_processor.clone_voice(test_name, temp_path)
            
            return jsonify({
                "success": True,
                "voice_id": voice_id,
                "audio_duration": duration,
                "message": "Voice cloning test successful!"
            })
            
        finally:
            os.unlink(temp_path)
            
    except Exception as e:
        return jsonify({"error": str(e), "success": False}), 500

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

@app.route('/api/delete-voice/<voice_id>', methods=['DELETE'])
def delete_voice(voice_id):
    """Delete a temporary cloned voice"""
    try:
        success = speech_processor.delete_voice(voice_id)
        if success:
            return jsonify({"success": True, "message": "Voice deleted"})
        else:
            return jsonify({"success": False, "error": "Failed to delete voice"}), 400
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 8000))
    app.run(host='0.0.0.0', port=port, debug=True)