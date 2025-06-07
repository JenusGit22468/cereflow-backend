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
        const aIsHospital = (aName.includes('hospital') || aName.includes('medical center')) && !aName.includes('urgent') ? 8 : 0;
        const bIsHospital = (bName.includes('hospital') || bName.includes('medical center')) && !bName.includes('urgent') ? 8 : 0;
        
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

// ChatGPT analysis with language support assessment
async function enhanceWithChatGPT(realFacilities, location, needTypes, language, detectedLocalLanguage) {
  if (realFacilities.length === 0) {
    return {
      success: false,
      error: "No facilities found in your area",
      facilities: []
    };
  }

  // Limit to top 10 facilities for better analysis (these should already be filtered and sorted)
  const maxFacilities = 10;
  const facilitiesToAnalyze = realFacilities.slice(0, maxFacilities);
  
  console.log(`📋 Top facilities being analyzed:`);
  facilitiesToAnalyze.forEach((facility, index) => {
    console.log(`${index + 1}. ${facility.displayName?.text} - ${facility.distance?.miles || 'unknown'} miles`);
  });
  
  console.log(`🎯 Analyzing top ${facilitiesToAnalyze.length} facilities (from ${realFacilities.length} total)`);

  // Prepare facility data for ChatGPT - minimal to reduce tokens
  const facilityData = facilitiesToAnalyze.map(place => ({
    name: place.displayName?.text || 'Unknown',
    address: place.formattedAddress || 'Address not available',
    phone: place.internationalPhoneNumber || 'Not available',
    distance: place.distance
  }));

  // Build language assessment context
  const languageContext = language === 'local' ? detectedLocalLanguage : language;
  const needsTranslation = languageContext !== 'en';

  const prompt = `Analyze these ${facilitiesToAnalyze.length} medical facilities for stroke care in ${location}.

FACILITIES:
${facilityData.map((f, i) => `${i + 1}. ${f.name} - ${f.address}`).join('\n')}

PATIENT NEEDS:
- Services: ${needTypes.join(', ')}
- Language: ${languageContext}${needsTranslation ? ' (non-English)' : ''}

ANALYSIS REQUIRED:
1. Medical relevance for stroke care (High/Medium/Low)
2. Language support assessment${needsTranslation ? ` for ${languageContext}` : ''}
3. Service availability for requested needs

Return JSON only:
{
  "facilities": [
    {
      "medical_relevance": "High/Medium/Low",
      "language_support": "Confirmed/Likely/Unlikely/Unknown",
      "language_note": "Brief note about language services",
      "service_match": "Excellent/Good/Fair/Poor",
      "specialty_note": "Brief note about stroke care capabilities"
    }
  ]
}`;

  try {
    console.log('🧠 Enhancing facilities with ChatGPT medical insights...');
    
    const completion = await openai.chat.completions.create({
      model: 'gpt-4o-mini',
      messages: [
        {
          role: 'system',
          content: 'You are a medical expert specializing in stroke care. Analyze facilities for medical relevance and language support. Return only valid JSON.'
        },
        {
          role: 'user',
          content: prompt
        }
      ],
      temperature: 0.1,
      max_tokens: 2000,
      response_format: { type: 'json_object' }
    });

    const analysis = JSON.parse(completion.choices[0].message.content);
    
    // Merge ChatGPT analysis with full facility data
    const enhancedFacilities = facilitiesToAnalyze.map((facility, index) => {
      const chatgptData = analysis.facilities?.[index] || {};
      return {
        name: facility.displayName?.text || 'Unknown',
        address: facility.formattedAddress || 'Address not available',
        phone: facility.internationalPhoneNumber || 'Not available',
        website: facility.websiteUri || 'Not available',
        rating: facility.rating || 'Not available',
        userRatingCount: facility.userRatingCount || 0,
        distance: facility.distance,
        directions: facility.directions,
        medical_relevance: chatgptData.medical_relevance || 'Medium',
        language_support: chatgptData.language_support || 'Unknown',
        language_note: chatgptData.language_note || '',
        service_match: chatgptData.service_match || 'Good',
        specialty_note: chatgptData.specialty_note || 'Medical facility with general services',
        likely_services: needTypes.includes('emergency') ? ['Emergency care', 'Stroke treatment'] : 
                        needTypes.includes('rehabilitation') ? ['Rehabilitation services', 'Therapy programs'] :
                        ['Medical services']
      };
    });

    console.log('✅ ChatGPT enhanced facilities with medical insights');
    
    return {
      success: true,
      facilities: enhancedFacilities,
      total_facilities_found: realFacilities.length,
      analyzed_count: facilitiesToAnalyze.length,
      detected_language: detectedLocalLanguage,
      search_language: languageContext,
      emergency_info: {
        local_emergency_number: "911",
        note: "Call 911 immediately if experiencing stroke symptoms"
      }
    };
    
  } catch (error) {
    console.error('❌ ChatGPT error:', error.message);
    
    // Return facilities without enhancement if ChatGPT fails
    const fallbackFacilities = facilitiesToAnalyze.map(facility => ({
      name: facility.displayName?.text || 'Unknown',
      address: facility.formattedAddress || 'Address not available',
      phone: facility.internationalPhoneNumber || 'Not available',
      website: facility.websiteUri || 'Not available',
      rating: facility.rating || 'Not available',
      userRatingCount: facility.userRatingCount || 0,
      distance: facility.distance,
      directions: facility.directions,
      medical_relevance: 'Not analyzed',
      language_support: 'Unknown',
      language_note: 'Language support assessment unavailable',
      service_match: 'Not analyzed',
      specialty_note: 'Real facility from Google Places',
      likely_services: ['Medical services available']
    }));

    return {
      success: true,
      facilities: fallbackFacilities,
      total_facilities_found: realFacilities.length,
      analyzed_count: facilitiesToAnalyze.length,
      detected_language: detectedLocalLanguage,
      search_language: languageContext,
      emergency_info: {
        local_emergency_number: "911",
        note: "Call 911 immediately if experiencing stroke symptoms"
      }
    };
  }
}

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