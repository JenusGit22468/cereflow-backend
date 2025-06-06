const { GoogleGenerativeAI } = require('@google/generative-ai');
require('dotenv').config();

async function testGemini() {
  try {
    console.log('API Key:', process.env.GEMINI_API_KEY ? 'Found' : 'Missing');
    
    const genAI = new GoogleGenerativeAI(process.env.GEMINI_API_KEY);
    const model = genAI.getGenerativeModel({ model: "gemini-1.5-flash" });
    
    const prompt = "Say hello from CereFlow!";
    const result = await model.generateContent(prompt);
    
    console.log('✅ Gemini API working!');
    console.log('Response:', result.response.text());
  } catch (error) {
    console.log('❌ Gemini API failed:', error.message);
  }
}

testGemini();