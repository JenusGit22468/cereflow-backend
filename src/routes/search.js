// =======================
// UPDATED SERVER.JS
// =======================

require('dotenv').config();
const express = require('express');
const cors = require('cors');
const rateLimit = require('express-rate-limit');

const app = express();
const PORT = process.env.PORT || 3000;

// Enhanced middleware
app.use(cors({
  origin: process.env.FRONTEND_URL || 'http://localhost:3000',
  credentials: true
}));

app.use(express.json({ limit: '10mb' }));
app.use(express.urlencoded({ extended: true }));

// Rate limiting
const limiter = rateLimit({
  windowMs: 15 * 60 * 1000, // 15 minutes
  max: 100, // limit each IP to 100 requests per windowMs
  message: { error: 'Too many requests, please try again later.' }
});
app.use('/api', limiter);

// Search-specific rate limiting
const searchLimiter = rateLimit({
  windowMs: 1 * 60 * 1000, // 1 minute
  max: 10, // 10 searches per minute
  message: { error: 'Too many search requests, please wait a moment.' }
});

// Logging middleware
app.use((req, res, next) => {
  console.log(`${new Date().toISOString()} - ${req.method} ${req.path}`);
  next();
});

// Health check
app.get('/', (req, res) => {
  res.json({ 
    message: 'CereFlow Backend is running!',
    version: '2.0.0',
    status: 'healthy',
    timestamp: new Date().toISOString()
  });
});

// Import routes
const searchRoutes = require('./src/routes/search');
const facilitiesRoutes = require('./src/routes/facilities');
const emergencyRoutes = require('./src/routes/emergency');

// Apply routes
app.use('/api/search', searchLimiter, searchRoutes);
app.use('/api/facilities', facilitiesRoutes);
app.use('/api/emergency', emergencyRoutes);

// Error handling middleware
app.use((err, req, res, next) => {
  console.error('Unhandled error:', err);
  res.status(500).json({
    success: false,
    error: 'Internal server error',
    message: process.env.NODE_ENV === 'development' ? err.message : 'Something went wrong'
  });
});

// 404 handler
app.use('*', (req, res) => {
  res.status(404).json({
    success: false,
    error: 'Endpoint not found',
    path: req.originalUrl
  });
});

// Graceful shutdown
process.on('SIGTERM', () => {
  console.log('SIGTERM received, shutting down gracefully');
  server.close(() => {
    console.log('Server closed');
    process.exit(0);
  });
});

const server = app.listen(PORT, () => {
  console.log(`🧠 CereFlow Backend v2.0.0 running on http://localhost:${PORT}`);
  console.log(`🌍 Environment: ${process.env.NODE_ENV || 'development'}`);
});

// =======================
// SRC/ROUTES/SEARCH.JS
// =======================

const express = require('express');
const { GoogleGenerativeAI } = require('@google/generative-ai');
const axios = require('axios');
const { validateSearchInput } = require('../middleware/validation');
const { searchCache } = require('../services/cache');
const { logSearch } = require('../services/logger');
const router = express.Router();

// Initialize Gemini AI
const genAI = new GoogleGenerativeAI(process.env.GEMINI_API_KEY);

