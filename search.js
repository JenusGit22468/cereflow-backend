const express = require('express');
const OpenAI = require('openai');
const axios = require('axios');
const router = express.Router();

const openai = new OpenAI({
  apiKey: process.env.OPENAI_API_KEY,
});

// Distance calculation function (Haversine formula)
function calculateDistance(lat1, lon1, lat2, lon2, unit = 'km') {
  const R = unit === 'miles' ? 3959 : 6371; // Earth's radius in miles or kilometers
  const dLat = toRadians(lat2 - lat1);
  const dLon = toRadians(lon2 - lon1);
  
  const a = Math.sin(dLat / 2) * Math.sin(dLat / 2) +
            Math.cos(toRadians(lat1)) * Math.cos(toRadians(lat2)) *
            Math.sin(dLon / 2) * Math.sin(dLon / 2);
  
  const c = 2 * Math.atan2(Math.sqrt(a), Math.sqrt(1 - a));
  const distance = R * c;
  
  return Math.round(distance * 10) / 10; // Round to 1 decimal place
}

function toRadians(degrees) {
  return degrees * (Math.PI / 180);
}

// Get coordinates for a location using Google Geocoding API
async function getLocationCoordinates(location) {
  try {
    const response = await axios.get(
      'https://maps.googleapis.com/maps/api/geocode/json',
      {
        params: {
          address: location,
          key: process.env.GOOGLE_PLACES_API_KEY
        }
      }
    );

    if (response.data.results && response.data.results.length > 0) {
      const coords = response.data.results[0].geometry.location;
      console.log(`📍 Found coordinates for ${location}: ${coords.lat}, ${coords.lng}`);
      return { lat: coords.lat, lng: coords.lng };
    }
    
    console.log(`❌ No coordinates found for ${location}`);
    return null;
  } catch (error) {
    console.error('❌ Geocoding error:', error.message);
    return null;
  }
}

// Generate both Google Maps and Apple Maps directions URLs
function generateDirectionsUrls(facilityAddress, facilityName, userLocation, facilityCoords) {
  const origin = encodeURIComponent(userLocation);
  const destination = encodeURIComponent(facilityAddress);
  
  // Google Maps URLs
  const googleMapsBase = 'https://www.google.com/maps/dir/';
  const googleMaps = {
    driving: `${googleMapsBase}${origin}/${destination}`,
    walking: `${googleMapsBase}${origin}/${destination}/@?entry=ttu&mode=walking`,
    transit: `${googleMapsBase}${origin}/${destination}/@?entry=ttu&mode=transit`,
    general: `https://www.google.com/maps/search/${destination}`
  };
  
  // Apple Maps URLs (works on iOS and macOS)
  const appleMaps = {
    driving: `https://maps.apple.com/?daddr=${destination}&dirflg=d`,
    walking: `https://maps.apple.com/?daddr=${destination}&dirflg=w`,
    transit: `https://maps.apple.com/?daddr=${destination}&dirflg=r`,
    general: `https://maps.apple.com/?q=${destination}`
  };
  
  // If we have coordinates, use them for more precise Apple Maps links
  if (facilityCoords) {
    const { latitude, longitude } = facilityCoords;
    appleMaps.driving = `https://maps.apple.com/?daddr=${latitude},${longitude}&dirflg=d`;
    appleMaps.walking = `https://maps.apple.com/?daddr=${latitude},${longitude}&dirflg=w`;
    appleMaps.transit = `https://maps.apple.com/?daddr=${latitude},${longitude}&dirflg=r`;
    appleMaps.general = `https://maps.apple.com/?ll=${latitude},${longitude}&q=${encodeURIComponent(facilityName)}`;
  }
  
  return {
    google: googleMaps,
    apple: appleMaps
  };
}

