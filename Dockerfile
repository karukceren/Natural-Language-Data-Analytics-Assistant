# ===========================================================================
# Doğal Dil İşlemeli Akıllı Veri Analiz Asistanı - Dockerfile
# Python 3.11 tabanlı optimize konteyner yapılandırması
# ===========================================================================

FROM python:3.11-slim

# Çalışma ortamı değişkenleri
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONPATH=/app \
    DEBIAN_FRONTEND=noninteractive

# Sistem paketlerini ve bağımlılıklarını yükle
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    curl \
    sqlite3 \
    && rm -rf /var/lib/apt/lists/*

# Çalışma dizini oluştur
WORKDIR /app

# Bağımlılıkları kopyala ve kur (Docker katman önbelleği için önce requirements)
COPY requirements.txt .
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir -r requirements.txt

# Uygulama kaynak kodlarını ve veritabanını kopyala
COPY src/ /app/src/
COPY data/ /app/data/
COPY tests/ /app/tests/

# Portları dışa aç (8000: FastAPI, 8501: Streamlit)
EXPOSE 8000 8501

# Sağlık kontrolü (FastAPI için)
HEALTHCHECK --interval=30s --timeout=10s --start-period=5s --retries=3 \
    CMD curl -f http://localhost:8000/api/health || exit 1

# Varsayılan başlangıç komutu (FastAPI Backend)
CMD ["uvicorn", "src.api.main:app", "--host", "0.0.0.0", "--port", "8000"]
