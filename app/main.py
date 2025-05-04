# app/main.py
from fastapi import FastAPI, HTTPException, Query
from pydantic import BaseModel
from datetime import date, datetime, timedelta
from collections import Counter
from firebase_admin import firestore

from app.model import analyze_emotion
from app.utils import save_entry, db

app = FastAPI(title="Öğrenci Duygu Günlüğü API")


# --- Pydantic modelleri ---

class EntryIn(BaseModel):
    student_id: str
    class_id:   str    # Kullanıcının girdiği sınıf ID
    date:       str    # "YYYY-MM-DD" veya "MM-DD-YYYY"
    text:       str

class EntryOut(BaseModel):
    student_id: str
    class_id:   str
    date:       str
    text:       str
    emotion:    str
    score:      float
    suggestion: str

class ClassEntries(BaseModel):
    class_id: str
    entries:  list[EntryOut]


# --- Analiz & Kayıt Endpoint’i ---

@app.post(
    "/analyze",
    response_model=EntryOut,
    summary="Günlük duygu analizi ve öneri üret",
    description="""
    Kullanıcının gönderdiği metni analiz eder, duygusunu belirler,
    rastgele bir öneri seçer ve veritabanına kaydeder.
    Ayrıca öğrenci ve sınıf kayıtlarını günceller.
    """
)
def analyze(entry: EntryIn):
    res = analyze_emotion(entry.text)

    # 1) Root 'entries' koleksiyonuna kaydet
    save_entry({
        "student_id": entry.student_id,
        "date":       entry.date,
        "text":       entry.text,
        "emotion":    res["emotion"],
        "score":      res["score"],
        "suggestion": res["suggestion"]
    })

    # 2) Sınıf belgesini oluştur/merge et
    cls_ref = db.collection("classes").document(entry.class_id)
    cls_ref.set({}, merge=True)

    # 3) Öğrenci belgesini oluştur/merge et ve en son girdiyi ekle
    student_ref = cls_ref.collection("students").document(entry.student_id)
    student_ref.set({}, merge=True)
    # Öğrenci belgesine son girdi bilgilerini ekliyoruz
    student_ref.set({
        "last_entry": {
            "date":       entry.date,
            "text":       entry.text,
            "emotion":    res["emotion"],
            "score":      res["score"],
            "suggestion": res["suggestion"]
        }
    }, merge=True)

    return EntryOut(
        student_id= entry.student_id,
        class_id=   entry.class_id,
        date=       entry.date,
        text=       entry.text,
        emotion=    res["emotion"],
        score=      res["score"],
        suggestion= res["suggestion"]
    )


# --- Öğrencinin Geçmiş Girdilerini Listeleme ---

@app.get(
    "/entries/{student_id}",
    summary="Öğrenci günlük girdilerini listele",
    description="Verilen öğrenci kimliğine ait tüm günlük duygu kayıtlarını döner."
)
def list_entries(student_id: str):
    docs = list(
        db.collection("entries")
          .document(student_id)
          .collection("daily")
          .stream()
    )
    if not docs:
        raise HTTPException(404, "Öğrenci bulunamadı veya hiç giriş yapmamış.")
    return [d.to_dict() for d in docs]


# --- Sınıfa Ait Tüm Girdileri Listeleme ---

@app.get(
    "/classes/{class_id}/entries",
    response_model=ClassEntries,
    summary="Sınıfa ait tüm öğrenci girdilerini listele",
    description="""
    Verilen sınıf kimliğindeki tüm öğrencilerin günlük duygu
    kayıtlarını bir arada döner.
    """
)
def class_entries(class_id: str):
    docs = db.collection("classes") \
             .document(class_id) \
             .collection("students") \
             .stream()
    student_ids = [d.id for d in docs]
    if not student_ids:
        raise HTTPException(404, "Sınıf bulunamadı veya öğrenci yok.")

    entries = []
    for sid in student_ids:
        for doc in db.collection("entries").document(sid).collection("daily").stream():
            data = doc.to_dict()
            entries.append(EntryOut(
                student_id= sid,
                class_id=   class_id,
                date=       data.get("date", doc.id),
                text=       data.get("text", ""),
                emotion=    data.get("emotion", ""),
                score=      data.get("score", 0.0),
                suggestion= data.get("suggestion", "")
            ))
    entries.sort(key=lambda e:
        datetime.strptime(e.date, "%Y-%m-%d") if "-" in e.date else datetime.strptime(e.date, "%m-%d-%Y")
    )
    return ClassEntries(class_id=class_id, entries=entries)