// Enhanced search endpoint
router.post('/', validateSearchInput, async (req, res) => {
  try {
    const searchData = {
      location: req.body.location,
      needType: req.body.needType,
      urgency: req.body.urgency || 'scheduled',
      language: req.body.language || 'en',
      insurance: req.body.insurance,
      additionalNeeds: req.body.additionalNeeds
    };

    // Log the search
    logSearch(searchData, req.ip);

    // Check cache first
    const cacheKey = `search_${JSON.stringify(searchData)}`;
    const cachedResult = searchCache.get(cacheKey);
    
    if (cachedResult) {
      console.log('🎯 Returning cached result');
      return res.json({
        ...cachedResult,
        cached: true,
        timestamp: new Date().toISOString()
      });
    }

    // Get location coordinates for better search
    const locationData = await getLocationData(searchData.location);
    
    // Enhanced AI prompt with location context
    const prompt = createEnhancedPrompt(searchData, locationData);
    
    // Get AI response
    const model = genAI.getGenerativeModel({ 
      model: "gemini-1.5-flash",
      generationConfig: {
        temperature: 0.1, // Lower temperature for more consistent results
        topP: 0.8,
        maxOutputTokens: 2048,
      }
    });
    
    const result = await model.generateContent(prompt);
    const aiResponse = result.response.text();
    
    // Enhanced response parsing
    const parsedResponse = await parseAIResponse(aiResponse, searchData);
    
    // Enrich with additional data
    const enrichedResponse = await enrichSearchResults(parsedResponse, locationData);
    
    // Cache the result (5 minutes for emergency, 30 minutes for others)
    const cacheTime = searchData.urgency === 'emergency' ? 300000 : 1800000;
    searchCache.set(cacheKey, enrichedResponse, cacheTime);
    
    res.json({
      ...enrichedResponse,
      cached: false,
      timestamp: new Date().toISOString()
    });
    
  } catch (error) {
    console.error('🚨 Search error:', error);
    res.status(500).json({
      success: false,
      error: 'Search failed',
      message: error.message,
      query: req.body
    });
  }
});

// Get nearby facilities by coordinates
router.get('/nearby', async (req, res) => {
  try {
    const { lat, lng, radius = 25, type = 'hospital' } = req.query;
    
    if (!lat || !lng) {
      return res.status(400).json({
        success: false,
        error: 'Latitude and longitude required'
      });
    }

    const facilities = await findNearbyFacilities(lat, lng, radius, type);
    
    res.json({
      success: true,
      facilities,
      searchParams: { lat, lng, radius, type }
    });
    
  } catch (error) {
    res.status(500).json({
      success: false,
      error: 'Failed to find nearby facilities',
      message: error.message
    });
  }
});

// Helper functions
async function getLocationData(location) {
  try {
    // Using a geocoding service (you'd need an API key)
    // This is a placeholder - implement with your preferred service
    const response = await axios.get(`https://api.opencagedata.com/geocode/v1/json`, {
      params: {
        q: location,
        key: process.env.GEOCODING_API_KEY,
        limit: 1
      }
    });
    
    if (response.data.results.length > 0) {
      const result = response.data.results[0];
      return {
        formatted: result.formatted,
        lat: result.geometry.lat,
        lng: result.geometry.lng,
        country: result.components.country,
        city: result.components.city || result.components.town
      };
    }
  } catch (error) {
    console.warn('Geocoding failed:', error.message);
  }
  
  return { formatted: location };
}

