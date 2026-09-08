import re
from pathlib import Path
from typing import Any, Dict, Generator, List, Optional
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.orm import declarative_base, sessionmaker, Session

from src.core.config import settings

# Proje ana dizini
PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent


def get_normalized_database_url(raw_url: str) -> str:
    """
    Veritabanı URL'ini normalize eder. 
    SQLite için göreli yolları proje kök dizinine göre mutlak yola dönüştürür.
    """
    if raw_url.startswith("sqlite:///./") or raw_url.startswith("sqlite:///data/"):
        relative_path = re.sub(r"^sqlite:///(?:\./)?", "", raw_url)
        absolute_db_path = PROJECT_ROOT / relative_path
        return f"sqlite:///{absolute_db_path.as_posix()}"
    return raw_url


# SQLAlchemy Motoru (Engine)
DATABASE_URL = get_normalized_database_url(settings.DATABASE_URL)

connect_args = {}
if DATABASE_URL.startswith("sqlite"):
    connect_args["check_same_thread"] = False

engine = create_engine(
    DATABASE_URL,
    connect_args=connect_args,
    pool_pre_ping=True,
    echo=settings.DEBUG,
)

# Session Fabrikası
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

# Declarative Model Base
Base = declarative_base()


def get_db() -> Generator[Session, None, None]:
    """
    FastAPI endpointleri veya servis katmanı için veritabanı oturumu (Session) sağlayıcı generator.
    """
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def test_connection() -> Dict[str, Any]:
    """
    Veritabanı bağlantısını test eder ve mevcut tabloları listeler.
    """
    try:
        with engine.connect() as connection:
            inspector = inspect(engine)
            tables = inspector.get_table_names()
            
            return {
                "status": "success",
                "database_type": engine.name,
                "database_url": DATABASE_URL,
                "table_count": len(tables),
                "tables": sorted(tables),
                "message": "Veritabanı bağlantısı başarılı.",
            }
    except Exception as exc:
        return {
            "status": "error",
            "database_type": getattr(engine, "name", "unknown"),
            "database_url": DATABASE_URL,
            "table_count": 0,
            "tables": [],
            "message": f"Veritabanı bağlantı hatası: {str(exc)}",
        }


def get_schema_summary() -> Dict[str, Any]:
    """
    LLM promptları ve şema izleyici ekranı için tüm tabloların kolonlarını,
    tiplerini, Primary Key ve Foreign Key ilişkilerini çıkarır.
    """
    inspector = inspect(engine)
    table_names = inspector.get_table_names()
    schema_info = {}

    for table_name in table_names:
        columns = inspector.get_columns(table_name)
        pk_constraint = inspector.get_pk_constraint(table_name)
        fks = inspector.get_foreign_keys(table_name)
        
        pk_cols = pk_constraint.get("constrained_columns", []) if pk_constraint else []

        schema_info[table_name] = {
            "columns": [
                {
                    "name": col["name"],
                    "type": str(col["type"]),
                    "nullable": col.get("nullable", True),
                    "is_primary_key": col["name"] in pk_cols,
                }
                for col in columns
            ],
            "primary_keys": pk_cols,
            "foreign_keys": [
                {
                    "constrained_columns": fk.get("constrained_columns", []),
                    "referred_table": fk.get("referred_table"),
                    "referred_columns": fk.get("referred_columns", []),
                }
                for fk in fks
            ],
        }

    return schema_info


def execute_read_only_query(query: str, limit: Optional[int] = None) -> Dict[str, Any]:
    """
    SELECT sorgularını güvenli bir şekilde çalıştırıp sonuçları liste ve sütun başlıkları olarak döner.
    """
    cleaned_query = query.strip().rstrip(";")
    if limit and "limit" not in cleaned_query.lower() and "top" not in cleaned_query.lower():
        cleaned_query = f"{cleaned_query} LIMIT {limit}"

    with engine.connect() as connection:
        result = connection.execute(text(cleaned_query))
        columns = list(result.keys())
        rows = [dict(zip(columns, row)) for row in result.fetchall()]
        
        return {
            "columns": columns,
            "rows": rows,
            "row_count": len(rows),
        }