# --- Öğretmen Dashboard: Haftalık Duygu Dağılımı ---

@app.get(
    "/stats/class/{class_id}",
    summary="Sınıf duygu istatistikleri",
    description="""
    Verilen sınıf kimliğindeki öğrencilerin son 7 gündeki
    Pozitif, Nötr ve Negatif giriş sayısını döner.
    """
)
def class_stats(
    class_id: str,
    start_date: str | None = Query(None, description="YYYY-MM-DD formatında başlangıç tarihi"),
    end_date:   str | None = Query(None, description="YYYY-MM-DD formatında bitiş tarihi")
):
    docs = db.collection("classes") \
             .document(class_id) \
             .collection("students") \
             .stream()
    student_ids = [d.id for d in docs]
    if not student_ids:
        raise HTTPException(404, "Sınıf bulunamadı veya öğrenci yok.")

    today = date.today()
    week_ago = today - timedelta(days=6)
    counter = Counter()

    for sid in student_ids:
        for doc in db.collection("entries").document(sid).collection("daily").stream():
            data = doc.to_dict()
            raw_date = data.get("date", doc.id)
            try:
                entry_date = datetime.strptime(raw_date, "%Y-%m-%d").date()
            except ValueError:
                try:
                    entry_date = datetime.strptime(raw_date, "%m-%d-%Y").date()
                except ValueError:
                    continue
            if week_ago <= entry_date <= today:
                emo = data.get("emotion", "neutral")
                counter[emo.capitalize()] += 1

    return {
        "class_id": class_id,
        "period":   f"{week_ago.isoformat()} to {today.isoformat()}",
        "counts": {
            "Pozitif": counter.get("Positive", 0),
            "Nötr":    counter.get("Neutral", 0),
            "Negatif": counter.get("Negative", 0),
        }
    }


# --- Öğretmen Dashboard: Risk Altındaki Öğrenciler ---

@app.get(
    "/at-risk/class/{class_id}",
    summary="Risk altındaki öğrencileri listele",
    description="""
    Peş peşe en az 3 gün Negatif duygu girişi yapmış
    öğrencilerin kimliklerini döner.
    """
)
def at_risk(
    class_id: str,
    start_date: str | None = Query(
        None,
        description="YYYY-MM-DD formatında başlangıç tarihi. Belirtilmezse en eski kayıt alınır."
    ),
    end_date:   str | None = Query(
        None,
        description="YYYY-MM-DD formatında bitiş tarihi. Belirtilmezse bugüne kadar alır."
    )
):
    # 1) Sınıftaki öğrenci ID’lerini al
    docs = db.collection("classes") \
             .document(class_id) \
             .collection("students") \
             .stream()
    student_ids = [d.id for d in docs]
    if not student_ids:
        raise HTTPException(404, "Sınıf bulunamadı veya öğrenci yok.")

    # 2) Tarih parametrelerini parse et
    today = date.today()
    try:
        start = datetime.strptime(start_date, "%Y-%m-%d").date() if start_date else date.min
        end   = datetime.strptime(end_date,   "%Y-%m-%d").date() if end_date   else today
    except ValueError:
        raise HTTPException(400, "start_date ve end_date YYYY-MM-DD formatında olmalı")

    at_risk = []
    for sid in student_ids:
        # 3) Öğrencinin tüm günlük girdilerini topla
        raw_entries = []
        for doc in db.collection("entries").document(sid).collection("daily").stream():
            data     = doc.to_dict()
            raw_date = data.get("date", doc.id)
            # Tarihi parse et
            try:
                d_obj = datetime.strptime(raw_date, "%Y-%m-%d").date()
            except ValueError:
                try:
                    d_obj = datetime.strptime(raw_date, "%m-%d-%Y").date()
                except ValueError:
                    continue
            # sadece start ≤ date ≤ end aralığındaki kayıtları al
            if start <= d_obj <= end:
                raw_entries.append((d_obj, data.get("emotion", "")))

        # 4) Tarihe göre sırala ve 3 gün art arda “negative” kontrolü yap
        raw_entries.sort(key=lambda x: x[0])
        streak = 0
        for _, emo in raw_entries:
            if emo == "negative":
                streak += 1
                if streak >= 3:
                    at_risk.append(sid)
                    break
            else:
                streak = 0

    return {
        "class_id":        class_id,
        "start_date":      start.isoformat(),
        "end_date":        end.isoformat(),
        "at_risk_students": at_risk
    }