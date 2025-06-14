from fastapi import FastAPI, File, UploadFile, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
import openai
import os
import tempfile
import asyncio
import aiofiles
from dotenv import load_dotenv
import json
import time
import requests
from concurrent.futures import ThreadPoolExecutor
import threading

load_dotenv()

app = FastAPI(title="Ctrl+Z Speech Clarity API")

# CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Initialize APIs (OpenAI v0.28.1 style)
openai.api_key = os.getenv("OPENAI_API_KEY")
ELEVENLABS_API_KEY = os.getenv("ELEVENLABS_API_KEY")

# Thread pool for parallel processing
executor = ThreadPoolExecutor(max_workers=3)

class OptimizedSpeechProcessor:
    def __init__(self):
        self.elevenlabs_base_url = "https://api.elevenlabs.io/v1"
        # Pre-warm the models on startup
        self._warmup()
        
    def _warmup(self):
        """Pre-warm APIs to reduce first-request latency"""
        try:
            # Warm up OpenAI
            threading.Thread(target=self._warmup_openai, daemon=True).start()
            # Warm up ElevenLabs
            threading.Thread(target=self._warmup_elevenlabs, daemon=True).start()
        except:
            pass  # Fail silently if warmup fails
    
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
        
    async def transcribe_audio_fast(self, audio_file_path: str) -> str:
        """Fast transcription with optimized settings"""
        try:
            def transcribe():
                with open(audio_file_path, "rb") as audio_file:
                    return openai.Audio.transcribe(
                        model="whisper-1",
                        file=audio_file,
                        language="en",
                        # Fast transcription settings
                        response_format="text",
                        temperature=0  # Deterministic for speed
                    )
            
            # Run in thread pool to avoid blocking
            loop = asyncio.get_event_loop()
            result = await loop.run_in_executor(executor, transcribe)
            
            # Handle both dict and string responses
            if isinstance(result, dict):
                return result.get("text", str(result))
            return str(result)
            
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"Transcription failed: {str(e)}")
    
    async def enhance_text_fast(self, text: str) -> str:
        """Fast text enhancement with shorter prompt"""
        try:
            # Simplified prompt for speed
            prompt = f"Fix grammar and clarity, keep meaning: '{text}'"
            
            def enhance():
                return openai.ChatCompletion.create(
                    model="gpt-3.5-turbo",
                    messages=[{"role": "user", "content": prompt}],
                    max_tokens=100,  # Reduced tokens for speed
                    temperature=0,   # Deterministic for speed
                    top_p=1,
                    frequency_penalty=0,
                    presence_penalty=0
                )
            
            # Run in thread pool
            loop = asyncio.get_event_loop()
            response = await loop.run_in_executor(executor, enhance)
            
            enhanced_text = response.choices[0].message.content.strip()
            
            # Quick validation
            if len(enhanced_text) < 3:
                return text
                
            return enhanced_text
            
        except Exception as e:
            print(f"Enhancement error: {str(e)}")
            return text  # Return original if enhancement fails
    
    async def generate_speech_fast(self, text: str, voice_id: str = None) -> bytes:
        """Fast speech generation with optimized settings"""
        try:
            if not voice_id:
                voice_id = "29vD33N1CtxCmqQRPOHJ"  # Default male voice (Drew)
            
            print(f"Generating speech with voice ID: {voice_id}")
            
            url = f"{self.elevenlabs_base_url}/text-to-speech/{voice_id}"
            
            headers = {
                "Accept": "audio/mpeg",
                "Content-Type": "application/json",
                "xi-api-key": ELEVENLABS_API_KEY
            }
            
            # Settings optimized for voice preservation and emotion
            data = {
                "text": text,
                "model_id": "eleven_multilingual_v2",  # Better for emotion preservation
                "voice_settings": {
                    "stability": 0.4,  # Lower for more emotion variation
                    "similarity_boost": 0.8,  # Higher to preserve voice characteristics
                    "style": 0.3,  # Add some style variation
                    "use_speaker_boost": True  # Preserve speaker characteristics
                }
            }
            
            # Use requests in thread pool for speed
            def sync_request():
                return requests.post(url, json=data, headers=headers, timeout=15)
            
            loop = asyncio.get_event_loop()
            response = await loop.run_in_executor(executor, sync_request)
            
            if response.status_code == 200:
                return response.content
            else:
                print(f"Speech generation error: {response.status_code} - {response.text}")
                raise Exception(f"ElevenLabs API error: {response.status_code} - {response.text}")
                        
        except Exception as e:
            print(f"Speech generation failed: {str(e)}")
            raise HTTPException(status_code=500, detail=f"Speech generation failed: {str(e)}")
    
    async def clone_voice(self, name: str, audio_file_path: str) -> str:
        """Clone voice using ElevenLabs Professional Voice Cloning"""
        try:
            url = f"{self.elevenlabs_base_url}/voices/add"
            
            headers = {
                "xi-api-key": ELEVENLABS_API_KEY
            }
            
            # Use professional cloning for better quality
            with open(audio_file_path, "rb") as audio_file:
                files = {
                    "files": (os.path.basename(audio_file_path), audio_file, "audio/mpeg")
                }
                data = {
                    "name": name,
                    "description": f"Professional clone for {name} - preserves emotions and speaking style",
                    "remove_background_noise": "true",  # Clean up audio
                }
                
                def sync_clone():
                    return requests.post(url, headers=headers, files=files, data=data, timeout=60)
                
                # Run in thread pool to avoid blocking
                loop = asyncio.get_event_loop()
                response = await loop.run_in_executor(executor, sync_clone)
            
            if response.status_code == 200:
                result = response.json()
                print(f"Voice cloned successfully: {result['voice_id']}")
                return result["voice_id"]
            else:
                print(f"Voice cloning failed: {response.status_code} - {response.text}")
                raise Exception(f"ElevenLabs clone error: {response.status_code} - {response.text}")
                
        except Exception as e:
            print(f"Voice cloning error: {str(e)}")
            raise HTTPException(status_code=500, detail=f"Voice cloning failed: {str(e)}")
    
    async def process_parallel(self, text: str, voice_id: str = None):
        """Process enhancement and speech generation in parallel"""
        try:
            # Start both tasks simultaneously
            enhance_task = asyncio.create_task(self.enhance_text_fast(text))
            
            # Wait for enhancement to complete first
            enhanced_text = await enhance_task
            
            # Generate speech with enhanced text
            audio_data = await self.generate_speech_fast(enhanced_text, voice_id)
            
            return enhanced_text, audio_data
            
        except Exception as e:
            # Fallback: use original text if enhancement fails
            audio_data = await self.generate_speech_fast(text, voice_id)
            return text, audio_data

