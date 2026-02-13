import os
import sys
sys.path.insert(0, os.path.dirname(__file__))

from dotenv import load_dotenv
load_dotenv()

api_key = os.getenv('GOOGLE_API_KEY', '')
from google import genai
from google.genai import types

client = genai.Client(api_key=api_key)

print("=== Test Gemini 2.5 Flash Image ===")
try:
    response = client.models.generate_content(
        model="gemini-2.5-flash-image",
        contents=["Generate an image: professional illustration for LinkedIn about teamwork"],
        config=types.GenerateContentConfig(
            response_modalities=["TEXT", "IMAGE"],
        )
    )
    for part in response.candidates[0].content.parts:
        if part.inline_data:
            print(f"SUCCESS! mime={part.inline_data.mime_type}, size={len(part.inline_data.data)}")
        elif part.text:
            print(f"Text: {part.text[:200]}")
except Exception as e:
    print(f"Error: {e}")
