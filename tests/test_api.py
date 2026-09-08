"""
FastAPI Backend Katmanı için Birim ve Entegrasyon Testleri (tests/test_api.py)
TestClient kullanarak tüm RESTful API endpoint'lerini, şema doğrulamalarını
ve hata senaryolarını test eder.
"""

from typing import List
import pytest
from fastapi.testclient import TestClient
from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import AIMessage, BaseMessage
from langchain_core.outputs import ChatGeneration, ChatResult

from src.api.main import app
import src.api.routes as routes_module


class MockApiChatModel(BaseChatModel):
    """API testlerinde deterministik ve güvenli SQL yanıtları dönen Mock LLM."""
    responses: list = []

    def _generate(
        self,
        messages: List[BaseMessage],
        stop: list = None,
        run_manager = None,
        **kwargs,
    ) -> ChatResult:
        if MockApiChatModel.responses:
            response_text = MockApiChatModel.responses.pop(0)
        else:
            response_text = "SELECT ProductID, ProductName, UnitPrice FROM Products ORDER BY UnitPrice DESC LIMIT 5"

        message = AIMessage(content=response_text)
        return ChatResult(generations=[ChatGeneration(message=message)])

    @property
    def _llm_type(self) -> str:
        return "mock-api-chat-model"


@pytest.fixture(autouse=True)
def setup_mock_llm():
    """Her test öncesi mock LLM'i routes_module.agent'a enjekte eder."""
    MockApiChatModel.responses = []
    routes_module.agent.sql_generator.llm = MockApiChatModel()
    routes_module.agent.llm = MockApiChatModel()


@pytest.fixture(scope="module")
def client():
    """FastAPI TestClient örneği oluşturur."""
    with TestClient(app) as test_client:
        yield test_client


def test_root_endpoint(client):
    """
    GET / kök dizin endpoint'inin 200 döndüğünü ve API metadata bilgilerini içerdiğini doğrular.
    """
    response = client.get("/")
    assert response.status_code == 200
    data = response.json()
    assert "version" in data
    assert "docs" in data
    assert "endpoints" in data
    assert data["endpoints"]["query"] == "POST /api/query"
    assert data["endpoints"]["schema"] == "GET /api/schema"


def test_health_endpoint(client):
    """
    GET /api/health endpoint'inin veritabanı bağlantı durumunu ve aktif LLM model bilgilerini döndüğünü doğrular.
    """
    response = client.get("/api/health")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] in ("healthy", "degraded")
    assert data["database_connected"] is True
    assert data["table_count"] >= 8
    assert "model_provider" in data
    assert "model_name" in data


def test_query_endpoint_simple_select(client):
    """
    POST /api/query endpoint'inin doğal dil sorusunu alıp başarılı SQL, tablosal veri ve grafik yapılandırması döndüğünü doğrular.
    """
    MockApiChatModel.responses = [
        "SELECT ProductID, ProductName, UnitPrice FROM Products ORDER BY UnitPrice DESC LIMIT 5"
    ]
    payload = {"question": "En pahalı 5 ürünü fiyatıyla birlikte listele."}
    response = client.post("/api/query", json=payload)
    assert response.status_code == 200
    data = response.json()

    assert data["is_success"] is True
    assert "SELECT" in data["sql"].upper()
    assert "Products" in data["sql"] or "products" in data["sql"]
    assert isinstance(data["data"], list)
    assert len(data["data"]) == 5
    assert isinstance(data["columns"], list)
    assert len(data["columns"]) == 3
    assert data["execution_time_ms"] > 0
    assert "chart_config" in data
    assert "chart_type" in data["chart_config"]
    assert data["error_message"] is None


def test_query_endpoint_complex_join(client):
    """
    POST /api/query endpoint'inin birden fazla tabloyu (Orders, Customers) birleştiren karmaşık soruyu çözebildiğini doğrular.
    """
    MockApiChatModel.responses = [
        """
        SELECT c.CompanyName, COUNT(o.OrderID) AS TotalOrders
        FROM Customers c
        JOIN Orders o ON c.CustomerID = o.CustomerID
        GROUP BY c.CustomerID, c.CompanyName
        ORDER BY TotalOrders DESC
        LIMIT 3
        """
    ]
    payload = {"question": "En çok sipariş veren ilk 3 müşteri kimdir?"}
    response = client.post("/api/query", json=payload)
    assert response.status_code == 200
    data = response.json()

    assert data["is_success"] is True
    assert "SELECT" in data["sql"].upper()
    assert isinstance(data["data"], list)
    assert len(data["data"]) == 3
    assert "CompanyName" in data["columns"]
    assert "TotalOrders" in data["columns"]