function createEnhancedPrompt(searchData, locationData) {
  const { location, needType, urgency, language, insurance, additionalNeeds } = searchData;
  
  return `You are a medical resource specialist helping stroke patients find care in ${location}.

CRITICAL REQUIREMENTS:
1. Find REAL medical facilities that exist
2. Include specific addresses and contact information
3. Prioritize stroke-specialized centers
4. Consider urgency level: ${urgency}
5. Account for insurance: ${insurance || 'Not specified'}

LOCATION CONTEXT:
- Search area: ${locationData.formatted || location}
- Country: ${locationData.country || 'Unknown'}
- Coordinates: ${locationData.lat ? `${locationData.lat}, ${locationData.lng}` : 'Not available'}

SEARCH CRITERIA:
- Need type: ${needType}
- Language preference: ${language}
- Additional needs: ${additionalNeeds || 'None specified'}
- Urgency: ${urgency}

RESPONSE FORMAT (JSON only, no markdown):
{
  "success": true,
  "facilities": [
    {
      "id": "unique_id",
      "name": "Real facility name",
      "address": "Complete address",
      "phone": "Phone number",
      "website": "Website URL if available",
      "type": "hospital/clinic/rehabilitation_center",
      "specialties": ["stroke_care", "rehabilitation", "emergency"],
      "services": ["Detailed list of services"],
      "distance": "Distance from search location",
      "rating": "Quality rating if available",
      "emergency_capable": true/false,
      "stroke_certified": true/false,
      "insurance_accepted": ["List of accepted insurance"],
      "languages": ["Languages spoken"],
      "hours": "Operating hours",
      "notes": "Special considerations"
    }
  ],
  "emergency_info": {
    "local_emergency": "Emergency number",
    "stroke_hotline": "Stroke-specific emergency line",
    "nearest_stroke_center": "Closest certified stroke center"
  },
  "travel_info": {
    "nearest_major_city": "If rural area",
    "transport_options": ["ambulance", "helicopter", "ground"],
    "estimated_travel_times": "Travel time estimates"
  },
  "insurance_notes": "Insurance-specific guidance",
  "language_support": "Language support availability",
  "additional_resources": [
    {
      "name": "Resource name",
      "type": "support_group/online_service/etc",
      "description": "What they provide",
      "contact": "Contact information"
    }
  ]
}

Find at least 3-5 facilities for major cities, 2-3 for smaller cities. Research real hospitals in ${location}.`;
}

async function parseAIResponse(aiResponse, searchData) {
  try {
    // Clean the response
    let cleanResponse = aiResponse
      .replace(/```json\n?/g, '')
      .replace(/\n?```/g, '')
      .replace(/^\*\*.*?\*\*$/gm, '')
      .trim();
    
    const jsonStart = cleanResponse.indexOf('{');
    const jsonEnd = cleanResponse.lastIndexOf('}') + 1;
    
    if (jsonStart !== -1 && jsonEnd > jsonStart) {
      cleanResponse = cleanResponse.substring(jsonStart, jsonEnd);
    }
    
    const parsed = JSON.parse(cleanResponse);
    
    // Validate and enhance the response
    if (!parsed.facilities || !Array.isArray(parsed.facilities)) {
      parsed.facilities = [];
    }
    
    // Add metadata
    parsed.query = searchData;
    parsed.generated_at = new Date().toISOString();
    
    return parsed;
    
  } catch (error) {
    console.error('Failed to parse AI response:', error);
    return createFallbackResponse(searchData, aiResponse);
  }
}

function createFallbackResponse(searchData, rawResponse) {
  return {
    success: false,
    query: searchData,
    facilities: [],
    emergency_info: {
      local_emergency: "Call local emergency services",
      stroke_hotline: "Contact nearest hospital"
    },
    fallback_data: {
      raw_ai_response: rawResponse,
      suggested_actions: [
        "Contact your local health department",
        "Search online for hospitals in your area",
        "Call your insurance provider for covered facilities"
      ]
    },
    generated_at: new Date().toISOString()
  };
}

async function enrichSearchResults(response, locationData) {
  // Add distance calculations, ratings, real-time availability if APIs available
  // This is where you'd integrate with real medical facility databases
  
  if (response.facilities) {
    response.facilities = response.facilities.map(facility => ({
      ...facility,
      verified: false, // Would be true if verified against real database
      last_updated: new Date().toISOString()
    }));
  }
  
  return response;
}

async function findNearbyFacilities(lat, lng, radius, type) {
  // Implement integration with Places API, health facility databases, etc.
  // This is a placeholder implementation
  
  return [
    {
      name: "Example Medical Center",
      distance: "2.3 km",
      type: type,
      coordinates: { lat: parseFloat(lat) + 0.01, lng: parseFloat(lng) + 0.01 }
    }
  ];
}

module.exports = router;

// =======================
// SRC/MIDDLEWARE/VALIDATION.JS
// =======================

