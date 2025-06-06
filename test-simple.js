const axios = require("axios");

async function testSimple() {
  try {
    console.log("Testing basic connection...");
    const response = await axios.get("http://localhost:3000");
    console.log("✅ Basic connection works:", response.data);
    
    console.log("Testing search endpoint...");
    const searchResponse = await axios.post("http://localhost:3000/api/search", {
      location: "Nashville, TN",
      needType: "rehabilitation"
    });
    console.log("✅ Search works!");
    
  } catch (error) {
    console.log("❌ Error details:");
    console.log("Message:", error.message);
    console.log("Code:", error.code);
  }
}

testSimple();
