"""
SchemaManager modülü için kapsamlı birim ve entegrasyon testleri.
"""

import pytest
from src.ai.schema_manager import SchemaManager, NORTHWIND_METADATA
from src.core.database import engine


@pytest.fixture
def schema_manager():
    """SchemaManager fixture örneği oluşturur."""
    return SchemaManager(engine=engine)


def test_schema_manager_init(schema_manager):
    """
    SchemaManager'ın başarıyla başlatıldığını ve tabloları yüklediğini doğrular.
    """
    assert schema_manager is not None
    table_names = schema_manager.get_table_names()
    assert len(table_names) >= 8
    assert "Customers" in table_names
    assert "Orders" in table_names
    assert "Products" in table_names
    assert "Order Details" in table_names
    assert schema_manager.get_all_tables() == table_names


def test_metadata_dictionary_coverage(schema_manager):
    """
    Metadata sözlüğünün temel Northwind tablolarını içerdiğini doğrular.
    """
    essential_keys = [
        "Customers",
        "Orders",
        "Order Details",
        "Products",
        "Employees",
        "Categories",
        "Suppliers",
        "Shippers",
    ]
    for key in essential_keys:
        assert key in NORTHWIND_METADATA
        meta = NORTHWIND_METADATA[key]
        assert "description" in meta and len(meta["description"]) > 10
        assert "key_columns" in meta and len(meta["key_columns"]) > 0
        assert "keywords" in meta and len(meta["keywords"]) > 0


def test_resolve_table_name(schema_manager):
    """
    Büyük/küçük harf veya boşluksuz isimlerin (OrderDetails -> 'Order Details')
    doğru şekilde çözümlendiğini doğrular.
    """
    assert schema_manager.resolve_table_name("customers") == "Customers"
    assert schema_manager.resolve_table_name("CUSTOMERS") == "Customers"
    assert schema_manager.resolve_table_name("OrderDetails") == "Order Details"
    assert schema_manager.resolve_table_name("orderdetails") == "Order Details"
    assert schema_manager.resolve_table_name("Order Details") == "Order Details"
    assert schema_manager.resolve_table_name("order details") == "Order Details"
    assert schema_manager.resolve_table_name("NonExistentTable") is None


def test_customers_orders_order_details_relationships(schema_manager):
    """
    Kritik Northwind ilişkilerinin (Customers -> Orders -> Order Details -> Products)
    doğru ve eksiksiz tespit edildiğini doğrular.
    """
    relationships = schema_manager.get_relationships([
        "Customers",
        "Orders",
        "Order Details",
        "Products",
    ])
    assert len(relationships) >= 3

    # Orders.CustomerID -> Customers.CustomerID kontrolü
    orders_to_customers = [
        r for r in relationships
        if r["from_table"] == "Orders" and r["to_table"] == "Customers"
    ]
    assert len(orders_to_customers) == 1
    assert "CustomerID" in orders_to_customers[0]["from_columns"]
    assert "CustomerID" in orders_to_customers[0]["to_columns"]

    # Order Details.OrderID -> Orders.OrderID kontrolü
    order_details_to_orders = [
        r for r in relationships
        if r["from_table"] == "Order Details" and r["to_table"] == "Orders"
    ]
    assert len(order_details_to_orders) == 1
    assert "OrderID" in order_details_to_orders[0]["from_columns"]
    assert "OrderID" in order_details_to_orders[0]["to_columns"]

    # Order Details.ProductID -> Products.ProductID kontrolü
    order_details_to_products = [
        r for r in relationships
        if r["from_table"] == "Order Details" and r["to_table"] == "Products"
    ]
    assert len(order_details_to_products) == 1
    assert "ProductID" in order_details_to_products[0]["from_columns"]
    assert "ProductID" in order_details_to_products[0]["to_columns"]


