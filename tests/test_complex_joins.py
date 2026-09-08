"""
Karmaşık JOIN ve Uç Durum (Edge-Case) Test Paketi (tests/test_complex_joins.py)
En az 3, 4 ve 5 tablolu ilişkisel sorguların doğruluğunu, veri tutarlılığını ve
alan dışı (Out-of-Domain / Halüsinasyon) soruların yakalanmasını test eder.
"""

from typing import List
import pytest
import pandas as pd
from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import AIMessage, BaseMessage
from langchain_core.outputs import ChatGeneration, ChatResult

from src.ai.schema_manager import SchemaManager
from src.ai.sql_generator import SQLGenerator, OutOfDomainQueryError
from src.ai.sql_healing import SQLSelfHealingAgent, QueryExecutionError
from src.core.database import engine, execute_read_only_query


class MockComplexJoinChatModel(BaseChatModel):
    """Karmaşık JOIN senaryolarında deterministik SQL üreten Mock LLM."""
    responses: list = []

    def _generate(
        self,
        messages: List[BaseMessage],
        stop: list = None,
        run_manager = None,
        **kwargs,
    ) -> ChatResult:
        if MockComplexJoinChatModel.responses:
            response_text = MockComplexJoinChatModel.responses.pop(0)
        else:
            response_text = "SELECT 1"

        message = AIMessage(content=response_text)
        return ChatResult(generations=[ChatGeneration(message=message)])

    @property
    def _llm_type(self) -> str:
        return "mock-complex-join-chat-model"


@pytest.fixture(autouse=True)
def reset_mock_state():
    """Her test öncesi mock durumunu sıfırlar."""
    MockComplexJoinChatModel.responses = []


@pytest.fixture
def schema_manager():
    """SchemaManager fixture örneği."""
    return SchemaManager(engine=engine)


@pytest.fixture
def complex_agent(schema_manager):
    """Mock LLM ile donatılmış SQLSelfHealingAgent fixture örneği."""
    mock_llm = MockComplexJoinChatModel()
    sql_gen = SQLGenerator(schema_manager=schema_manager, llm=mock_llm)
    return SQLSelfHealingAgent(
        sql_generator=sql_gen,
        schema_manager=schema_manager,
        llm=mock_llm,
        max_retries=3,
    )


# ---------------------------------------------------------------------------
# 1. Senaryo 1: 3 Tablolu JOIN (Customers -> Orders -> Order Details)
# ---------------------------------------------------------------------------
def test_scenario_1_germany_customers_total_spent_3_tables(complex_agent):
    """
    Senaryo 1: 'Almanya'daki müşterilerin verdiği siparişlerin toplam tutarını müşteri bazında listele.'
    Customers -> Orders -> Order Details (3 Tablo)
    """
    expected_sql = """
    SELECT 
        c.CustomerID,
        c.CompanyName,
        c.Country,
        ROUND(SUM((od.UnitPrice * od.Quantity) * (1.0 - od.Discount)), 2) AS TotalSpent
    FROM Customers c
    JOIN Orders o ON c.CustomerID = o.CustomerID
    JOIN "Order Details" od ON o.OrderID = od.OrderID
    WHERE c.Country = 'Germany'
    GROUP BY c.CustomerID, c.CompanyName, c.Country
    ORDER BY TotalSpent DESC
    """
    MockComplexJoinChatModel.responses = [expected_sql]

    question = "Almanya'daki müşterilerin verdiği siparişlerin toplam tutarını müşteri bazında listele."
    df, final_sql, history = complex_agent.execute_with_healing(question)

    # 1. Doğrulama: Dönen veri boş olmamalı
    assert not df.empty
    assert len(df) >= 5  # Northwind'de 11 Alman müşteri var

    # 2. Doğrulama: Gerekli sütunlar mevcut olmalı
    assert "CustomerID" in df.columns
    assert "CompanyName" in df.columns
    assert "TotalSpent" in df.columns

    # 3. Doğrulama: Değerler mantıklı ve pozitif olmalı
    assert (df["TotalSpent"] > 0).all()
    assert (df["Country"] == "Germany").all()

    # 4. Doğrulama: Sıralama azalan olmalı (DESC)
    assert df["TotalSpent"].iloc[0] >= df["TotalSpent"].iloc[1]


