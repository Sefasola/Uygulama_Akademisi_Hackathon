# app/utils.py
import os
from dotenv import load_dotenv
import firebase_admin
from firebase_admin import credentials, firestore

# .env dosyasını yükle
load_dotenv()

# Service account anahtarını al ve Firebase Admin SDK'yı başlat
cred_path = os.getenv("FIREBASE_CRED", "serviceAccountKey.json")
cred = credentials.Certificate(cred_path)
firebase_admin.initialize_app(cred)

# Firestore istemcisi
db = firestore.client()

def save_entry(entry: dict):
    """
    entry dict örneği:
    {
      "student_id": "...",
      "date": "YYYY-MM-DD",
      "text": "...",
      "emotion": "...",
      "score": 0.95,
      "suggestion": "..."
    }
    """
    student_id = entry["student_id"]
    date = entry["date"]
    db \
      .collection("entries") \
      .document(student_id) \
      .collection("daily") \
      .document(date) \
      .set(entry)
