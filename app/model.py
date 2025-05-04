# app/model.py
import os
from dotenv import load_dotenv
from transformers import AutoTokenizer, AutoModelForSequenceClassification
import torch
from torch.nn.functional import softmax
import random

# .env dosyasını yükle
load_dotenv()
hf_token = os.getenv("HUGGINGFACE_HUB_TOKEN")

# 1) Model ve tokenizer’ı yükle (Hugging Face token ile)
bert_model_name = "savasy/bert-base-turkish-sentiment-cased"
tokenizer = AutoTokenizer.from_pretrained(
    bert_model_name,
    token=hf_token
)
model = AutoModelForSequenceClassification.from_pretrained(
    bert_model_name,
    token=hf_token
)

# 2) Öneri havuzu
oneriler = {
    "positive": [
        "Bugün enerjiksin! Yeni bir konu öğrenmeye başla.",
        "Zor bir alıştırma çözmeyi dene.",
        "Kendine meydan oku: 10 soruluk mini test yap."
    ],
    "neutral": [
        "Bugün sade çalış. Önceki konuları gözden geçir.",
        "5 dakikalık kısa bir tekrar yeterli olur.",
        "Bugün bir özet çıkar, zihnin toparlanır."
    ],
    "negative": [
        "Kısa bir video izle, sonra sevdiğin konudan 1 soru çöz.",
        "Nefes egzersiziyle başla, sonra hafif bir okuma yap.",
        "Bugün kendini zorlama, 3 dakikalık tekrar yeterli."
    ]
}

def analyze_emotion(text: str) -> dict:
    """
    Metni alır, modelle inference yapar ve
    {'emotion': ..., 'score': ..., 'suggestion': ...} döner.
    """
    # Tokenize & model inference
    inputs = tokenizer(text, return_tensors="pt", truncation=True, padding=True)
    outputs = model(**inputs)
    
    # Olasılıkları hesapla
    probs = softmax(outputs.logits, dim=1)[0]
    pred = torch.argmax(probs).item()
    
    # Ham etiketi al ve üç kategoriye eşle
    raw_label = model.config.id2label[pred].lower()  # örn: "positive"
    if raw_label.startswith("pos"):
        key = "positive"
    elif raw_label.startswith("neu"):
        key = "neutral"
    else:
        key = "negative"
    
    # Sonuç sözlüğünü döndür
    return {
        "emotion": key,
        "score": float(probs[pred]),
        "suggestion": random.choice(oneriler[key])
    }