# ---------------------------------------------------------------------------
# 2. Senaryo 2: 5 Tablolu JOIN (Shippers -> Orders -> Order Details -> Products -> Categories)
# ---------------------------------------------------------------------------
def test_scenario_2_speedy_express_beverages_sales_5_tables(complex_agent):
    """
    Senaryo 2: 'Speedy Express kargosuyla taşınan Beverages kategorisindeki ürünlerin toplam satış adedini getir.'
    Shippers -> Orders -> Order Details -> Products -> Categories (5 Tablo)
    """
    expected_sql = """
    SELECT 
        s.CompanyName AS ShipperName,
        c.CategoryName,
        SUM(od.Quantity) AS TotalQuantitySold
    FROM Shippers s
    JOIN Orders o ON s.ShipperID = o.ShipVia
    JOIN "Order Details" od ON o.OrderID = od.OrderID
    JOIN Products p ON od.ProductID = p.ProductID
    JOIN Categories c ON p.CategoryID = c.CategoryID
    WHERE s.CompanyName = 'Speedy Express' AND c.CategoryName = 'Beverages'
    GROUP BY s.CompanyName, c.CategoryName
    """
    MockComplexJoinChatModel.responses = [expected_sql]

    question = "Speedy Express kargosuyla taşınan Beverages kategorisindeki ürünlerin toplam satış adedini getir."
    df, final_sql, history = complex_agent.execute_with_healing(question)

    # 1. Doğrulama: Sonuç tablosu 1 satır dönmeli
    assert len(df) == 1
    assert "ShipperName" in df.columns
    assert "CategoryName" in df.columns
    assert "TotalQuantitySold" in df.columns

    # 2. Doğrulama: Değerler doğrulanmalı
    assert df["ShipperName"].iloc[0] == "Speedy Express"
    assert df["CategoryName"].iloc[0] == "Beverages"
    assert int(df["TotalQuantitySold"].iloc[0]) > 0


# ---------------------------------------------------------------------------
# 3. Senaryo 3: 3 Tablolu Çalışan Performansı (Employees -> Orders -> Order Details)
# ---------------------------------------------------------------------------
def test_scenario_3_top_3_employees_revenue_2016_3_tables(complex_agent):
    """
    Senaryo 3: '2016 yılında en yüksek ciroyu getiren ilk 3 çalışanın adını, soyadını ve cirosunu listele.'
    Employees -> Orders -> Order Details (3 Tablo)
    """
    expected_sql = """
    SELECT 
        e.EmployeeID,
        e.FirstName || ' ' || e.LastName AS FullName,
        ROUND(SUM((od.UnitPrice * od.Quantity) * (1.0 - od.Discount)), 2) AS TotalRevenue
    FROM Employees e
    JOIN Orders o ON e.EmployeeID = o.EmployeeID
    JOIN "Order Details" od ON o.OrderID = od.OrderID
    WHERE strftime('%Y', o.OrderDate) = '2016'
    GROUP BY e.EmployeeID, e.FirstName, e.LastName
    ORDER BY TotalRevenue DESC
    LIMIT 3
    """
    MockComplexJoinChatModel.responses = [expected_sql]

    question = "2016 yılında en yüksek ciroyu getiren ilk 3 çalışanın adını, soyadını ve cirosunu listele."
    df, final_sql, history = complex_agent.execute_with_healing(question)

    # 1. Doğrulama: Tam olarak ilk 3 satır dönmeli
    assert len(df) == 3
    assert "FullName" in df.columns
    assert "TotalRevenue" in df.columns

    # 2. Doğrulama: Cirolar pozitif ve sıralı olmalı
    assert (df["TotalRevenue"] > 1000).all()
    assert df["TotalRevenue"].iloc[0] >= df["TotalRevenue"].iloc[1] >= df["TotalRevenue"].iloc[2]

    # 2. Doğrulama: Cirolar pozitif ve sıralı olmalı
    assert (df["TotalRevenue"] > 1000).all()
    assert df["TotalRevenue"].iloc[0] >= df["TotalRevenue"].iloc[1] >= df["TotalRevenue"].iloc[2]


