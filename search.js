const express = require('express');
const OpenAI = require('openai');
const axios = require('axios');
const router = express.Router();

const openai = new OpenAI({
  apiKey: process.env.OPENAI_API_KEY,
});

// Distance calculation function (Haversine formula)
function calculateDistance(lat1, lon1, lat2, lon2, unit = 'km') {
  const R = unit === 'miles' ? 3959 : 6371;
  const dLat = toRadians(lat2 - lat1);
  const dLon = toRadians(lon2 - lon1);
  
  const a = Math.sin(dLat / 2) * Math.sin(dLat / 2) +
            Math.cos(toRadians(lat1)) * Math.cos(toRadians(lat2)) *
            Math.sin(dLon / 2) * Math.sin(dLon / 2);
  
  const c = 2 * Math.atan2(Math.sqrt(a), Math.sqrt(1 - a));
  const distance = R * c;
  
  return Math.round(distance * 10) / 10;
}

function toRadians(degrees) {
  return degrees * (Math.PI / 180);
}

// Get coordinates for a location using Google Geocoding API
async function getLocationCoordinates(location) {
  try {
    console.log(`🔍 Attempting to geocode: "${location}"`);
    
    const response = await axios.get(
      'https://maps.googleapis.com/maps/api/geocode/json',
      {
        params: {
          address: location,
          key: process.env.GOOGLE_PLACES_API_KEY
        }
      }
    );

    console.log(`📡 Geocoding response status: ${response.data.status}`);
    
    if (response.data.error_message) {
      console.error(`❌ Geocoding API error: ${response.data.error_message}`);
    }

    if (response.data.results && response.data.results.length > 0) {
      const coords = response.data.results[0].geometry.location;
      console.log(`📍 Found coordinates for ${location}: ${coords.lat}, ${coords.lng}`);
      return { 
        lat: coords.lat, 
        lng: coords.lng,
        country: getCountryFromGeocodingResult(response.data.results[0])
      };
    }
    
    console.log(`❌ No coordinates found for ${location}`);
    return null;
  } catch (error) {
    console.error('❌ Geocoding error:', error.response?.data || error.message);
    return null;
  }
}

// Extract country from geocoding result for language detection
function getCountryFromGeocodingResult(result) {
  const components = result.address_components || [];
  const countryComponent = components.find(comp => comp.types.includes('country'));
  return countryComponent?.short_name || 'US';
}

// Auto-detect local language based on country
function getLocalLanguage(countryCode) {
  const languageMap = {
    'US': 'en', 'CA': 'en', 'GB': 'en', 'AU': 'en', 'NZ': 'en',
     'NP': 'ne',
    'MX': 'es', 'ES': 'es', 'AR': 'es', 'CO': 'es', 'PE': 'es',
    'FR': 'fr', 'BE': 'fr', 'CH': 'fr',
    'DE': 'de', 'AT': 'de',
    'IT': 'it',
    'BR': 'pt', 'PT': 'pt',
    'CN': 'zh', 'TW': 'zh',
    'JP': 'ja',
    'KR': 'ko',
    'IN': 'hi',
    'RU': 'ru'
  };
  return languageMap[countryCode] || 'en';
}

// Generate both Google Maps and Apple Maps directions URLs
function generateDirectionsUrls(facilityAddress, facilityName, userLocation, facilityCoords) {
  const origin = encodeURIComponent(userLocation);
  const destination = encodeURIComponent(facilityAddress);
  
  // Google Maps URLs
  const googleMaps = {
    driving: `https://www.google.com/maps/dir/${origin}/${destination}`,
    general: `https://www.google.com/maps/search/${destination}`
  };
  
  // Apple Maps URLs
  const appleMaps = {
    driving: `https://maps.apple.com/?daddr=${destination}&dirflg=d`,
    general: `https://maps.apple.com/?q=${destination}`
  };
  
  // If we have coordinates, use them for more precise Apple Maps links
  if (facilityCoords) {
    const { latitude, longitude } = facilityCoords;
    appleMaps.driving = `https://maps.apple.com/?daddr=${latitude},${longitude}&dirflg=d`;
    appleMaps.general = `https://maps.apple.com/?ll=${latitude},${longitude}&q=${encodeURIComponent(facilityName)}`;
  }
  
  return {
    google: googleMaps,
    apple: appleMaps
  };
}

