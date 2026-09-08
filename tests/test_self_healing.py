"""
Self-Healing SQL Mekanizması (SQLSelfHealingAgent) için birim ve entegrasyon testleri.
"""

from typing import List
import pandas as pd
import pytest
from langchain_core.messages import AIMessage, BaseMessage
from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.outputs import ChatGeneration, ChatResult

from src.ai.few_shot_manager import FewShotManager
from src.ai.schema_manager import SchemaManager
from src.ai.sql_generator import SQLGenerator
from src.ai.sql_healing import SQLSelfHealingAgent, QueryExecutionError
from src.core.database import engine


class MockHealingChatModel(BaseChatModel):
    """
    Test senaryolarında aşamalı olarak (önce hatalı sonra düzeltilmiş)
    SQL yanıtları dönen akıllı Mock Chat Model.
    """
    call_count: int = 0
    responses: list = []

    def _generate(
        self,
        messages: List[BaseMessage],
        stop: list = None,
        run_manager = None,
        **kwargs,
    ) -> ChatResult:
        MockHealingChatModel.call_count += 1
        
        # Sıradaki cevabı ver
        if MockHealingChatModel.responses:
            response_text = MockHealingChatModel.responses.pop(0)
        else:
            response_text = "SELECT 1"

        message = AIMessage(content=response_text)
        return ChatResult(generations=[ChatGeneration(message=message)])

    @property
    def _llm_type(self) -> str:
        return "mock-healing-chat-model"


@pytest.fixture(autouse=True)
def reset_mock():
    """Her test öncesi mock durumunu sıfırlar."""
    MockHealingChatModel.call_count = 0
    MockHealingChatModel.responses = []


# ---------------------------------------------------------------------------
# 1. Başarılı İlk Deneme Testi
# ---------------------------------------------------------------------------

def test_healing_successful_on_first_try():
    """İlk denemede doğru SQL üretildiğinde tamir döngüsüne girmeden sonuç döndüğünü doğrular."""
    MockHealingChatModel.responses = [
        "SELECT ProductID, ProductName, UnitPrice FROM Products ORDER BY UnitPrice DESC LIMIT 5"
    ]
    mock_llm = MockHealingChatModel()
    agent = SQLSelfHealingAgent(llm=mock_llm)

    df, final_sql, history = agent.execute_with_healing("En pahalı 5 ürün")

    assert isinstance(df, pd.DataFrame)
    assert len(df) == 5
    assert "UnitPrice" in df.columns
    assert MockHealingChatModel.call_count == 1
    assert any("[Başarılı]" in h for h in history)


# ---------------------------------------------------------------------------
# 2. Hatalı Kolon İsminden Kendi Kendini Tamir Etme Testi
# ---------------------------------------------------------------------------

def test_healing_recovers_from_invalid_column():
    """
    1. Deneme: Hatalı kolon ('Price') içerir ve sqlite3 'no such column' hatası verir.
    2. Deneme (Healing): Hata yakalanır ve doğru kolon ('UnitPrice') ile sorgu düzeltilip çalıştırılır.
    """
    MockHealingChatModel.responses = [
        "SELECT ProductName, Price FROM Products",  # Hatalı: 'Price' kolonu yok ('UnitPrice' olmalı)
        "SELECT ProductName, UnitPrice FROM Products LIMIT 5",  # Düzeltilmiş doğru SQL
    ]
    mock_llm = MockHealingChatModel()
    agent = SQLSelfHealingAgent(llm=mock_llm, max_retries=3)

    df, final_sql, history = agent.execute_with_healing("Ürünlerin fiyatlarını listele")

    assert isinstance(df, pd.DataFrame)
    assert len(df) == 5
    assert "UnitPrice" in df.columns
    assert MockHealingChatModel.call_count == 2
    
    # Geçmişin hatayı ve düzeltmeyi kaydettiğini doğrula
    assert any("no such column: Price" in h for h in history)
    assert any("[Deneme 2] Düzeltilmiş SQL üretildi" in h for h in history)
    assert any("[Başarılı]" in h for h in history)


# ---------------------------------------------------------------------------
# 3. Tırnaksız Tablo İsminden (Order Details) Tamir Etme Testi
# ---------------------------------------------------------------------------

def test_healing_recovers_from_unquoted_table_name():
    """
    1. Deneme: Boşluklu tablo adını tırnaksız yazar (SELECT * FROM Order Details -> Syntax Error).
    2. Deneme (Healing): LLM tabloyu '"Order Details"' şeklinde tırnaklar ve sorgu başarıyla döner.
    """
    MockHealingChatModel.responses = [
        "SELECT OrderID, Quantity FROM Order Details LIMIT 5",  # Hatalı: tırnaksız boşluklu isim
        'SELECT OrderID, Quantity FROM "Order Details" LIMIT 5',  # Düzeltilmiş
    ]
    mock_llm = MockHealingChatModel()
    agent = SQLSelfHealingAgent(llm=mock_llm, max_retries=3)

    df, final_sql, history = agent.execute_with_healing("Sipariş detaylarından 5 kayıt getir")

    assert isinstance(df, pd.DataFrame)
    assert len(df) == 5
    assert "Quantity" in df.columns
    assert MockHealingChatModel.call_count == 2
    assert '"Order Details"' in final_sql


# ---------------------------------------------------------------------------
# 4. Maksimum Deneme Sayısı Aşımı Testi
# ---------------------------------------------------------------------------

def test_healing_max_retries_exceeded_raises_query_execution_error():
    """Tüm denemelerde hata veren düzeltilemeyen bir senaryoda QueryExecutionError fırlatıldığını doğrular."""
    # 3 deneme boyunca sürekli geçersiz tablo adı üretilsin
    MockHealingChatModel.responses = [
        "SELECT * FROM NonExistentTable1",
        "SELECT * FROM NonExistentTable2",
        "SELECT * FROM NonExistentTable3",
    ]
    mock_llm = MockHealingChatModel()
    agent = SQLSelfHealingAgent(llm=mock_llm, max_retries=3)

    with pytest.raises(QueryExecutionError) as exc_info:
        agent.execute_with_healing("Müşteri ve sipariş listesi")

    err = exc_info.value
    assert "Maksimum deneme sayısı (3) aşıldı" in str(err)
    assert len(err.attempts) > 0
    assert "NonExistentTable" in err.last_sql
    assert MockHealingChatModel.call_count == 3


# ---------------------------------------------------------------------------
# 5. Tamir Sırasında Güvenlik İhlalinin Yakalanması
# ---------------------------------------------------------------------------

def test_healing_rejects_security_violation_in_repaired_sql():
    """Tamir edilen SQL içinde zararlı bir komut (DROP vb.) varsa AST denetiminin bunu yakaladığını doğrular."""
    MockHealingChatModel.responses = [
        "SELECT * FROM BrokenTable",
        "DROP TABLE Customers",  # Zararlı tamir girişimi
        "SELECT CustomerID FROM Customers LIMIT 3",  # Nihayetinde güvenli ve doğru sorgu
    ]
    mock_llm = MockHealingChatModel()
    agent = SQLSelfHealingAgent(llm=mock_llm, max_retries=3)

    df, final_sql, history = agent.execute_with_healing("Müşterileri getir")

    assert isinstance(df, pd.DataFrame)
    assert len(df) == 3
    # 2. denemedeki güvenlik ihlalinin geçmişe kaydedildiğini doğrula
    assert any("Güvenlik İhlali" in h for h in history)
    assert MockHealingChatModel.call_count == 3