# ---------------------------------------------------------------------------
# 4. Senaryo 4: Agregasyon & Gruplama (Categories -> Products -> Order Details)
# ---------------------------------------------------------------------------
def test_scenario_4_category_order_quantity_and_avg_discount_3_tables(complex_agent):
    """
    Senaryo 4: 'Her ürün kategorisindeki toplam sipariş miktarını ve ortalama indirim oranını hesapla.'
    Categories -> Products -> Order Details (3 Tablo)
    """
    expected_sql = """
    SELECT 
        c.CategoryID,
        c.CategoryName,
        COUNT(DISTINCT p.ProductID) AS UniqueProducts,
        SUM(od.Quantity) AS TotalQuantity,
        ROUND(AVG(od.Discount), 4) AS AvgDiscountRate
    FROM Categories c
    JOIN Products p ON c.CategoryID = p.CategoryID
    JOIN "Order Details" od ON p.ProductID = od.ProductID
    GROUP BY c.CategoryID, c.CategoryName
    ORDER BY TotalQuantity DESC
    """
    MockComplexJoinChatModel.responses = [expected_sql]

    question = "Her ürün kategorisindeki toplam sipariş miktarını ve ortalama indirim oranını hesapla."
    df, final_sql, history = complex_agent.execute_with_healing(question)

    # 1. Doğrulama: Northwind'deki tüm 8 kategori listelenmeli
    assert len(df) == 8
    assert "CategoryName" in df.columns
    assert "TotalQuantity" in df.columns
    assert "AvgDiscountRate" in df.columns

    # 2. Doğrulama: Toplam adetler pozitif olmalı
    assert (df["TotalQuantity"] > 0).all()
    # Ortalama indirim oranı 0.0 ile 1.0 arasında olmalı
    assert (df["AvgDiscountRate"] >= 0.0).all()
    assert (df["AvgDiscountRate"] <= 1.0).all()


# ---------------------------------------------------------------------------
# 5. Senaryo 5: Edge-Case ve Alan Dışı (Out-of-Domain) Soru Yönetimi
# ---------------------------------------------------------------------------
def test_scenario_5_out_of_domain_passwords_rejected(complex_agent):
    """
    Kullanıcı veritabanında olmayan hassas varlıkları (şifre, parola) sorduğunda
    halüsinasyon görmeden güvenli şekilde reddedildiğini doğrular.
    """
    question = "Kullanıcıların şifrelerini ve parolalarını getir."
    with pytest.raises(QueryExecutionError) as exc_info:
        complex_agent.execute_with_healing(question)

    assert "Bu soru veritabanı şemasında bulunan tablolarla ilişkili değildir." in str(exc_info.value)


def test_scenario_5_out_of_domain_bitcoin_rejected(complex_agent):
    """
    Kullanıcı kripto/bitcoin gibi şema dışı finansal verileri sorduğunda
    anlamlı bir hata mesajıyla reddedildiğini doğrular.
    """
    question = "Güncel Bitcoin (BTC) ve Ethereum fiyatlarını göster."
    with pytest.raises(QueryExecutionError) as exc_info:
        complex_agent.execute_with_healing(question)

    assert "Bu soru veritabanı şemasında bulunan tablolarla ilişkili değildir." in str(exc_info.value)


def test_scenario_5_out_of_domain_weather_rejected(complex_agent):
    """
    Kullanıcı hava durumu veya spor gibi alakasız konuları sorduğunda
    alan dışı olarak engellendiğini doğrular.
    """
    question = "Yarın İstanbul'da hava durumu nasıl olacak?"
    with pytest.raises(QueryExecutionError) as exc_info:
        complex_agent.execute_with_healing(question)

    assert "Bu soru veritabanı şemasında bulunan tablolarla ilişkili değildir." in str(exc_info.value)


def test_scenario_5_model_output_out_of_domain_token_handled(complex_agent):
    """
    LLM doğrudan 'OUT_OF_DOMAIN' token'ı ürettiğinde, sistemin bunu yakalayıp
    QueryExecutionError fırlattığını doğrular.
    """
    MockComplexJoinChatModel.responses = ["OUT_OF_DOMAIN"]

    # Zorunlu tablo parametresiyle alan kontrolünü baypas edip model çıktısına bakalım
    question = "Güneş sistemindeki gezegenlerin listesi nedir?"
    with pytest.raises(QueryExecutionError) as exc_info:
        complex_agent.execute_with_healing(question, table_names=["Customers"])

    assert "Bu soru veritabanı şemasında bulunan tablolarla ilişkili değildir." in str(exc_info.value)
