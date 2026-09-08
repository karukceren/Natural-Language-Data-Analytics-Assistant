"""
Doğal Dil İşlemeli Akıllı Veri Analiz Asistanı - FastAPI Ana Uygulama Sunucusu (main.py)
Uygulama başlatıcı, CORS yapılandırması ve API rotalarını bağlar.
"""

from pathlib import Path
import sys

# Proje kök dizinini sys.path'e ekle
PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import uvicorn
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from src.api.routes import router as api_router
from src.core.config import settings

# FastAPI Uygulaması Tanımı
app = FastAPI(
    title="🧠 Doğal Dil İşlemeli Akıllı Veri Analiz Asistanı API",
    description=(
        "Northwind veritabanı üzerinde Türkçe/İngilizce doğal dil sorularını güvenli SQL "
        "sorgularına dönüştüren, Self-Healing ile otomatik tamir eden ve veriyi dinamik grafiklerle "
        "görselleştiren kurumsal RESTful API backend katmanı."
    ),
    version="1.0.0",
    docs_url="/docs",
    redoc_url="/redoc",
    openapi_url="/openapi.json",
)

# CORS Yapılandırması (Streamlit, Web UI ve harici istemciler için)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# API Yönlendiricisini Dahil Et
app.include_router(api_router)


@app.get("/", tags=["Kök Dizin"])
def root():
    """
    API Kök Dizin Bilgilendirme Endpoint'i.
    """
    return {
        "message": f"{settings.APP_NAME} API Katmanı Aktif",
        "version": "1.0.0",
        "docs": "/docs",
        "redoc": "/redoc",
        "health": "/api/health",
        "endpoints": {
            "query": "POST /api/query",
            "schema": "GET /api/schema",
            "logs": "GET /api/logs",
            "health": "GET /api/health",
        },
    }


if __name__ == "__main__":
    uvicorn.run(
        "src.api.main:app",
        host="0.0.0.0",
        port=8000,
        reload=True,
    )
