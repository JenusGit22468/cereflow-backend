const axios = require("axios");

async function testBackend() {
  try {
    console.log("Testing backend...");
    
    const response = await axios.post("http://localhost:3000/api/search", {
      location: "London, UK",
      needType: "rehabilitation",
      insurance: "NHS",
      additionalNeeds: "Speech therapy"
    });
    
    console.log("✅ SUCCESS!");
    console.log("Raw AI Response:");
    console.log(JSON.stringify(response.data, null, 2));
    
  } catch (error) {
    console.log("❌ FAILED:");
    console.log("Error:", error.message);
    if (error.response) {
      console.log("Status:", error.response.status);
      console.log("Data:", error.response.data);
    }
  }
}

testBackend();
