import os

import requests
from dotenv import load_dotenv

load_dotenv()

api_key = os.getenv("GOOGLE_API_KEY") or os.getenv("GEMINI_API_KEY")
if not api_key:
    raise SystemExit("API key tidak ditemukan di .env (GOOGLE_API_KEY / GEMINI_API_KEY).")

resp = requests.get(
    "https://generativelanguage.googleapis.com/v1beta/models",
    params={"key": api_key, "pageSize": 200},
    timeout=20,
)
resp.raise_for_status()

names = sorted(
    m["name"].replace("models/", "")
    for m in resp.json().get("models", [])
    if "generateContent" in m.get("supportedGenerationMethods", [])
    and "gemini" in m["name"]
)

print("Model Gemini yang tersedia untuk API key Anda:\n")
for n in names:
    print(f"  {n}")
print("\nIsi GEMINI_MODEL dan GEMINI_FALLBACK_MODELS di .env dengan nama di atas.")