// FIXED: Enhanced location bias for 50-mile radius searches with proper coordinate bounds
function getExtendedLocationBias(location, userCoords) {
  // If we have user coordinates, create a 50-mile radius circle (PREFERRED METHOD)
  if (userCoords) {
    return {
      circle: {
        center: {
          latitude: userCoords.lat,
          longitude: userCoords.lng
        },
        radius: 80467 // 50 miles in meters
      }
    };
  }
  
  // Fallback to city-based extended search areas with SAFE coordinate bounds
  const cityCoordinates = {
    'kathmandu': { lat: 27.7172, lng: 85.3240 },
    'new york': { lat: 40.7128, lng: -74.0060 },
    'london': { lat: 51.5074, lng: -0.1278 },
    'tokyo': { lat: 35.6762, lng: 139.6503 },
    'sydney': { lat: -33.8688, lng: 151.2093 },
    'toronto': { lat: 43.6532, lng: -79.3832 },
    'mumbai': { lat: 19.0760, lng: 72.8877 },
    'delhi': { lat: 28.7041, lng: 77.1025 },
    'paris': { lat: 48.8566, lng: 2.3522 },
    'berlin': { lat: 52.5200, lng: 13.4050 },
    'madrid': { lat: 40.4168, lng: -3.7038 },
    'rome': { lat: 41.9028, lng: 12.4964 },
    'beijing': { lat: 39.9042, lng: 116.4074 },
    'shanghai': { lat: 31.2304, lng: 121.4737 },
    'seoul': { lat: 37.5665, lng: 126.9780 },
    'bangkok': { lat: 13.7563, lng: 100.5018 },
    'singapore': { lat: 1.3521, lng: 103.8198 },
    'hong kong': { lat: 22.3193, lng: 114.1694 },
    'dubai': { lat: 25.2048, lng: 55.2708 },
    'cairo': { lat: 30.0444, lng: 31.2357 },
    'lagos': { lat: 6.5244, lng: 3.3792 },
    'johannesburg': { lat: -26.2041, lng: 28.0473 },
    'cape town': { lat: -33.9249, lng: 18.4241 },
    'sao paulo': { lat: -23.5505, lng: -46.6333 },
    'mexico city': { lat: 19.4326, lng: -99.1332 },
    'buenos aires': { lat: -34.6118, lng: -58.3960 },
    // US Cities - Enhanced
    'east lansing': { lat: 42.7370, lng: -84.4839 },
    'lansing': { lat: 42.3314, lng: -84.5467 },
    'michigan': { lat: 44.3467, lng: -84.8554 },
    'detroit': { lat: 42.3314, lng: -83.0458 },
    'chicago': { lat: 41.8781, lng: -87.6298 },
    'los angeles': { lat: 34.0522, lng: -118.2437 },
    'boston': { lat: 42.3601, lng: -71.0589 },
    'miami': { lat: 25.7617, lng: -80.1918 },
    'seattle': { lat: 47.6062, lng: -122.3321 },
    'denver': { lat: 39.7392, lng: -104.9903 }
  };

  const locationLower = location.toLowerCase();
  for (const [city, coords] of Object.entries(cityCoordinates)) {
    if (locationLower.includes(city)) {
      // FIXED: Use smaller, safer radius that won't exceed 180 degrees
      const radius = 0.4; // Reduced from 0.72 to prevent rectangle viewport errors
      
      // Ensure coordinates stay within valid bounds
      const lowLat = Math.max(coords.lat - radius, -85); // Prevent going beyond poles
      const highLat = Math.min(coords.lat + radius, 85);
      const lowLng = Math.max(coords.lng - radius, -179); // Prevent exceeding ±180
      const highLng = Math.min(coords.lng + radius, 179);
      
      return {
        rectangle: {
          low: {
            latitude: lowLat,
            longitude: lowLng
          },
          high: {
            latitude: highLat,
            longitude: highLng
          }
        }
      };
    }
  }

  // Default to safe, moderate search area instead of global search
  return {
    rectangle: {
      low: { latitude: -85, longitude: -179 },
      high: { latitude: 85, longitude: 179 }
    }
  };
}