const validateSearchInput = (req, res, next) => {
  const { location, needType } = req.body;
  
  // Required fields
  if (!location || location.trim().length === 0) {
    return res.status(400).json({
      success: false,
      error: 'Location is required',
      field: 'location'
    });
  }
  
  if (!needType || needType.trim().length === 0) {
    return res.status(400).json({
      success: false,
      error: 'Need type is required',
      field: 'needType'
    });
  }
  
  // Sanitize inputs
  req.body.location = location.trim();
  req.body.needType = needType.trim();
  
  if (req.body.additionalNeeds) {
    req.body.additionalNeeds = req.body.additionalNeeds.trim();
  }
  
  // Validate urgency level
  const validUrgency = ['emergency', 'urgent', 'scheduled'];
  if (req.body.urgency && !validUrgency.includes(req.body.urgency)) {
    req.body.urgency = 'scheduled';
  }
  
  next();
};

module.exports = { validateSearchInput };

// =======================
// SRC/SERVICES/CACHE.JS
// =======================

class SimpleCache {
  constructor() {
    this.cache = new Map();
    this.timers = new Map();
  }
  
  set(key, value, ttl = 600000) { // Default 10 minutes
    // Clear existing timer
    if (this.timers.has(key)) {
      clearTimeout(this.timers.get(key));
    }
    
    this.cache.set(key, value);
    
    // Set expiration timer
    const timer = setTimeout(() => {
      this.cache.delete(key);
      this.timers.delete(key);
    }, ttl);
    
    this.timers.set(key, timer);
  }
  
  get(key) {
    return this.cache.get(key);
  }
  
  delete(key) {
    if (this.timers.has(key)) {
      clearTimeout(this.timers.get(key));
      this.timers.delete(key);
    }
    this.cache.delete(key);
  }
  
  clear() {
    this.timers.forEach(timer => clearTimeout(timer));
    this.cache.clear();
    this.timers.clear();
  }
  
  size() {
    return this.cache.size;
  }
}

const searchCache = new SimpleCache();

module.exports = { searchCache };

// =======================
// SRC/SERVICES/LOGGER.JS
// =======================

const fs = require('fs').promises;
const path = require('path');

const logSearch = async (searchData, ip) => {
  try {
    const logEntry = {
      timestamp: new Date().toISOString(),
      ip: ip,
      location: searchData.location,
      needType: searchData.needType,
      urgency: searchData.urgency
    };
    
    const logLine = JSON.stringify(logEntry) + '\n';
    const logFile = path.join(__dirname, '../../logs/searches.log');
    
    // Ensure logs directory exists
    await fs.mkdir(path.dirname(logFile), { recursive: true });
    await fs.appendFile(logFile, logLine);
    
  } catch (error) {
    console.error('Failed to log search:', error);
  }
};

module.exports = { logSearch };

// =======================
// UPDATED PACKAGE.JSON
// =======================

{
  "name": "cereflow-backend",
  "version": "2.0.0",
  "description": "Enhanced backend for CereFlow stroke resources",
  "main": "server.js",
  "scripts": {
    "start": "node server.js",
    "dev": "nodemon server.js",
    "test": "node test-simple.js",
    "logs": "tail -f logs/searches.log"
  },
  "dependencies": {
    "@google/generative-ai": "^0.2.1",
    "axios": "^1.9.0",
    "cors": "^2.8.5",
    "dotenv": "^16.3.1",
    "express": "^4.18.2",
    "express-rate-limit": "^7.1.5"
  },
  "devDependencies": {
    "nodemon": "^3.0.1"
  }
}

// =======================
// .ENV TEMPLATE
// =======================

# API Keys
GEMINI_API_KEY=your_gemini_api_key_here
GEOCODING_API_KEY=your_geocoding_api_key_here

# Server Configuration
PORT=3000
NODE_ENV=development
FRONTEND_URL=http://localhost:3000

# Rate Limiting
RATE_LIMIT_WINDOW_MS=900000
RATE_LIMIT_MAX_REQUESTS=100
SEARCH_RATE_LIMIT_MAX=10