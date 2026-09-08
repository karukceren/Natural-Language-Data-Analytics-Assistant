"""
SQLValidator ve Salt-Okunur Güvenlik Katmanı (security.py) için birim ve entegrasyon testleri.
"""

import pandas as pd
import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError, OperationalError

from src.core.security import (
    execute_safe_query,
    execute_safe_query_as_dict,
    get_readonly_engine,
)
from src.tools.sql_validator import SQLValidator, SecurityViolationError


# ---------------------------------------------------------------------------
# SQLValidator: Geçerli SELECT ve CTE Sorgu Testleri
# ---------------------------------------------------------------------------

def test_valid_simple_select():
    """Basit SELECT sorgusunun doğrulandığını test eder."""
    sql = "SELECT CustomerID, CompanyName, City FROM Customers WHERE Country = 'Germany'"
    is_valid, msg = SQLValidator.is_valid_select(sql)
    assert is_valid is True
    assert msg == ""


def test_valid_complex_join_select():
    """Çoklu JOIN, GROUP BY ve HAVING içeren karmaşık SELECT sorgusunun onaylandığını test eder."""
    sql = """
        SELECT c.CustomerID, c.CompanyName, COUNT(o.OrderID) AS OrderCount, SUM(od.UnitPrice * od.Quantity) AS TotalRevenue
        FROM Customers c
        JOIN Orders o ON c.CustomerID = o.CustomerID
        JOIN "Order Details" od ON o.OrderID = od.OrderID
        WHERE o.OrderDate >= '2016-01-01'
        GROUP BY c.CustomerID, c.CompanyName
        HAVING OrderCount > 5
        ORDER BY TotalRevenue DESC
        LIMIT 10
    """
    is_valid, msg = SQLValidator.is_valid_select(sql)
    assert is_valid is True
    assert msg == ""


def test_valid_with_cte_query():
    """WITH (Common Table Expression - CTE) ile başlayan sorguların onaylandığını test eder."""
    sql = """
        WITH HighValueOrders AS (
            SELECT OrderID, SUM(UnitPrice * Quantity) AS Total
            FROM "Order Details"
            GROUP BY OrderID
            HAVING Total > 1000
        )
        SELECT o.OrderID, o.CustomerID, hvo.Total
        FROM Orders o
        JOIN HighValueOrders hvo ON o.OrderID = hvo.OrderID
    """
    is_valid, msg = SQLValidator.is_valid_select(sql)
    assert is_valid is True
    assert msg == ""


def test_valid_subquery_select():
    """İç içe alt sorgu (subquery) içeren ifadelerin onaylandığını test eder."""
    sql = """
        SELECT ProductName, UnitPrice
        FROM Products
        WHERE CategoryID IN (
            SELECT CategoryID FROM Categories WHERE CategoryName = 'Beverages'
        )
    """
    is_valid, msg = SQLValidator.is_valid_select(sql)
    assert is_valid is True


# ---------------------------------------------------------------------------
# SQLValidator: Zararlı DDL / DML Komutlarını Engelleme Testleri
# ---------------------------------------------------------------------------

@pytest.mark.parametrize(
    "malicious_sql,expected_keyword",
    [
        ("DROP TABLE Customers", "DROP"),
        ("drop table if exists orders;", "DROP"),
        ("DELETE FROM Orders WHERE OrderID > 0", "DELETE"),
        ("TRUNCATE TABLE Products", "TRUNCATE"),
        ("INSERT INTO Shippers (CompanyName) VALUES ('Malicious Express')", "INSERT"),
        ("UPDATE Products SET UnitPrice = 0.0", "UPDATE"),
        ("ALTER TABLE Employees ADD COLUMN IsAdmin INTEGER", "ALTER"),
        ("GRANT ALL PRIVILEGES ON Customers TO PUBLIC", "GRANT"),
        ("REVOKE ALL PRIVILEGES ON Customers FROM PUBLIC", "REVOKE"),
        ("EXEC xp_cmdshell 'whoami'", "EXEC"),
        ("EXECUTE sp_executesql N'SELECT 1'", "EXECUTE"),
        ("CREATE TABLE Hacker (id INT)", "CREATE"),
        ("ATTACH DATABASE 'malicious.db' AS mal", "ATTACH"),
        ("DETACH DATABASE mal", "DETACH"),
        ("PRAGMA table_info(Customers)", "PRAGMA"),
        ("REPLACE INTO Categories (CategoryID, CategoryName) VALUES (1, 'Hacked')", "REPLACE"),
    ],
)
def test_reject_malicious_ddl_dml(malicious_sql, expected_keyword):
    """Zararlı DDL ve DML komutlarının is_valid_select tarafından reddedildiğini doğrular."""
    is_valid, msg = SQLValidator.is_valid_select(malicious_sql)
    assert is_valid is False
    assert "Güvenlik İhlali" in msg or "Yalnızca SELECT" in msg
    assert expected_keyword.upper() in msg.upper()