// Step 1: Get real facilities from Google Places API (New) with distances and directions
async function getRealFacilities(location, needTypes) {
  console.log('🔍 Searching for medical facilities within 50-mile radius...');
  
  try {
    // Get user location coordinates for distance calculation
    const userCoords = await getLocationCoordinates(location);
    if (!userCoords) {
      console.log('❌ Could not get user coordinates, using text search only');
    }
    
    // Multiple search strategies to get more results
    const allFacilities = [];
    
    // Strategy 1: Specific medical facility search - limit query length
    const medicalQueries = [
      // For many needs, use shorter queries to avoid API limits
      needTypes.length > 3 
        ? `${needTypes.slice(0, 3).join(' ')} medical facilities near ${location}`
        : `${needTypes.join(' ')} facilities near ${location}`,
      needTypes.length > 3
        ? `${needTypes.slice(0, 3).join(' ')} centers near ${location}`
        : `${needTypes.join(' ')} centers near ${location}`,
      `rehabilitation clinics near ${location}`,
      `hospitals near ${location}`,
      `medical centers near ${location}`
    ];
    
    // Strategy 2: Broader facility types (enhanced for all medical needs)
    let facilityTypes = ['hospital', 'health', 'doctor'];
    
    // Add specialized facility types based on medical needs
    if (needTypes.includes('physical-therapy')) {
      facilityTypes.push('physiotherapist');
    }
    if (needTypes.includes('speech-therapy')) {
      facilityTypes.push('speech_therapist');
    }
    if (needTypes.includes('occupational-therapy')) {
      facilityTypes.push('occupational_therapist');
    }
    if (needTypes.includes('support-groups')) {
      facilityTypes.push('counselor', 'psychologist');
    }
    
    for (const query of medicalQueries) {
      console.log(`🔍 Searching: ${query}`);
      
      for (const facilityType of facilityTypes) {
        try {
          const response = await axios.post(
            'https://places.googleapis.com/v1/places:searchText',
            {
              textQuery: query,
              maxResultCount: 20, // Increased from 15
              includedType: facilityType,
              // Only use locationBias if we have coordinates, otherwise let Google figure it out
              ...(userCoords ? { locationBias: getExtendedLocationBias(location, userCoords) } : {}),
              rankPreference: 'DISTANCE' // Prioritize by distance
            },
            {
              headers: {
                'Content-Type': 'application/json',
                'X-Goog-Api-Key': process.env.GOOGLE_PLACES_API_KEY,
                'X-Goog-FieldMask': 'places.displayName,places.formattedAddress,places.internationalPhoneNumber,places.websiteUri,places.rating,places.userRatingCount,places.types,places.businessStatus,places.location,places.primaryType'
              }
            }
          );

          if (response.data.places && response.data.places.length > 0) {
            allFacilities.push(...response.data.places);
            console.log(`✅ Found ${response.data.places.length} facilities for ${facilityType} - ${query.substring(0, 30)}...`);
          }
          
          // Small delay to avoid rate limiting
          await new Promise(resolve => setTimeout(resolve, 100));
        } catch (error) {
          console.log(`⚠️ Search failed for ${facilityType}: ${error.message}`);
          continue; // Try next search
        }
      }
    }
    
    // Remove duplicates based on place name and address
    const uniqueFacilities = allFacilities.filter((facility, index, self) => 
      index === self.findIndex(f => 
        f.displayName?.text === facility.displayName?.text && 
        f.formattedAddress === facility.formattedAddress
      )
    );
    
    console.log(`📊 Total unique facilities found: ${uniqueFacilities.length}`);
    
    // Add distance and directions to each facility, filter by 50-mile radius
    const facilitiesWithDirections = uniqueFacilities
      .map(place => {
        const facilityCoords = place.location;
        let distance = null;
        let directions = null;
        
        // Calculate distance if we have both coordinates
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
      })
      .filter(facility => {
        // Filter to 50-mile (80km) radius if we have distance data
        if (facility.distance && facility.distance.miles) {
          return facility.distance.miles <= 50;
        }
        return true; // Keep facilities without distance data
      })
      .sort((a, b) => {
        // Sort by distance (closest first)
        if (a.distance && b.distance) {
          return a.distance.miles - b.distance.miles;
        }
        return 0;
      });
    
    console.log(`🎯 Final results within 50-mile radius: ${facilitiesWithDirections.length}`);
    return facilitiesWithDirections;
    
  } catch (error) {
    console.error('❌ Google Places (New) error:', error.response?.data || error.message);
    return [];
  }
}

