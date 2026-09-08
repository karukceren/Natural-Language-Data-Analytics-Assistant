"""
SQLGenerator modülü için kapsamlı birim ve entegrasyon testleri.
"""

from typing import List
import pytest
from langchain_core.messages import AIMessage, BaseMessage
from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.outputs import ChatGeneration, ChatResult

from src.ai.schema_manager import SchemaManager
from src.ai.sql_generator import SQLGenerator, SQL_SYSTEM_PROMPT_TEMPLATE
from src.core.database import execute_read_only_query, engine


class MockChatModel(BaseChatModel):
    """
    Test ortamında harici API çağrısı yapmadan belirlenen SQL çıktılarını
    döndüren sahte (Mock) LangChain Chat Model.
    """
    mock_responses: dict = {}

    def _generate(
        self,
        messages: List[BaseMessage],
        stop: list = None,
        run_manager = None,
        **kwargs,
    ) -> ChatResult:
        # Son kullanıcı mesajından soruyu al
        last_message = messages[-1].content if messages else ""
        
        response_text = "SELECT 1"
        for q_pattern, sql in self.mock_responses.items():
            if q_pattern.lower() in last_message.lower():
                response_text = sql
                break

        message = AIMessage(content=response_text)
        generation = ChatGeneration(message=message)
        return ChatResult(generations=[generation])

    @property
    def _llm_type(self) -> str:
        return "mock-chat-model"


@pytest.fixture
def mock_llm():
    """Örnek sorular için mock SQL yanıtları yapılandırılmış LLM fixture'ı."""
    responses = {
        "En pahalı 5 ürünü": "```sql\nSELECT ProductName, UnitPrice FROM Products ORDER BY UnitPrice DESC LIMIT 5;\n```",
        "Hangi ülkelerden kaçar tane müşteri": "SELECT Country, COUNT(*) AS CustomerCount FROM Customers GROUP BY Country ORDER BY CustomerCount DESC",
        "1997 yılında en çok sipariş veren 3 müşteri": """
            SELECT c.CustomerID, c.CompanyName, COUNT(o.OrderID) AS TotalOrders
            FROM Customers c
            JOIN Orders o ON c.CustomerID = o.CustomerID
            WHERE strftime('%Y', o.OrderDate) = '1997'
            GROUP BY c.CustomerID, c.CompanyName
            ORDER BY TotalOrders DESC
            LIMIT 3
        """,
        "2016 yılında en çok sipariş veren 3 müşteri": """
            SELECT c.CustomerID, c.CompanyName, COUNT(o.OrderID) AS TotalOrders
            FROM Customers c
            JOIN Orders o ON c.CustomerID = o.CustomerID
            WHERE strftime('%Y', o.OrderDate) = '2016'
            GROUP BY c.CustomerID, c.CompanyName
            ORDER BY TotalOrders DESC
            LIMIT 3
        """,
        "Tehlikeli Soru": "DROP TABLE Customers;",
    }
    return MockChatModel(mock_responses=responses)


@pytest.fixture
def sql_generator(mock_llm):
    """Mock LLM ile donatılmış SQLGenerator fixture'ı."""
    schema_mgr = SchemaManager(engine=engine)
    return SQLGenerator(schema_manager=schema_mgr, llm=mock_llm)


# ---------------------------------------------------------------------------
# Birim Testleri: SQL Temizleme (clean_sql_output)
# ---------------------------------------------------------------------------

def test_clean_sql_output_markdown_block():
    """Markdown bloklarını temizlediğini doğrular."""
    raw = "```sql\nSELECT * FROM Products WHERE UnitPrice > 50;\n```"
    cleaned = SQLGenerator.clean_sql_output(raw)
    assert cleaned == "SELECT * FROM Products WHERE UnitPrice > 50"


def test_clean_sql_output_prefixes_and_semicolons():
    """Ön ekleri ('SQL:', 'Query:') ve sondaki noktalı virgülleri temizlediğini doğrular."""
    raw1 = "SQL: SELECT CustomerID FROM Customers;"
    assert SQLGenerator.clean_sql_output(raw1) == "SELECT CustomerID FROM Customers"

    raw2 = "Query:   SELECT OrderID FROM Orders ;  "
    assert SQLGenerator.clean_sql_output(raw2) == "SELECT OrderID FROM Orders"


# ---------------------------------------------------------------------------
# Birim Testleri: Güvenlik Filtresi (validate_safety)
# ---------------------------------------------------------------------------

def test_validate_safety_valid_select():
    """Geçerli SELECT ve WITH (CTE) sorgularının güvenlik testini geçtiğini doğrular."""
    safe_query1 = "SELECT ProductName, UnitPrice FROM Products WHERE UnitPrice > 20"
    is_safe, err = SQLGenerator.validate_safety(safe_query1)
    assert is_safe is True
    assert err is None

    safe_query2 = "WITH TopOrders AS (SELECT OrderID FROM Orders) SELECT * FROM TopOrders"
    is_safe, err = SQLGenerator.validate_safety(safe_query2)
    assert is_safe is True