def test_validate_raises_security_violation_error():
    """validate metodunun güvenlik ihlalinde SecurityViolationError fırlattığını doğrular."""
    with pytest.raises(SecurityViolationError, match="Güvenlik İhlali"):
        SQLValidator.validate("DELETE FROM Customers")


def test_reject_empty_or_whitespace_queries():
    """Boş veya yalnızca boşluk/yorumdan oluşan sorguların reddedildiğini doğrular."""
    assert SQLValidator.is_valid_select("")[0] is False
    assert SQLValidator.is_valid_select("   ")[0] is False
    assert SQLValidator.is_valid_select("-- sadece yorum satiri")[0] is False


# ---------------------------------------------------------------------------
# SQLValidator: Çoklu Sorgu (Stacked Query / Semicolon Injection) Testleri
# ---------------------------------------------------------------------------

@pytest.mark.parametrize(
    "stacked_sql",
    [
        "SELECT * FROM Orders; DROP TABLE Products;",
        "SELECT * FROM Customers; SELECT * FROM Orders;",
        "SELECT 1; DELETE FROM Employees;",
        "SELECT CustomerID FROM Customers; UPDATE Products SET UnitPrice = 100;",
    ],
)
def test_reject_stacked_queries(stacked_sql):
    """Noktalı virgül ile birleştirilmiş çoklu sorgu enjeksiyonlarının engellendiğini doğrular."""
    is_valid, msg = SQLValidator.is_valid_select(stacked_sql)
    assert is_valid is False
    assert "Çoklu SQL" in msg or "Stacked Queries" in msg or "Güvenlik İhlali" in msg


# ---------------------------------------------------------------------------
# SQLValidator: Tablo Çıkarıcı Yardımcı Fonksiyon (extract_tables)
# ---------------------------------------------------------------------------

def test_extract_tables():
    """Sorguda kullanılan tablo isimlerinin AST üzerinden doğru çıkarıldığını doğrular."""
    sql = 'SELECT c.CompanyName, o.OrderDate FROM Customers c JOIN Orders o ON c.CustomerID = o.CustomerID JOIN "Order Details" od ON o.OrderID = od.OrderID'
    tables = SQLValidator.extract_tables(sql)
    assert "Customers" in tables
    assert "Orders" in tables
    assert "Order Details" in tables


# ---------------------------------------------------------------------------
# security.py: execute_safe_query & Salt-Okunur Yürütme Testleri
# ---------------------------------------------------------------------------

def test_execute_safe_query_returns_dataframe():
    """execute_safe_query fonksiyonunun doğru pandas DataFrame döndürdüğünü doğrular."""
    sql = "SELECT ProductID, ProductName, UnitPrice FROM Products ORDER BY UnitPrice DESC LIMIT 5"
    df = execute_safe_query(sql)

    assert isinstance(df, pd.DataFrame)
    assert len(df) == 5
    assert "ProductID" in df.columns
    assert "ProductName" in df.columns
    assert "UnitPrice" in df.columns
    assert df["UnitPrice"].iloc[0] >= df["UnitPrice"].iloc[1]


def test_execute_safe_query_as_dict():
    """execute_safe_query_as_dict fonksiyonunun sözlük çıktısını doğrular."""
    sql = "SELECT CategoryID, CategoryName FROM Categories ORDER BY CategoryID ASC"
    res = execute_safe_query_as_dict(sql)

    assert isinstance(res, dict)
    assert "columns" in res
    assert "rows" in res
    assert "row_count" in res
    assert res["row_count"] >= 8
    assert res["columns"] == ["CategoryID", "CategoryName"]


def test_execute_safe_query_blocks_malicious_sql():
    """Zararlı komutların execute_safe_query çağrısında SecurityViolationError fırlattığını doğrular."""
    with pytest.raises(SecurityViolationError):
        execute_safe_query("DROP TABLE Customers")

    with pytest.raises(SecurityViolationError):
        execute_safe_query("SELECT * FROM Orders; DELETE FROM Products;")


def test_readonly_engine_database_level_protection():
    """
    Doğrudan SQLAlchemy motoru üzerinden yazma girişiminde bulunulsa dahi
    SQLite bağlantısının (mode=ro & PRAGMA query_only) bunu engellediğini doğrular.
    """
    engine = get_readonly_engine()
    with engine.connect() as conn:
        with pytest.raises((OperationalError, DBAPIError)):
            conn.execute(text("CREATE TABLE test_security_leak (id INT)"))