// Create location bias for Google Places API
function createLocationBias(userCoords, radiusMiles = 31) {
  if (!userCoords) {
    return null;
  }
  
  // Convert miles to meters (max 50000 for API)
  const radiusMeters = Math.min(radiusMiles * 1609.34, 50000);
  
  return {
    circle: {
      center: {
        latitude: userCoords.lat,
        longitude: userCoords.lng
      },
      radius: radiusMeters
    }
  };
}

// Smart facility filtering based on service type
function filterFacilitiesByServiceType(facilities, needTypes) {
  console.log(`🔧 Filtering ${facilities.length} facilities for services: ${needTypes.join(', ')}`);
  
  const filtered = facilities.filter(facility => {
    const name = facility.displayName?.text?.toLowerCase() || '';
    const types = facility.types || [];
    const typesStr = types.join(' ').toLowerCase();
    
    // EXCLUDE pet clinics, veterinary, and non-human medical facilities
    if (name.includes('pet') || name.includes('veterinary') || name.includes('animal') || 
        typesStr.includes('veterinary') || name.includes('vet ')) {
      console.log(`❌ Excluding: ${facility.displayName?.text} (veterinary/pet facility)`);
      return false;
    }
    
    // Emergency: Prioritize hospitals and emergency rooms
    if (needTypes.includes('emergency')) {
      const isEmergencyRelevant = 
        name.includes('hospital') ||
        name.includes('emergency') ||
        name.includes('medical center') ||
        name.includes('trauma') ||
        name.includes('stroke center') ||
        typesStr.includes('hospital') ||
        typesStr.includes('emergency') ||
        // Also include urgent care but with lower priority
        name.includes('urgent care');
      
      if (isEmergencyRelevant) {
        console.log(`✅ Emergency relevant: ${facility.displayName?.text}`);
        return true;
      }
    }
    
    // Rehabilitation: Look for rehab centers, speech therapy, occupational therapy
    if (needTypes.includes('rehabilitation')) {
      const isRehabRelevant = 
        name.includes('rehabilitation') ||
        name.includes('rehab') ||
        name.includes('recovery') ||
        name.includes('therapy') ||
        name.includes('physical therapy') ||
        name.includes('speech') ||
        name.includes('occupational') ||
        typesStr.includes('physiotherapist') ||
        typesStr.includes('rehabilitation');
      
      if (isRehabRelevant) return true;
    }
    
    // Speech Therapy: Specific to speech therapy
    if (needTypes.includes('speech-therapy')) {
      const isSpeechRelevant = 
        name.includes('speech') ||
        name.includes('language') ||
        name.includes('communication') ||
        typesStr.includes('speech');
      
      if (isSpeechRelevant) return true;
    }
    
    // Physical Therapy
    if (needTypes.includes('physical-therapy')) {
      const isPhysicalRelevant = 
        name.includes('physical therapy') ||
        name.includes('physiotherapy') ||
        name.includes('physical rehab') ||
        typesStr.includes('physiotherapist');
      
      if (isPhysicalRelevant) return true;
    }
    
    // Occupational Therapy
    if (needTypes.includes('occupational-therapy')) {
      const isOccupationalRelevant = 
        name.includes('occupational') ||
        name.includes('occupational therapy') ||
        typesStr.includes('occupational');
      
      if (isOccupationalRelevant) return true;
    }
    
    // Support Groups: Community centers, hospitals with support programs
    if (needTypes.includes('support-groups')) {
      const isSupportRelevant = 
        name.includes('support') ||
        name.includes('community') ||
        name.includes('group') ||
        name.includes('center') ||
        name.includes('association') ||
        typesStr.includes('community_center');
      
      if (isSupportRelevant) return true;
    }
    
    // If no specific match but it's a major medical facility, include it
    const isMajorMedical = 
      name.includes('hospital') ||
      name.includes('medical center') ||
      typesStr.includes('hospital');
    
    if (isMajorMedical) {
      console.log(`✅ Major medical facility: ${facility.displayName?.text}`);
      return true;
    }
    
    console.log(`❌ Excluding: ${facility.displayName?.text} (not relevant for ${needTypes.join(', ')})`);
    return false;
  });
  
  console.log(`✅ Filtered to ${filtered.length} relevant facilities`);
  return filtered;
}

