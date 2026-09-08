"""
Doğal Dil İşlemeli Akıllı Veri Analiz Asistanı - Streamlit UI API İstemcisi (API Client)
FastAPI backend katmanı ile HTTP üzerinden haberleşir; API çevrimdışı olduğunda
otomatik olarak yerel servis katmanına geçiş (fallback) desteği sağlar.
"""

from typing import Any, Dict, List, Optional
import requests


class APIClient:
    """
    FastAPI backend servisi ile iletişim kuran REST istemcisi.
    """

    def __init__(self, base_url: str = "http://localhost:8000", timeout: float = 60.0):
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout

    def check_health(self) -> Optional[Dict[str, Any]]:
        """
        FastAPI sunucusunun sağlık durumunu kontrol eder.
        """
        try:
            resp = requests.get(f"{self.base_url}/api/health", timeout=2.0)
            if resp.status_code == 200:
                return resp.json()
            return None
        except Exception:
            return None

    def is_available(self) -> bool:
        """
        Backend API sunucusunun aktif ve erişilebilir olup olmadığını döner.
        """
        health = self.check_health()
        return health is not None and health.get("status") in ("healthy", "degraded")

    def run_query(
        self,
        question: str,
        provider: Optional[str] = None,
        model_name: Optional[str] = None,
        api_key: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Kullanıcı sorusunu FastAPI /api/query endpoint'ine gönderir ve sonucu döner.
        """
        payload = {"question": question}
        if provider:
            payload["provider"] = provider
        if model_name:
            payload["model_name"] = model_name
        if api_key:
            payload["api_key"] = api_key

        resp = requests.post(
            f"{self.base_url}/api/query",
            json=payload,
            timeout=self.timeout,
        )
        resp.raise_for_status()
        return resp.json()

    def get_schema(self) -> Dict[str, Any]:
        """
        Veritabanı şemasını /api/schema endpoint'inden çeker.
        """
        resp = requests.get(f"{self.base_url}/api/schema", timeout=10.0)
        resp.raise_for_status()
        return resp.json()

    def get_logs(self, limit: int = 50) -> Dict[str, Any]:
        """
        Sorgu loglarını /api/logs endpoint'inden çeker.
        """
        resp = requests.get(f"{self.base_url}/api/logs", params={"limit": limit}, timeout=10.0)
        resp.raise_for_status()
        return resp.json()

    def clear_logs(self) -> bool:
        """
        Sorgu loglarını /api/logs endpoint'i üzerinden siler.
        """
        resp = requests.delete(f"{self.base_url}/api/logs", timeout=5.0)
        return resp.status_code == 200


# Singleton API istemcisi örneği
api_client = APIClient()
