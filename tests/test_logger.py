"""
Sorgu Loglama ve İzleme Servisi (QueryLogger ve QueryLog Modeli) için birim testleri.
"""

import pandas as pd
import pytest
from sqlalchemy import inspect

from src.core.database import Base, SessionLocal, engine
from src.core.logger import QueryLogger
from src.core.models import QueryLog


@pytest.fixture
def logger_instance():
    """Testler için temizlenmiş QueryLogger örneği oluşturan fixture."""
    logger = QueryLogger(engine=engine, session_factory=SessionLocal)
    logger.clear_logs()
    yield logger
    logger.clear_logs()


# ---------------------------------------------------------------------------
# 1. Tablo Oluşturma ve Model Testi
# ---------------------------------------------------------------------------

def test_query_log_table_creation(logger_instance):
    """'query_logs' tablosunun veritabanında başarıyla oluşturulduğunu doğrular."""
    inspector = inspect(engine)
    table_names = inspector.get_table_names()
    assert "query_logs" in table_names

    columns = [col["name"] for col in inspector.get_columns("query_logs")]
    assert "id" in columns
    assert "timestamp" in columns
    assert "user_query" in columns
    assert "generated_sql" in columns
    assert "execution_time_ms" in columns
    assert "row_count" in columns
    assert "is_success" in columns
    assert "error_message" in columns
    assert "retry_count" in columns


# ---------------------------------------------------------------------------
# 2. Başarılı Sorgu Loglama Testi
# ---------------------------------------------------------------------------

def test_log_successful_query(logger_instance):
    """Başarılı bir sorgunun tüm metrikleriyle birlikte kaydedildiğini ve okunduğunu doğrular."""
    log_id = logger_instance.log_query(
        user_query="En pahalı 5 ürünü listele",
        generated_sql="SELECT ProductName, UnitPrice FROM Products ORDER BY UnitPrice DESC LIMIT 5",
        execution_time_ms=145.5,
        row_count=5,
        is_success=True,
        error_message=None,
        retry_count=0,
    )

    assert log_id > 0

    df = logger_instance.get_recent_logs(limit=5)
    assert isinstance(df, pd.DataFrame)
    assert len(df) == 1

    row = df.iloc[0]
    assert row["id"] == log_id
    assert row["user_query"] == "En pahalı 5 ürünü listele"
    assert "SELECT ProductName" in row["generated_sql"]
    assert row["execution_time_ms"] == 145.5
    assert row["row_count"] == 5
    assert bool(row["is_success"]) is True
    assert row["error_message"] is None or pd.isna(row["error_message"])
    assert row["retry_count"] == 0


# ---------------------------------------------------------------------------
# 3. Hatalı ve Yeniden Denenen (Self-Healing) Sorgu Loglama Testi
# ---------------------------------------------------------------------------

def test_log_failed_query_with_error_and_retries(logger_instance):
    """Hata alan ve tamir döngüsü işletilen bir sorgunun eksiksiz kaydedildiğini doğrular."""
    log_id = logger_instance.log_query(
        user_query="Geçersiz bir tabloyu sorgula",
        generated_sql="SELECT * FROM NonExistentTable",
        execution_time_ms=450.2,
        row_count=0,
        is_success=False,
        error_message="OperationalError: no such table: NonExistentTable",
        retry_count=3,
    )

    assert log_id > 0

    df = logger_instance.get_recent_logs(limit=1)
    assert len(df) == 1

    row = df.iloc[0]
    assert bool(row["is_success"]) is False
    assert "no such table" in row["error_message"]
    assert row["retry_count"] == 3


# ---------------------------------------------------------------------------
# 4. get_recent_logs ve Limit Doğrulama Testi
# ---------------------------------------------------------------------------

def test_get_recent_logs_dataframe(logger_instance):
    """get_recent_logs fonksiyonunun limit parametresine ve zaman sıralamasına uyduğunu test eder."""
    for i in range(10):
        logger_instance.log_query(
            user_query=f"Soru {i}",
            generated_sql=f"SELECT {i}",
            execution_time_ms=10.0 * i,
            row_count=i,
            is_success=True,
        )

    # Limit 5
    df_limited = logger_instance.get_recent_logs(limit=5)
    assert len(df_limited) == 5
    # En son eklenen sorgunun en üstte olduğunu teyit et (azalan sıralama)
    assert df_limited.iloc[0]["user_query"] == "Soru 9"

    # Boş durum kontrolü
    logger_instance.clear_logs()
    df_empty = logger_instance.get_recent_logs(limit=10)
    assert isinstance(df_empty, pd.DataFrame)
    assert len(df_empty) == 0
    assert "user_query" in df_empty.columns


# ---------------------------------------------------------------------------
# 5. get_logs_summary İstatistik Analiz Testi
# ---------------------------------------------------------------------------

def test_get_logs_summary_metrics(logger_instance):
    """get_logs_summary fonksiyonunun analitik izleme metriklerini doğru hesapladığını test eder."""
    # 3 Başarılı, 1 Başarısız sorgu ekle
    logger_instance.log_query("Soru 1", execution_time_ms=100.0, is_success=True, retry_count=0)
    logger_instance.log_query("Soru 2", execution_time_ms=200.0, is_success=True, retry_count=1)
    logger_instance.log_query("Soru 3", execution_time_ms=300.0, is_success=True, retry_count=0)
    logger_instance.log_query("Soru 4", execution_time_ms=400.0, is_success=False, retry_count=3)

    summary = logger_instance.get_logs_summary()

    assert summary["total_queries"] == 4
    assert summary["successful_queries"] == 3
    assert summary["failed_queries"] == 1
    assert summary["success_rate_percent"] == 75.0
    assert summary["avg_execution_time_ms"] == 250.0
    assert summary["avg_retry_count"] == 1.0