// Get real facilities from Google Places API (New)
async function getRealFacilities(location, needTypes) {
  console.log('🔍 Searching for medical facilities...');
  
  try {
    // Get user location coordinates
    const userCoords = await getLocationCoordinates(location);
    
    // Set search radius based on service type
    let searchRadius = 31; // Default 31 miles
    if (needTypes.includes('support-groups')) {
      searchRadius = 50; // Max radius for support groups
    }
    
    const locationBias = createLocationBias(userCoords, searchRadius);
    
    // All facilities found
    const allFacilities = [];
    
    // Create targeted search queries based on need types
    const searchQueries = [];
    
    // Emergency: Focus on hospitals and emergency rooms
    if (needTypes.includes('emergency')) {
      searchQueries.push('stroke center near ' + location);
      searchQueries.push('hospital emergency room near ' + location);
      searchQueries.push('trauma center near ' + location);
      searchQueries.push('comprehensive stroke center near ' + location);
    }
    
    // Rehabilitation: Focus on stroke rehab and comprehensive therapy
    if (needTypes.includes('rehabilitation')) {
      searchQueries.push('stroke rehabilitation center near ' + location);
      searchQueries.push('neurological rehabilitation hospital near ' + location);
      searchQueries.push('inpatient rehabilitation facility near ' + location);
      searchQueries.push('stroke recovery center near ' + location);
    }
    
    // Specific therapy types
    if (needTypes.includes('speech-therapy')) {
      searchQueries.push('speech therapy clinic near ' + location);
      searchQueries.push('speech language pathologist near ' + location);
    }
    
    if (needTypes.includes('physical-therapy')) {
      searchQueries.push('physical therapy clinic near ' + location);
      searchQueries.push('neurological physical therapy near ' + location);
    }
    
    if (needTypes.includes('occupational-therapy')) {
      searchQueries.push('occupational therapy near ' + location);
      searchQueries.push('occupational therapist near ' + location);
    }
    
    // Support Groups: Cast wider net
    if (needTypes.includes('support-groups')) {
      searchQueries.push('stroke support group near ' + location);
      searchQueries.push('stroke survivor group near ' + location);
      searchQueries.push('brain injury support center near ' + location);
      searchQueries.push('community health center near ' + location);
    }
    
    // Always include general medical searches
    searchQueries.push('hospital near ' + location);
    searchQueries.push('medical center near ' + location);
    
    // Search for each query
    for (const query of searchQueries) {
      try {
        console.log(`🔍 Searching: "${query}"`);
        
        const requestBody = {
          textQuery: query,
          maxResultCount: 20,
          rankPreference: 'DISTANCE'
        };
        
        // Only add location bias if we have coordinates
        if (locationBias) {
          requestBody.locationBias = locationBias;
        }
        
        const response = await axios.post(
          'https://places.googleapis.com/v1/places:searchText',
          requestBody,
          {
            headers: {
              'Content-Type': 'application/json',
              'X-Goog-Api-Key': process.env.GOOGLE_PLACES_API_KEY,
              'X-Goog-FieldMask': 'places.displayName,places.formattedAddress,places.internationalPhoneNumber,places.websiteUri,places.rating,places.userRatingCount,places.types,places.businessStatus,places.location'
            }
          }
        );

        if (response.data.places && response.data.places.length > 0) {
          allFacilities.push(...response.data.places);
          console.log(`✅ Found ${response.data.places.length} facilities for: ${query.substring(0, 50)}...`);
        } else {
          console.log(`⚠️ No results for: ${query.substring(0, 50)}...`);
        }
        
        // Small delay to avoid rate limiting
        await new Promise(resolve => setTimeout(resolve, 200));
        
      } catch (error) {
        console.error(`❌ Search failed for query "${query}":`, error.response?.data?.error || error.message);
        continue;
      }
    }
    
    // Remove duplicates
    const uniqueFacilities = [];
    const seenPlaces = new Set();
    
    for (const facility of allFacilities) {
      const placeId = `${facility.displayName?.text}-${facility.formattedAddress}`;
      if (!seenPlaces.has(placeId)) {
        seenPlaces.add(placeId);
        uniqueFacilities.push(facility);
      }
    }
    
    console.log(`📊 Total unique facilities found: ${uniqueFacilities.length}`);
    
    // Smart filter based on service types
    const filteredFacilities = filterFacilitiesByServiceType(uniqueFacilities, needTypes);
    console.log(`🔧 After filtering: ${filteredFacilities.length} relevant facilities`);
    
    // Add distance and directions to each facility
    const facilitiesWithDetails = filteredFacilities.map(place => {
      const facilityCoords = place.location;
      let distance = null;
      let directions = null;
      
      // Calculate distance if we have coordinates
      if (userCoords && facilityCoords) {
        distance = {
          km: calculateDistance(userCoords.lat, userCoords.lng, facilityCoords.latitude, facilityCoords.longitude, 'km'),
          miles: calculateDistance(userCoords.lat, userCoords.lng, facilityCoords.latitude, facilityCoords.longitude, 'miles')
        };
      }
      
      // Generate directions URLs
      if (place.formattedAddress) {
        directions = generateDirectionsUrls(
          place.formattedAddress,
          place.displayName?.text || 'Medical Facility',
          location,
          facilityCoords
        );
      }
      
      return {
        ...place,
        distance,
        directions
      };
    });
    
    // Sort by relevance first, then distance
    const sortedFacilities = facilitiesWithDetails.sort((a, b) => {
      const aName = a.displayName?.text?.toLowerCase() || '';
      const bName = b.displayName?.text?.toLowerCase() || '';
      
      // Priority scoring for emergency services
      if (needTypes.includes('emergency')) {
        // Stroke centers get highest priority
        const aIsStrokeCenter = aName.includes('stroke') ? 10 : 0;
        const bIsStrokeCenter = bName.includes('stroke') ? 10 : 0;
        
        // Hospitals get high priority
        const aIsHospital = (aName.includes('hospital') || aName.includes('medical center')) && 
                   !aName.includes('urgent') && 
                   !aName.includes('eye') && 
                   !aName.includes('dental') && 
                   !aName.includes('skin') &&
                  !aName.includes('ent') ? 8 : 0;
        const bIsHospital = (bName.includes('hospital') || bName.includes('medical center')) && 
                   !bName.includes('urgent') && 
                   !bName.includes('eye') && 
                   !bName.includes('dental') && 
                   !bName.includes('skin') && 
                   !bName.includes('ent') ? 8 : 0;

        // Emergency departments get medium-high priority
        const aIsEmergency = aName.includes('emergency') && !aName.includes('urgent') ? 6 : 0;
        const bIsEmergency = bName.includes('emergency') && !bName.includes('urgent') ? 6 : 0;
        
        // Trauma centers get high priority
        const aIsTrauma = aName.includes('trauma') ? 7 : 0;
        const bIsTrauma = bName.includes('trauma') ? 7 : 0;
        
        // Urgent care gets lower priority (but still included)
        const aIsUrgentCare = aName.includes('urgent') ? 3 : 0;
        const bIsUrgentCare = bName.includes('urgent') ? 3 : 0;
        
        const aScore = aIsStrokeCenter + aIsHospital + aIsEmergency + aIsTrauma + aIsUrgentCare;
        const bScore = bIsStrokeCenter + bIsHospital + bIsEmergency + bIsTrauma + bIsUrgentCare;
        
        console.log(`🏥 ${aName.substring(0, 30)}: score ${aScore}, ${bName.substring(0, 30)}: score ${bScore}`);
        
        if (aScore !== bScore) return bScore - aScore; // Higher score first
      }
      
      // If relevance is equal, sort by distance
      if (a.distance && b.distance) {
        return a.distance.miles - b.distance.miles;
      }
      return 0;
    });
    
    console.log(`🎯 Sorted facilities by relevance and distance`);
    sortedFacilities.slice(0, 5).forEach((facility, index) => {
      console.log(`${index + 1}. ${facility.displayName?.text} - ${facility.distance?.miles || 'unknown'} miles`);
    });
    
    // Filter by max distance based on service type
    const maxDistance = needTypes.includes('support-groups') ? 50 : 31;
    const finalResults = sortedFacilities.filter(facility => {
      if (facility.distance && facility.distance.miles) {
        return facility.distance.miles <= maxDistance;
      }
      return true;
    });
    
    console.log(`🎯 Final results within ${maxDistance}-mile radius: ${finalResults.length}`);
    return finalResults;
    
  } catch (error) {
    console.error('❌ Google Places API error:', error.message);
    return [];
  }
}

