const axios = require('axios');

async function testSearch() {
  try {
    const response = await axios.post('http://localhost:3000/api/search', {
      location: "Nashville, TN",
      needType: "rehabilitation",
      insurance: "Medicare",
      additionalNeeds: "Speech therapy needed"
    });
    
    console.log('✅ Search endpoint working!');
    console.log('Response:', JSON.stringify(response.data, null, 2));
  } catch (error) {
    console.log('❌ Search endpoint failed:', error.message);
  }
}

testSearch();