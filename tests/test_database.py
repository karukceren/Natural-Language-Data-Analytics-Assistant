import pytest
from src.core.database import (
    test_connection as db_test_connection,
    get_schema_summary,
    execute_read_only_query,
    engine,
)


def test_database_connection():
    """
    Veritabanı bağlantı durumunun başarılı olduğunu test eder.
    """
    result = db_test_connection()
    assert result["status"] == "success"
    assert result["table_count"] >= 8
    assert isinstance(result["tables"], list)


def test_essential_tables_exist():
    """
    Northwind için kritik kurumsal tabloların mevcut olduğunu test eder.
    """
    result = db_test_connection()
    tables = result["tables"]

    # Hem standart hem boşluklu formatları destekle
    essential_tables = [
        "Categories",
        "Customers",
        "Employees",
        "Orders",
        "Products",
        "Shippers",
        "Suppliers",
    ]

    for table in essential_tables:
        assert any(t.lower() == table.lower() for t in tables), f"Eksik tablo: {table}"


def test_tables_are_not_empty():
    """
    Kritik tabloların içerisinde veri bulunduğunu doğrular.
    """
    check_tables = ["Products", "Customers", "Categories", "Employees"]

    for table in check_tables:
        res = execute_read_only_query(f'SELECT COUNT(*) as cnt FROM "{table}"')
        assert res["row_count"] > 0
        count = res["rows"][0]["cnt"]
        assert count > 0, f"Tablo boş: {table}"


def test_execute_read_only_query():
    """
    execute_read_only_query fonksiyonunun doğru kolon ve satır yapısı döndürdüğünü test eder.
    """
    query = 'SELECT "ProductID", "ProductName", "UnitPrice" FROM "Products" ORDER BY "UnitPrice" DESC'
    res = execute_read_only_query(query, limit=5)

    assert "columns" in res
    assert "rows" in res
    assert res["row_count"] == 5
    assert "ProductName" in res["columns"]
    assert "UnitPrice" in res["columns"]
    assert len(res["rows"]) == 5


def test_get_schema_summary():
    """
    Şema analiz servisinin tabloları, kolonları ve anahtarları doğru çıkardığını test eder.
    """
    schema = get_schema_summary()
    assert isinstance(schema, dict)
    assert "Products" in schema or "products" in schema

    products_key = "Products" if "Products" in schema else "products"
    product_schema = schema[products_key]

    assert "columns" in product_schema
    column_names = [col["name"] for col in product_schema["columns"]]
    assert "ProductName" in column_names or "productname" in [c.lower() for c in column_names]