// Enhanced ChatGPT analysis with smart insights application for pagination
async function enhanceWithChatGPT(realFacilities, location, needTypes, language, detectedLocalLanguage) {
  // Add missing variables
  const languageContext = language === 'local' ? detectedLocalLanguage : language;
  const needsTranslation = languageContext !== 'en';
  if (realFacilities.length === 0) {
    return {
      success: false,
      error: "No facilities found in your area",
      facilities: []
    };
  }

  // Analyze top 15 facilities with ChatGPT (to stay under token limits)
  const maxFacilitiesForAI = 15;
  const facilitiesForAI = realFacilities.slice(0, maxFacilitiesForAI);
  
  console.log(`🎯 Analyzing top ${facilitiesForAI.length} facilities with AI (from ${realFacilities.length} total)`);

  // Prepare facility data for ChatGPT - minimal to reduce tokens
  const facilityDataForAI = facilitiesForAI.map(place => ({
    name: place.displayName?.text || 'Unknown',
    address: place.formattedAddress || 'Address not available',
    types: place.types || [],
    distance: place.distance
  }));

  // Build language assessment context
  const prompt = `You are a medical emergency expert. Analyze these facilities for STROKE EMERGENCY care in ${location}.

CRITICAL: You must be EXTREMELY strict about medical relevance for stroke care.

FACILITIES:
${facilityDataForAI.map((f, i) => `${i + 1}. ${f.name} - ${f.address} - Types: ${f.types.join(', ')}`).join('\n')}

PATIENT NEEDS: ${needTypes.join(', ')}
LANGUAGE: ${language}${language !== 'en' ? ' (non-English)' : ''}

STROKE EMERGENCY MEDICAL RELEVANCE (BE EXTREMELY STRICT):

HIGH RELEVANCE (Only these can treat stroke emergencies):
- General hospitals with emergency departments
- Trauma centers  
- Stroke centers
- Major medical centers with neurology

MEDIUM RELEVANCE:
- Urgent care centers (can stabilize but limited stroke care)

LOW RELEVANCE (CANNOT treat stroke emergencies):
- Eye hospitals (ophthalmology only)
- Dental hospitals (dentistry only) 
- Skin hospitals (dermatology only)
- ENT hospitals (ear/nose/throat only)
- Specialty clinics
- Diagnostic centers

MANDATORY RULES - NO EXCEPTIONS:
- If hospital name contains "Eye" → MUST be LOW relevance
- If hospital name contains "Dental" → MUST be LOW relevance  
- If hospital name contains "Skin" → MUST be LOW relevance
- If hospital name contains "ENT" → MUST be LOW relevance
- If hospital name contains "Dermat" → MUST be LOW relevance

EXAMPLES:
- "Nepal Eye Hospital" = LOW (eye specialty, cannot treat stroke)
- "Dental Care Hospital" = LOW (dental specialty, cannot treat stroke)
- "Civil Service Hospital" = HIGH (general hospital, can treat strokes)
- "Emergency Department" = HIGH (emergency care, can treat stroke)

MANDATORY OVERRIDES - THESE MUST BE LOW:
- "Nepal Eye Hospital" = LOW (ophthalmology specialty, CANNOT treat stroke)
- "ASG Eye Hospital" = LOW (ophthalmology specialty, CANNOT treat stroke)  
- "Central Health care Dental" = LOW (dental specialty, CANNOT treat stroke)
- "Dental Care Hospital" = LOW (dental specialty, CANNOT treat stroke)
- "Nepal Skin Hospital" = LOW (dermatology specialty, CANNOT treat stroke)

CRITICAL RULE: Any hospital with "Eye", "Dental", "Skin", "ENT" in the name MUST be rated LOW for stroke emergencies, regardless of being called a "hospital".

Return JSON with detailed analysis for pattern matching:`;

  let aiAnalysis = null;
  
  try {
    console.log('🧠 Enhancing facilities with ChatGPT medical insights...');
    
    const completion = await openai.chat.completions.create({
      model: 'gpt-4o-mini',
      messages: [
        {
          role: 'system',
          content: 'You are a medical expert. Analyze facilities and provide patterns for similar facilities. Return only valid JSON.'
        },
        {
          role: 'user',
          content: prompt
        }
      ],
      temperature: 0.1,
      max_tokens: 3000,
      response_format: { type: 'json_object' }
    });

    aiAnalysis = JSON.parse(completion.choices[0].message.content);
    console.log('✅ ChatGPT analysis completed successfully');
    
  } catch (error) {
    console.error('❌ ChatGPT error:', error.message);
    // Continue without AI analysis
  }

  // Function to determine facility type for pattern matching
  function getFacilityType(facility) {
    const name = facility.displayName?.text?.toLowerCase() || '';
    const types = facility.types || [];
    const typesStr = types.join(' ').toLowerCase();
    
    if (name.includes('hospital') || typesStr.includes('hospital')) return 'hospital';
    if (name.includes('urgent care') || name.includes('urgent')) return 'urgent_care';
    if (name.includes('clinic') || typesStr.includes('clinic')) return 'clinic';
    if (name.includes('center') && (name.includes('stroke') || name.includes('heart') || name.includes('neuro'))) return 'specialty_center';
    return 'other';
  }

  // Function to apply AI insights using patterns with SERVICE-SPECIFIC manual override
  function applyAIInsights(facility, index) {
    console.log(`🔍 Checking facility: ${facility.displayName?.text}`);
    
    // SERVICE-SPECIFIC MANUAL OVERRIDE
    const name = (facility.displayName?.text || '').toLowerCase();
    console.log(`🔍 Name lowercased: ${name}`);
    console.log(`🔍 Service types: ${needTypes.join(', ')}`);
    
    // FOR EMERGENCY - Strict exclusions (eye, dental, skin, ENT cannot treat stroke emergencies)
    if (needTypes.includes('emergency')) {
      if (name.includes('eye') || name.includes('dental') || name.includes('skin') || 
          name.includes('ent') || name.includes('dermat') || name.includes('ophthalm')) {
        console.log(`🚫 EMERGENCY OVERRIDE TRIGGERED for: ${name}`);
        return {
          medical_relevance: 'Low',
          language_support: 'Unknown',
          language_note: 'Language support not assessed',
          service_match: 'Poor',
          specialty_note: 'Specialty hospital - not equipped for stroke emergencies',
          facility_type: 'specialty_hospital'
        };
      }
    }
    
    // FOR REHABILITATION/THERAPY - More selective exclusions
    if (needTypes.includes('rehabilitation') || needTypes.includes('speech-therapy') || 
        needTypes.includes('physical-therapy') || needTypes.includes('occupational-therapy')) {
      
      // Still exclude eye and dental (they don't do stroke rehab)
      if (name.includes('eye') || name.includes('dental')) {
        console.log(`🚫 REHAB OVERRIDE TRIGGERED for: ${name} (eye/dental not relevant for stroke rehab)`);
        return {
          medical_relevance: 'Low',
          language_support: 'Unknown',
          language_note: 'Language support not assessed',
          service_match: 'Poor',
          specialty_note: 'Specialty hospital - not relevant for stroke rehabilitation',
          facility_type: 'specialty_hospital'
        };
      }
      
      // ALLOW speech therapy and PT clinics to be rated normally for therapy services
      if (name.includes('speech') && needTypes.includes('speech-therapy')) {
        console.log(`✅ ALLOWING speech therapy facility for speech-therapy service: ${name}`);
        // Let it continue to normal AI analysis
      }
      
      if ((name.includes('physical therapy') || name.includes('physiotherapy')) && 
          needTypes.includes('physical-therapy')) {
        console.log(`✅ ALLOWING physical therapy facility for physical-therapy service: ${name}`);
        // Let it continue to normal AI analysis
      }
    }
    
    // FOR SUPPORT GROUPS - Only exclude clearly irrelevant specialties
    if (needTypes.includes('support-groups')) {
      if (name.includes('eye') || name.includes('dental') || name.includes('skin')) {
        console.log(`🚫 SUPPORT GROUP OVERRIDE TRIGGERED for: ${name} (specialty not relevant for support)`);
        return {
          medical_relevance: 'Low',
          language_support: 'Unknown',
          language_note: 'Language support not assessed',
          service_match: 'Poor',
          specialty_note: 'Specialty hospital - not relevant for stroke support services',
          facility_type: 'specialty_hospital'
        };
      }
    }
    
    console.log(`✅ No service-specific override needed for: ${name}`);

    // If we have direct AI analysis for this facility, use it
    if (aiAnalysis && aiAnalysis.facilities && aiAnalysis.facilities[index]) {
      return aiAnalysis.facilities[index];
    }
    
    // Otherwise, apply patterns based on facility type
    const facilityType = getFacilityType(facility);
    
    let insights = {
      medical_relevance: 'Medium',
      language_support: 'Unknown',
      language_note: 'Language support not assessed',
      service_match: 'Good',
      specialty_note: 'Medical facility',
      facility_type: facilityType
    };
    
    // Apply AI patterns if available
    if (aiAnalysis && aiAnalysis.patterns) {
      const patterns = aiAnalysis.patterns;
      
      // Apply language support patterns
      if (facilityType === 'hospital' && patterns.hospital_language_support) {
        insights.language_support = patterns.hospital_language_support;
      } else if (facilityType === 'urgent_care' && patterns.urgent_care_language_support) {
        insights.language_support = patterns.urgent_care_language_support;
      } else if (facilityType === 'clinic' && patterns.clinic_language_support) {
        insights.language_support = patterns.clinic_language_support;
      }
      
      if (patterns.general_language_note) {
        insights.language_note = patterns.general_language_note;
      }
    }
    
    // Apply rule-based insights for medical relevance based on service type
    if (needTypes.includes('emergency')) {
      if (name.includes('stroke') || name.includes('trauma')) {
        insights.medical_relevance = 'High';
        insights.specialty_note = 'Specialized for stroke/trauma care';
        insights.service_match = 'Excellent';
      } else if (facilityType === 'hospital' && 
          !name.includes('eye') && 
          !name.includes('dental') && 
          !name.includes('skin')) {
        insights.medical_relevance = 'High';
        insights.specialty_note = 'Hospital with emergency department';
        insights.service_match = 'Excellent';
      } else if (facilityType === 'urgent_care') {
        insights.medical_relevance = 'Medium';
        insights.specialty_note = 'Urgent care facility, not specialized for stroke emergencies';
        insights.service_match = 'Fair';
      }
    }
    
    // Rehabilitation and therapy services
    if (needTypes.includes('rehabilitation') || needTypes.includes('speech-therapy') || 
        needTypes.includes('physical-therapy') || needTypes.includes('occupational-therapy')) {
      
      // Speech therapy clinics get high relevance for speech therapy
      if (name.includes('speech') && needTypes.includes('speech-therapy')) {
        insights.medical_relevance = 'High';
        insights.specialty_note = 'Specialized speech therapy services';
        insights.service_match = 'Excellent';
      }
      
      // Physical therapy clinics get high relevance for physical therapy
      if ((name.includes('physical therapy') || name.includes('physiotherapy')) && 
          needTypes.includes('physical-therapy')) {
        insights.medical_relevance = 'High';
        insights.specialty_note = 'Specialized physical therapy services';
        insights.service_match = 'Excellent';
      }
      
      // Occupational therapy clinics get high relevance for occupational therapy
      if (name.includes('occupational') && needTypes.includes('occupational-therapy')) {
        insights.medical_relevance = 'High';
        insights.specialty_note = 'Specialized occupational therapy services';
        insights.service_match = 'Excellent';
      }
      
      // Rehabilitation centers get high relevance for rehabilitation
      if ((name.includes('rehabilitation') || name.includes('rehab')) && 
          needTypes.includes('rehabilitation')) {
        insights.medical_relevance = 'High';
        insights.specialty_note = 'Specialized rehabilitation services';
        insights.service_match = 'Excellent';
      }
      
      // General hospitals also good for rehab services
      if (facilityType === 'hospital' && !name.includes('eye') && !name.includes('dental')) {
        insights.medical_relevance = 'High';
        insights.specialty_note = 'Hospital with rehabilitation services';
        insights.service_match = 'Good';
      }
    }
    
    // Default language support for English-speaking areas
    if (insights.language_support === 'Unknown' && languageContext === 'en') {
      insights.language_support = 'Confirmed';
      insights.language_note = 'English is the primary language spoken';
    }
    
    return insights;
  }

  // Enhance ALL facilities using AI analysis + patterns
  const enhancedFacilities = realFacilities.map((facility, index) => {
    const aiInsights = applyAIInsights(facility, index);
    
    return {
      name: facility.displayName?.text || 'Unknown',
      address: facility.formattedAddress || 'Address not available',
      phone: facility.internationalPhoneNumber || 'Not available',
      website: facility.websiteUri || 'Not available',
      rating: facility.rating || 'Not available',
      userRatingCount: facility.userRatingCount || 0,
      distance: facility.distance,
      directions: facility.directions,
      types: facility.types || [],
      ...aiInsights,
      likely_services: needTypes.includes('emergency') ? ['Emergency care', 'Stroke treatment'] : 
                      needTypes.includes('rehabilitation') ? ['Rehabilitation services', 'Therapy programs'] :
                      needTypes.includes('speech-therapy') ? ['Speech therapy', 'Language therapy'] :
                      needTypes.includes('physical-therapy') ? ['Physical therapy', 'Motor rehabilitation'] :
                      needTypes.includes('occupational-therapy') ? ['Occupational therapy', 'Daily living skills'] :
                      ['Medical services']
    };
  });

  console.log(`✅ Enhanced ${enhancedFacilities.length} facilities (${facilitiesForAI.length} with AI, ${enhancedFacilities.length - facilitiesForAI.length} with patterns)`);
  
  return {
    success: true,
    facilities: enhancedFacilities,
    total_facilities_found: realFacilities.length,
    ai_analyzed_count: facilitiesForAI.length,
    pattern_applied_count: enhancedFacilities.length - facilitiesForAI.length,
    detected_language: detectedLocalLanguage,
    search_language: languageContext,
    emergency_info: {
      local_emergency_number: "911",
      note: "Call 911 immediately if experiencing stroke symptoms"
    },
    sorting_options: {
      available: ["relevance", "distance"],
      default: "relevance"
    },
    pagination: {
      total_results: enhancedFacilities.length,
      results_per_page: 10,
      total_pages: Math.ceil(enhancedFacilities.length / 10)
    }
  };
}

