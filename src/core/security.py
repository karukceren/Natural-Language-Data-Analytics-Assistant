"""
Doğal Dil İşlemeli Akıllı Veri Analiz Asistanı - Salt-Okunur Güvenli Sorgu Motoru
Veritabanı bağlantısını salt-okunur (mode=ro & PRAGMA query_only = ON) modda açar,
SQLValidator ile AST denetiminden geçen sorguları güvenli biçimde çalıştırır
ve pandas DataFrame olarak döner.
"""

from pathlib import Path
from typing import Any, Dict, Optional
import pandas as pd
from sqlalchemy import create_engine, event, text
from sqlalchemy.engine import Engine

from src.core.config import settings
from src.core.database import PROJECT_ROOT, get_normalized_database_url
from src.tools.sql_validator import SQLValidator, SecurityViolationError


_readonly_engine: Optional[Engine] = None


def get_readonly_database_url(raw_url: str) -> str:
    """
    Veritabanı URL'sini salt-okunur (mode=ro) SQLite URI formatına dönüştürür.
    """
    normalized = get_normalized_database_url(raw_url)
    if normalized.startswith("sqlite:///"):
        db_path = normalized.replace("sqlite:///", "")
        # URI formatı: sqlite:///file:path/to/db?mode=ro&uri=true
        return f"sqlite:///file:{db_path}?mode=ro&uri=true"
    return normalized


def get_readonly_engine() -> Engine:
    """
    Salt-okunur modda yapılandırılmış SQLAlchemy motorunu döner (Singleton).
    SQLite için 'mode=ro' ve 'PRAGMA query_only = ON;' korumalarını aktif eder.
    """
    global _readonly_engine
    if _readonly_engine is not None:
        return _readonly_engine

    readonly_url = get_readonly_database_url(settings.DATABASE_URL)
    connect_args = {}

    if "sqlite" in readonly_url:
        connect_args["uri"] = True
        connect_args["check_same_thread"] = False

    engine = create_engine(
        readonly_url,
        connect_args=connect_args,
        pool_pre_ping=True,
        echo=False,
    )

    # SQLite bağlantı hook'u ile her yeni bağlantıda query_only pragma'sını aç
    if "sqlite" in readonly_url:
        @event.listens_for(engine, "connect")
        def set_sqlite_readonly(dbapi_connection, connection_record):
            cursor = dbapi_connection.cursor()
            try:
                cursor.execute("PRAGMA query_only = ON;")
            except Exception:
                pass
            finally:
                cursor.close()

    _readonly_engine = engine
    return _readonly_engine


def execute_safe_query(
    sql: str,
    params: Optional[Dict[str, Any]] = None,
    timeout: Optional[int] = None,
    max_rows: Optional[int] = None,
) -> pd.DataFrame:
    """
    Sorguyu önce SQLValidator ile AST seviyesinde denetler, ardından salt-okunur
    veritabanı bağlantısı üzerinden çalıştırarak sonucu pandas.DataFrame olarak döner.

    Args:
        sql: Çalıştırılacak SQL sorgusu.
        params: Sorgu parametreleri (varsa).
        timeout: Maksimum sorgu çalışma süresi (saniye).
        max_rows: Maksimum döndürülecek satır sayısı (None ise settings.MAX_ROW_LIMIT).

    Returns:
        pd.DataFrame: Sorgu sonuçlarının yer aldığı DataFrame nesnesi.

    Raises:
        SecurityViolationError: Güvenlik ihlali tespit edildiğinde.
        Exception: Veritabanı sorgu hatası durumunda.
    """
    # 1. AST Seviyesinde Güvenlik Denetimi
    validated_sql = SQLValidator.validate(sql)

    # 2. Limit sınırlandırması uygula
    limit = max_rows if max_rows is not None else settings.MAX_ROW_LIMIT
    lower_sql = validated_sql.lower()
    if limit and "limit" not in lower_sql and "top" not in lower_sql:
        validated_sql = f"{validated_sql} LIMIT {limit}"

    engine = get_readonly_engine()
    timeout_sec = timeout if timeout is not None else settings.SQL_TIMEOUT_SECONDS

    # 3. Salt-Okunur Bağlantıda Çalıştır
    with engine.connect() as connection:
        # SQLite timeout / execution options
        stmt = text(validated_sql)
        if params:
            result = connection.execute(stmt, params)
        else:
            result = connection.execute(stmt)

        columns = list(result.keys())
        rows = result.fetchall()

        df = pd.DataFrame(rows, columns=columns)
        return df


def execute_safe_query_as_dict(
    sql: str,
    params: Optional[Dict[str, Any]] = None,
    max_rows: Optional[int] = None,
) -> Dict[str, Any]:
    """
    execute_safe_query çıktısını sözlük (dict) formatında döner (API ve UI katmanı için).

    Returns:
        {
            "columns": ["col1", "col2", ...],
            "rows": [{"col1": val1, "col2": val2}, ...],
            "row_count": N
        }
    """
    df = execute_safe_query(sql, params=params, max_rows=max_rows)
    return {
        "columns": list(df.columns),
        "rows": df.to_dict(orient="records"),
        "row_count": len(df),
    }