speech_processor = OptimizedSpeechProcessor()

@app.get("/")
async def root():
    return {"message": "Ctrl+Z Speech Clarity API is running! ⚡"}

@app.post("/api/create-voice-profile")
async def create_voice_profile(name: str, audio: UploadFile = File(...)):
    """Create a voice profile using instant cloning"""
    
    if not audio.content_type.startswith('audio/'):
        raise HTTPException(status_code=400, detail="File must be an audio file")
    
    # Save uploaded audio
    with tempfile.NamedTemporaryFile(delete=False, suffix=".wav") as temp_file:
        content = await audio.read()
        temp_file.write(content)
        temp_audio_path = temp_file.name
    
    try:
        # Clone voice using instant cloning
        voice_id = await speech_processor.clone_voice(name, temp_audio_path)
        
        return JSONResponse({
            "success": True,
            "voice_id": voice_id,
            "message": f"Voice profile '{name}' created instantly!"
        })
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Voice cloning failed: {str(e)}")
    
    finally:
        # Clean up
        try:
            os.unlink(temp_audio_path)
        except:
            pass

@app.post("/api/process-speech-fast")
async def process_speech_fast(audio: UploadFile = File(...), voice_id: str = None, auto_clone: bool = True):
    """Ultra-fast speech processing with automatic voice cloning"""
    
    if not audio.content_type.startswith('audio/'):
        raise HTTPException(status_code=400, detail="File must be an audio file")
    
    start_time = time.time()
    
    # Save uploaded audio to memory-based temp file
    with tempfile.NamedTemporaryFile(delete=False, suffix=".wav") as temp_file:
        content = await audio.read()
        temp_file.write(content)
        temp_audio_path = temp_file.name
    
    try:
        # Step 1: Fast transcription
        transcribe_start = time.time()
        original_text = await speech_processor.transcribe_audio_fast(temp_audio_path)
        transcribe_time = time.time() - transcribe_start
        
        # Step 2: Auto voice cloning if no voice_id provided
        clone_time = 0
        if not voice_id and auto_clone:
            try:
                clone_start = time.time()
                print("Auto-cloning voice from user's speech...")
                voice_id = await speech_processor.clone_voice("AutoClone", temp_audio_path)
                clone_time = time.time() - clone_start
                print(f"Auto-cloned voice: {voice_id} in {clone_time:.2f}s")
            except Exception as e:
                print(f"Auto-cloning failed, using default voice: {str(e)}")
                voice_id = None
        
        # Step 3: Parallel enhancement and speech generation
        process_start = time.time()
        enhanced_text, audio_data = await speech_processor.process_parallel(original_text, voice_id)
        process_time = time.time() - process_start
        
        total_time = time.time() - start_time
        
        return JSONResponse({
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
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
    
    finally:
        # Clean up
        try:
            os.unlink(temp_audio_path)
        except:
            pass

@app.get("/api/voices")
async def get_voices():
    """Get available voices from ElevenLabs"""
    try:
        def sync_get():
            return requests.get(
                f"{speech_processor.elevenlabs_base_url}/voices",
                headers={"xi-api-key": ELEVENLABS_API_KEY}
            )

        loop = asyncio.get_event_loop()
        response = await loop.run_in_executor(executor, sync_get)

        if response.status_code == 200:
            data = response.json()
            return JSONResponse({
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
            return JSONResponse({
                "success": False,
                "error": f"API error: {response.status_code}",
                "voices": []
            })
    except Exception as e:
        return JSONResponse({
            "success": False,
            "error": str(e),
            "voices": []
        })

@app.get("/api/speed-test")
async def speed_test():
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
        def sync_test():
            return requests.get(
                f"{speech_processor.elevenlabs_base_url}/voices",
                headers={"xi-api-key": ELEVENLABS_API_KEY}
            )

        loop = asyncio.get_event_loop()
        response = await loop.run_in_executor(executor, sync_test)
        el_time = time.time() - el_start
    except Exception as e:
        el_time = f"Error: {str(e)}"
    
    total = time.time() - start
    
    return {
        "openai_ping": openai_time,
        "elevenlabs_ping": el_time,
        "total_test_time": round(total, 2),
        "status": "APIs are warmed up!" if isinstance(openai_time, float) and isinstance(el_time, float) else "Some APIs may be slow"
    }

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)