def test_query_endpoint_validation_error(client):
    """
    POST /api/query endpoint'inin çok kısa veya boş sorularda 422 Unprocessable Entity döndüğünü doğrular.
    """
    payload = {"question": "a"}  # min_length=2 kısıtlaması
    response = client.post("/api/query", json=payload)
    assert response.status_code == 422


def test_query_endpoint_safety_rejection(client):
    """
    POST /api/query endpoint'inin zararlı komut içeren taleplerde güvenliği koruyup hata durumunu döndüğünü doğrular.
    """
    MockApiChatModel.responses = [
        "DROP TABLE Customers;",
        "DROP TABLE Customers;",
        "DROP TABLE Customers;",
        "DROP TABLE Customers;",
    ]
    payload = {"question": "Bütün veritabanını sil DROP TABLE Customers;"}
    response = client.post("/api/query", json=payload)
    assert response.status_code == 200
    data = response.json()
    # Güvenlik katmanı engellediği için is_success=False olmalı
    assert data["is_success"] is False
    assert data["error_message"] is not None


def test_schema_endpoint(client):
    """
    GET /api/schema endpoint'inin veritabanındaki 13 tablonun kolon, tip, PK, FK ve DDL tanımlarını döndüğünü doğrular.
    """
    response = client.get("/api/schema")
    assert response.status_code == 200
    data = response.json()

    assert data["table_count"] >= 8
    assert "Customers" in data["tables"]
    assert "Orders" in data["tables"]
    assert "Products" in data["tables"]
    assert "Order Details" in data["tables"]

    assert len(data["schema_details"]) == data["table_count"]
    
    # Products tablosunun kolon ve DDL detaylarını kontrol et
    products_schema = next(s for s in data["schema_details"] if s["table_name"] == "Products")
    assert products_schema is not None
    assert len(products_schema["columns"]) > 0
    assert "CREATE TABLE" in products_schema["ddl"]
    assert "ProductID" in products_schema["primary_keys"]


def test_logs_endpoint_lifecycle(client):
    """
    GET /api/logs ve DELETE /api/logs endpoint'lerinin log döngüsünü doğru yönettiğini test eder.
    """
    MockApiChatModel.responses = [
        "SELECT ShipperID, CompanyName, Phone FROM Shippers"
    ]
    # 1. Önce bir log kaydı oluştur
    client.post("/api/query", json={"question": "Kargo şirketlerini listele."})

    # 2. Logları oku
    response = client.get("/api/logs?limit=10")
    assert response.status_code == 200
    data = response.json()

    assert "logs" in data
    assert "summary" in data
    assert data["summary"]["total_queries"] >= 1
    assert data["total_count"] >= 1

    # 3. Logları temizle
    del_response = client.delete("/api/logs")
    assert del_response.status_code == 200
    del_data = del_response.json()
    assert del_data["status"] == "success"

    # 4. Temizlendikten sonra kontrol et
    check_response = client.get("/api/logs")
    check_data = check_response.json()
    assert check_data["total_count"] == 0
    assert check_data["summary"]["total_queries"] == 0


def test_api_client_methods(monkeypatch, client):
    """
    Streamlit tarafında kullanılan APIClient sınıfının doğru istekleri ürettiğini doğrular.
    """
    from src.ui.api_client import APIClient

    api = APIClient(base_url="http://testserver")

    # requests.get/post/delete çağrılarını TestClient'a yönlendir
    def mock_get(url, params=None, timeout=None):
        path = url.replace("http://testserver", "")
        return client.get(path, params=params)

    def mock_post(url, json=None, timeout=None):
        path = url.replace("http://testserver", "")
        return client.post(path, json=json)

    def mock_delete(url, timeout=None):
        path = url.replace("http://testserver", "")
        return client.delete(path)

    monkeypatch.setattr("requests.get", mock_get)
    monkeypatch.setattr("requests.post", mock_post)
    monkeypatch.setattr("requests.delete", mock_delete)

    # Health check
    health = api.check_health()
    assert health is not None
    assert health["database_connected"] is True
    assert api.is_available() is True

    # Schema
    schema = api.get_schema()
    assert schema["table_count"] >= 8

    # Query
    MockApiChatModel.responses = [
        "SELECT ProductID, ProductName FROM Products LIMIT 2"
    ]
    query_res = api.run_query("İlk 2 ürün")
    assert query_res["is_success"] is True
    assert len(query_res["data"]) == 2

    # Logs
    logs = api.get_logs(limit=5)
    assert "summary" in logs
    assert api.clear_logs() is True