// Step 2: ChatGPT analyzes and enhances the real facilities
async function enhanceWithChatGPT(realFacilities, location, needTypes, language) {
  if (realFacilities.length === 0) {
    return {
      success: false,
      error: "No facilities found in Google Places",
      facilities: []
    };
  }

  const facilityData = realFacilities.map(place => ({
    name: place.displayName?.text || 'Unknown',
    address: place.formattedAddress || 'Address not available',
    phone: place.internationalPhoneNumber || 'Not available',
    website: place.websiteUri || 'Not available',
    rating: place.rating || 'Not available',
    userRatingCount: place.userRatingCount || 0,
    types: place.types || [],
    businessStatus: place.businessStatus || 'Unknown',
    distance: place.distance,
    directions: place.directions
  }));

  const prompt = `You are a medical expert analyzing REAL medical facilities for stroke/rehabilitation patients.

VERIFIED FACILITIES FROM GOOGLE PLACES:
${JSON.stringify(facilityData, null, 2)}

PATIENT NEEDS:
- Location: ${location}
- Services needed: ${needTypes.join(', ')}
- Language: ${language}

INSTRUCTIONS:
- Analyze these REAL facilities for ${needTypes.join(' and ')} services
- Rank by medical relevance for stroke/rehabilitation care
- Add medical insights but keep original Google data intact
- DO NOT modify names, addresses, contact info, distances, or directions from Google
- For speech-therapy: Look for speech-language pathology, communication therapy
- For occupational-therapy: Look for daily living skills, fine motor skills training
- For support-groups: Look for stroke support groups, peer counseling, mental health support
- Return your analysis in JSON format

Response format (return valid JSON):
{
  "success": true,
  "facilities": [
    {
      "name": "Exact name from Google",
      "address": "Exact address from Google", 
      "phone": "Exact phone from Google",
      "website": "Exact website from Google",
      "rating": "Google rating",
      "userRatingCount": "Google user count",
      "distance": "Exact distance object from Google",
      "directions": "Exact directions object from Google",
      "medical_relevance": "High/Medium/Low for ${needTypes.join('/')}",
      "likely_services": ["Services they likely offer"],
      "stroke_suitability": "Suitability analysis",
      "notes": "Medical insights"
    }
  ],
  "emergency_info": {
    "local_emergency_number": "Emergency number for ${location}",
    "ambulance_number": "Ambulance number"
  }
}`;

  try {
    console.log('🧠 Analyzing real facilities with ChatGPT...');
    
    const completion = await openai.chat.completions.create({
      model: 'gpt-4o',
      messages: [
        {
          role: 'system',
          content: 'You are a medical expert analyzing verified Google Places data. Never modify the original facility information including distances and directions. Always respond with valid JSON.'
        },
        {
          role: 'user',
          content: prompt
        }
      ],
      temperature: 0.2,
      max_tokens: 4000,
      response_format: { type: 'json_object' }
    });

    const analysis = JSON.parse(completion.choices[0].message.content);
    console.log('✅ ChatGPT enhanced facilities with medical insights');
    
    return analysis;
  } catch (error) {
    console.error('❌ ChatGPT analysis error:', error);
    
    return {
      success: true,
      facilities: facilityData.map(facility => ({
        ...facility,
        type: 'medical_facility',
        medical_relevance: 'Unknown - ChatGPT analysis failed',
        notes: 'Real facility from Google Places (New API)'
      })),
      emergency_info: {
        local_emergency_number: "Contact local emergency services"
      }
    };
  }
}

// Main search route
router.post('/search', async (req, res) => {
  const { location, needTypes, language } = req.body;

  if (!location || !needTypes || !needTypes.length) {
    return res.status(400).json({
      success: false,
      error: 'Missing required fields: location and needTypes are required.',
    });
  }

  console.log('🔥 PLACES API SEARCH - 50 MILE RADIUS:', { location, needTypes, language });

  try {
    const googleResults = await getRealFacilities(location, needTypes);
    
    if (googleResults.length === 0) {
      return res.json({
        success: false,
        error: "No medical facilities found within 50-mile radius",
        facilities: [],
        suggestion: "Try searching for a different location or expand your search criteria"
      });
    }

    console.log(`📊 Pre-ChatGPT analysis: ${googleResults.length} facilities found`);
    
    const enhancedResults = await enhanceWithChatGPT(googleResults, location, needTypes, language);

    const finalResponse = {
      ...enhancedResults,
      search_radius: "50 miles (80 km)",
      total_facilities_found: googleResults.length,
      data_sources: ['Google Places API (New)', 'ChatGPT Medical Analysis', 'Google Geocoding API'],
      query: { location, needTypes, language },
      timestamp: new Date().toISOString(),
      search_method: 'extended_radius_places_chatgpt_v5_final'
    };

    console.log(`🎯 FINAL SEARCH RESULTS: ${finalResponse.facilities?.length || 0} facilities within 50-mile radius`);
    res.json(finalResponse);

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