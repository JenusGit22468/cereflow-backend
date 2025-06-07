// Load environment variables
require('dotenv').config();

// Import required packages
const express = require('express');
const cors = require('cors');

// Create Express app
const app = express();
const PORT = process.env.PORT || 5000;

// Middleware
app.use(cors()); // Allows your frontend to talk to backend
app.use(express.json()); // Allows handling JSON data

// Basic test route
app.get('/', (req, res) => {
  res.json({ message: 'CereFlow Backend is running!' });
});

// Import search routes
const searchRoutes = require('./search');
app.use('/api', searchRoutes);

// Start server
app.listen(PORT, () => {
  console.log(`Server running on http://localhost:${PORT}`);
});