def test_generate_ddl_structure(schema_manager):
    """
    DDL üreticisinin geçerli SQL sözdizimine ve PK/FK kısıtlamalarına sahip olduğunu doğrular.
    """
    # 1. Customers tablosu DDL'i
    customers_ddl = schema_manager.generate_ddl("Customers")
    assert "CREATE TABLE Customers (" in customers_ddl
    assert "CustomerID" in customers_ddl
    assert "CompanyName" in customers_ddl
    assert "PRIMARY KEY" in customers_ddl

    # 2. Boşluklu isimli Order Details tablosu DDL'i
    order_details_ddl = schema_manager.generate_ddl("Order Details")
    assert 'CREATE TABLE "Order Details" (' in order_details_ddl
    assert "OrderID" in order_details_ddl
    assert "ProductID" in order_details_ddl
    assert "UnitPrice" in order_details_ddl
    assert "Quantity" in order_details_ddl
    assert "Discount" in order_details_ddl
    assert "FOREIGN KEY" in order_details_ddl
    assert "REFERENCES Orders" in order_details_ddl
    assert "REFERENCES Products" in order_details_ddl


def test_get_formatted_schema(schema_manager):
    """
    LLM promptu için oluşturulan zenginleştirilmiş şema metninin
    DDL, açıklamalar ve ilişki rehberini içerdiğini doğrular.
    """
    formatted = schema_manager.get_formatted_schema(["Customers", "Orders"])
    assert "VERİTABANI ŞEMA VE METADATA TANIMLARI" in formatted
    assert "Tablo: `Customers`" in formatted
    assert "Tablo: `Orders`" in formatted
    assert "İş Açıklaması:" in formatted
    assert "Önemli Kolonlar:" in formatted
    assert "CREATE TABLE" in formatted
    assert "TABLOLAR ARASI İLİŞKİLER" in formatted
    assert "`Orders` -> `Customers`" in formatted


def test_get_relevant_tables_keywords(schema_manager):
    """
    Farklı Türkçe ve İngilizce sorgular için en ilgili tabloların seçildiğini doğrular.
    """
    # Senaryo 1: Müşteriler ve şirketler
    t1 = schema_manager.get_relevant_tables("En çok sipariş veren müşteriler kimlerdir?")
    assert "Customers" in t1
    assert "Orders" in t1

    # Senaryo 2: Kargo şirketleri
    t2 = schema_manager.get_relevant_tables("Hangi kargo şirketi ile en çok taşıma yapıldı?")
    assert "Shippers" in t2

    # Senaryo 3: Ürün ve kategori
    t3 = schema_manager.get_relevant_tables("Hangi kategoride kaç adet ürünümüz var?")
    assert "Products" in t3
    assert "Categories" in t3

    # Senaryo 4: Çalışan ve yönetici
    t4 = schema_manager.get_relevant_tables("Personeller ve bağlı oldukları müdürler kimler?")
    assert "Employees" in t4


def test_get_relevant_tables_fk_bridge_expansion(schema_manager):
    """
    Müşteriler ve Ürünler sorulduğunda, aradaki Orders ve Order Details
    köprü tablolarının otomatik dahil edildiğini (FK Expansion) doğrular.
    """
    query = "Müşterilerin en çok satın aldığı ürünler hangileridir?"
    relevant = schema_manager.get_relevant_tables(query)
    
    # Soru doğrudan 'müşteri' ve 'ürün' içerir, ancak JOIN yapılabilmesi için
    # 'Orders' ve 'Order Details' tablolarının da bulunması şarttır.
    assert "Customers" in relevant
    assert "Products" in relevant
    assert "Orders" in relevant
    assert "Order Details" in relevant


def test_database_summary(schema_manager):
    """
    Veritabanı istatistiklerinin doğru çıkarıldığını test eder.
    """
    summary = schema_manager.get_database_summary()
    assert "database_type" in summary
    assert summary["table_count"] >= 8
    assert summary["total_columns"] > 50
    assert summary["relationship_count"] > 5