// Add sorting endpoint
router.post('/search/sort', async (req, res) => {
  const { facilities, sortBy } = req.body;
  
  if (!facilities || !Array.isArray(facilities)) {
    return res.status(400).json({
      success: false,
      error: 'Invalid facilities data'
    });
  }
  
  let sortedFacilities = [...facilities];
  
  if (sortBy === 'distance') {
    sortedFacilities.sort((a, b) => {
      if (a.distance && b.distance) {
        return a.distance.miles - b.distance.miles;
      }
      return 0;
    });
  } else if (sortBy === 'relevance') {
    sortedFacilities.sort((a, b) => {
      // Relevance scoring
      const relevanceScore = {
        'High': 3,
        'Medium': 2, 
        'Low': 1
      };
      
      const aScore = relevanceScore[a.medical_relevance] || 1;
      const bScore = relevanceScore[b.medical_relevance] || 1;
      
      if (aScore !== bScore) return bScore - aScore;
      
      // If relevance is equal, sort by distance
      if (a.distance && b.distance) {
        return a.distance.miles - b.distance.miles;
      }
      return 0;
    });
  }
  
  res.json({
    success: true,
    facilities: sortedFacilities,
    sorted_by: sortBy
  });
});

// Main search route
router.post('/search', async (req, res) => {
  let { location, needTypes, language } = req.body;

  if (!location || !needTypes || !needTypes.length) {
    return res.status(400).json({
      success: false,
      error: 'Missing required fields: location and needTypes are required.'
    });
  }

  console.log('🔥 STARTING SEARCH:', { location, needTypes, language });

  try {
    // Step 1: Get location coordinates and detect local language
    const userCoords = await getLocationCoordinates(location);
    const detectedLocalLanguage = userCoords ? getLocalLanguage(userCoords.country) : 'en';
    
    // If language is 'local', use detected language
    if (language === 'local') {
      language = detectedLocalLanguage;
      console.log(`🌍 Auto-detected local language: ${language} for ${userCoords?.country || 'unknown region'}`);
    }

    // Step 2: Get real facilities from Google Places
    const googleResults = await getRealFacilities(location, needTypes);
    
    if (googleResults.length === 0) {
      return res.json({
        success: false,
        error: "No medical facilities found in your area",
        facilities: [],
        suggestion: "Try searching for a larger city or different location",
        detected_language: detectedLocalLanguage
      });
    }

    // Step 3: Enhance with ChatGPT
    const enhancedResults = await enhanceWithChatGPT(googleResults, location, needTypes, language, detectedLocalLanguage);

    // Step 4: Send response
    res.json({
      ...enhancedResults,
      search_radius: needTypes.includes('support-groups') ? "50 miles (80 km)" : "31 miles (50 km)",
      timestamp: new Date().toISOString()
    });

  } catch (error) {
    console.error('🚨 Search error:', error);
    res.status(500).json({
      success: false,
      error: 'Search failed',
      message: error.message,
      facilities: []
    });
  }
});

module.exports = router;