def test_validate_safety_forbidden_dml_ddl():
    """DROP, DELETE, UPDATE, INSERT, ALTER gibi zararlı komutların engellendiğini doğrular."""
    forbidden_queries = [
        "DROP TABLE Customers",
        "DELETE FROM Orders WHERE OrderID = 10248",
        "UPDATE Products SET UnitPrice = 0",
        "INSERT INTO Shippers (CompanyName) VALUES ('Hacker Express')",
        "ALTER TABLE Employees ADD COLUMN Password TEXT",
        "TRUNCATE TABLE [Order Details]",
        "EXEC sp_executesql",
        "ATTACH DATABASE 'malicious.db' AS mal",
    ]

    for f_query in forbidden_queries:
        is_safe, err = SQLGenerator.validate_safety(f_query)
        assert is_safe is False, f"Engellenmeliydi: {f_query}"
        assert "Güvenlik İhlali" in err or "Yalnızca SELECT" in err


# ---------------------------------------------------------------------------
# Birim Testleri: Prompt Yapılandırması (build_prompt_messages)
# ---------------------------------------------------------------------------

def test_build_prompt_messages_content(sql_generator):
    """Oluşturulan prompt mesajlarının şemayı, kuralları ve kullanıcı sorusunu içerdiğini doğrular."""
    question = "Kategorilerine göre ürün adetleri nelerdir?"
    messages = sql_generator.build_prompt_messages(question)

    assert len(messages) >= 2
    system_msg = messages[0].content
    last_human_msg = messages[-1].content

    assert "VERİTABANI ŞEMA VE METADATA TANIMLARI" in system_msg
    assert "Sadece SELECT Sorguları" in system_msg
    assert "Kullanıcı Sorusu: Kategorilerine göre ürün adetleri nelerdir?" in last_human_msg


# ---------------------------------------------------------------------------
# Entegrasyon Testleri: Kullanıcı Soruları & DB Çalıştırılabilirliği
# ---------------------------------------------------------------------------

def test_query_1_most_expensive_5_products(sql_generator):
    """
    Soru 1: 'En pahalı 5 ürünü fiyatıyla birlikte listele.'
    SQL üretimini ve veritabanında çalıştırılabilirliğini test eder.
    """
    question = "En pahalı 5 ürünü fiyatıyla birlikte listele."
    sql = sql_generator.generate_sql(question)

    assert "SELECT" in sql.upper()
    assert "Products" in sql
    assert "UnitPrice" in sql
    assert "LIMIT 5" in sql.upper()

    # DB üzerinde çalıştır ve doğrula
    res = execute_read_only_query(sql)
    assert res["row_count"] == 5
    assert len(res["rows"]) == 5
    # Fiyatların azalan sırada olduğunu teyit et
    prices = [r["UnitPrice"] for r in res["rows"]]
    assert prices == sorted(prices, reverse=True)


def test_query_2_customer_count_by_country(sql_generator):
    """
    Soru 2: 'Hangi ülkelerden kaçar tane müşteri var?'
    SQL üretimini ve veritabanında gruplama/sıralama doğruluğunu test eder.
    """
    question = "Hangi ülkelerden kaçar tane müşteri var?"
    sql = sql_generator.generate_sql(question)

    assert "SELECT" in sql.upper()
    assert "Country" in sql
    assert "Customers" in sql
    assert "GROUP BY" in sql.upper()

    # DB üzerinde çalıştır ve doğrula
    res = execute_read_only_query(sql)
    assert res["row_count"] > 10
    assert "Country" in res["columns"]


def test_query_3_top_3_customers_in_1997(sql_generator):
    """
    Soru 3: '1997 yılında en çok sipariş veren 3 müşteri kimdir?'
    Çoklu tablo JOIN (Customers + Orders) ve tarih filtresi SQL sözdizimini doğrular.
    """
    question = "1997 yılında en çok sipariş veren 3 müşteri kimdir?"
    sql = sql_generator.generate_sql(question)

    assert "Customers" in sql
    assert "Orders" in sql
    assert "1997" in sql
    assert "LIMIT 3" in sql.upper()

    # DB üzerinde çalıştır ve syntax/sorgu hatası vermediğini doğrula
    res = execute_read_only_query(sql)
    assert "columns" in res
    assert "CustomerID" in res["columns"] or "CompanyName" in res["columns"]


def test_query_3_top_3_customers_in_2016_with_data(sql_generator):
    """
    Soru 3 varyantı: 2016 yılı için sipariş verisi bulunan dönemde
    3 müşterinin döndüğünü ve azalan sipariş adedine göre sıralandığını doğrular.
    """
    question = "2016 yılında en çok sipariş veren 3 müşteri kimdir?"
    sql = sql_generator.generate_sql(question)

    res = execute_read_only_query(sql)
    assert res["row_count"] == 3
    assert len(res["rows"]) == 3
    orders_counts = [r["TotalOrders"] for r in res["rows"]]
    assert orders_counts == sorted(orders_counts, reverse=True)


def test_generate_and_execute_helper(sql_generator):
    """generate_and_execute fonksiyonunun uçtan uca doğru yanıt formatı döndürdüğünü test eder."""
    res = sql_generator.generate_and_execute("En pahalı 5 ürünü fiyatıyla birlikte listele.", limit=5)
    assert res["status"] == "success"
    assert res["error"] is None
    assert res["row_count"] == 5
    assert len(res["columns"]) >= 2
    assert len(res["rows"]) == 5


def test_sql_generator_safety_rejection(sql_generator):
    """Zararlı komut üreten sahte bir model cevabında ValueError fırlatıldığını doğrular."""
    with pytest.raises(ValueError, match="güvenlik testini geçemedi"):
        sql_generator.generate_sql("Tehlikeli Soru")
