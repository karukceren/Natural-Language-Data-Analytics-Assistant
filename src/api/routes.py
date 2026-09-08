"""
Doğal Dil İşlemeli Akıllı Veri Analiz Asistanı - FastAPI API Yönlendiricisi (Routes)
Kullanıcı sorularını alan, Text-to-SQL + Self-Healing pipeline'ını çalıştıran,
şema ve log yönetimini sağlayan RESTful endpoint'leri tanımlar.
"""

import os
import time
from typing import Any, Dict, List, Optional
import numpy as np
import pandas as pd
from fastapi import APIRouter, HTTPException, Query, status

from src.ai.schema_manager import SchemaManager
from src.ai.sql_generator import SQLGenerator
from src.ai.sql_healing import QueryExecutionError, SQLSelfHealingAgent
from src.api.schemas import (
    HealthResponse,
    LogEntryItem,
    LogsResponse,
    LogsSummary,
    QueryRequest,
    QueryResponse,
    SchemaColumnInfo,
    SchemaResponse,
    SchemaTableInfo,
)
from src.core.config import settings
from src.core.database import engine, test_connection
from src.core.logger import query_logger
from src.tools.chart_selector import determine_chart_type

router = APIRouter(prefix="/api", tags=["Akıllı Veri Analiz Asistanı API"])

# Global Singleton Servis Örnekleri
schema_manager = SchemaManager(engine=engine)
agent = SQLSelfHealingAgent(
    schema_manager=schema_manager,
    max_retries=settings.MAX_RETRY_ATTEMPTS,
)


def _clean_dataframe_for_json(df: pd.DataFrame) -> List[Dict[str, Any]]:
    """
    Pandas DataFrame'deki NaN, NaT ve sonsuz (inf) değerleri JSON ile uyumlu
    None / null değerlerine dönüştürerek liste sözlük (records) formatında döner.
    """
    if df.empty:
        return []
    
    # NaN ve None temizliği
    cleaned_df = df.replace({np.nan: None, np.inf: None, -np.inf: None})
    return cleaned_df.to_dict(orient="records")


# ---------------------------------------------------------------------------
# 1. Sistem Sağlığı (Health Check)
# ---------------------------------------------------------------------------
@router.get(
    "/health",
    response_model=HealthResponse,
    summary="Sistem ve Veritabanı Sağlık Kontrolü",
)
def get_health_status() -> HealthResponse:
    """
    Veritabanı bağlantısını, mevcut tablo sayısını ve aktif LLM sağlayıcı ayarlarını döner.
    """
    conn_info = test_connection()
    is_connected = conn_info.get("status") == "success"
    table_count = conn_info.get("table_count", 0)

    return HealthResponse(
        status="healthy" if is_connected else "degraded",
        app_name=settings.APP_NAME,
        database_type=conn_info.get("database_type", "sqlite"),
        database_connected=is_connected,
        table_count=table_count,
        model_provider=settings.DEFAULT_LLM_PROVIDER,
        model_name=settings.DEFAULT_MODEL_NAME,
    )


# ---------------------------------------------------------------------------
# 2. Doğal Dil Sorgulama ve Analiz (Query Execution)
# ---------------------------------------------------------------------------
@router.post(
    "/query",
    response_model=QueryResponse,
    summary="Doğal Dil Sorusunu SQL'e Çevir ve Çalıştır",
)
def process_query(request: QueryRequest) -> QueryResponse:
    """
    Kullanıcının doğal dildeki sorusunu alır:
    1. SQLSelfHealingAgent ile SQL üretir ve güvenli biçimde çalıştırır.
    2. Hata durumunda Self-Healing döngüsü ile sorguyu otomatik tamir eder.
    3. Dönen veriyi analiz edip en uygun grafik türünü (ChartSelector) belirler.
    4. QueryLogger ile audit log kaydı açar.
    5. Sonuç tablosu, grafik konfigürasyonu ve yürütme detaylarını döner.
    """
    start_time = time.perf_counter()
    question = request.question.strip()

    try:
        if request.api_key and request.provider:
            env_map = {
                "groq": "GROQ_API_KEY",
                "gemini": "GEMINI_API_KEY",
                "google": "GEMINI_API_KEY",
                "openai": "OPENAI_API_KEY",
                "anthropic": "ANTHROPIC_API_KEY",
                "openrouter": "OPENROUTER_API_KEY",
            }
            env_var = env_map.get(request.provider.lower())
            if env_var:
                os.environ[env_var] = request.api_key.strip()

        if request.provider or request.model_name:
            provider = (request.provider or settings.DEFAULT_LLM_PROVIDER).lower()
            model_name = request.model_name or settings.DEFAULT_MODEL_NAME
            gen = SQLGenerator(
                schema_manager=schema_manager,
                provider=provider,
                model_name=model_name,
                llm=agent.sql_generator._llm,
            )
            query_agent = SQLSelfHealingAgent(
                sql_generator=gen,
                schema_manager=schema_manager,
                max_retries=settings.MAX_RETRY_ATTEMPTS,
                llm=agent._llm,
            )
        else:
            query_agent = agent

        # Self-Healing Text-to-SQL Yürütme
        df, final_sql, history = query_agent.execute_with_healing(question)
        exec_time_ms = round((time.perf_counter() - start_time) * 1000, 2)
        retry_count = max(0, len(history) - 2)

        # Otomatik Grafik Seçimi
        chart_config = determine_chart_type(df, question=question)

        # JSON Temizliği
        records = _clean_dataframe_for_json(df)
        columns = list(df.columns) if not df.empty else []

        # Başarılı Log Kaydı
        query_logger.log_query(
            user_query=question,
            generated_sql=final_sql,
            execution_time_ms=exec_time_ms,
            row_count=len(df),
            is_success=True,
            retry_count=retry_count,
        )

        summary_text = (
            f"Sorgu başarıyla çalıştırıldı. Toplam {len(df)} kayıt listelendi. "
            f"Önerilen görselleştirme: {chart_config.get('chart_type', 'table').upper()}."
        )

        return QueryResponse(
            sql=final_sql,
            data=records,
            columns=columns,
            chart_config=chart_config,
            execution_time_ms=exec_time_ms,
            retry_count=retry_count,
            is_success=True,
            error_message=None,
            repair_history=history,
            summary=summary_text,
        )

    except QueryExecutionError as q_err:
        exec_time_ms = round((time.perf_counter() - start_time) * 1000, 2)

        # Başarısız Log Kaydı
        query_logger.log_query(
            user_query=question,
            generated_sql=q_err.last_sql,
            execution_time_ms=exec_time_ms,
            row_count=0,
            is_success=False,
            error_message=q_err.message,
            retry_count=len(q_err.attempts),
        )

        return QueryResponse(
            sql=q_err.last_sql or "",
            data=[],
            columns=[],
            chart_config={"chart_type": "table", "title": "Hata"},
            execution_time_ms=exec_time_ms,
            retry_count=len(q_err.attempts),
            is_success=False,
            error_message=q_err.message,
            repair_history=q_err.attempts,
            summary=f"Sorgu çalıştırılamadı: {q_err.message}",
        )

    except Exception as exc:
        exec_time_ms = round((time.perf_counter() - start_time) * 1000, 2)
        err_msg = str(exc)

        # Beklenmeyen Hata Logu
        query_logger.log_query(
            user_query=question,
            generated_sql=None,
            execution_time_ms=exec_time_ms,
            row_count=0,
            is_success=False,
            error_message=err_msg,
            retry_count=0,
        )

        return QueryResponse(
            sql="",
            data=[],
            columns=[],
            chart_config={"chart_type": "table", "title": "Beklenmeyen Hata"},
            execution_time_ms=exec_time_ms,
            retry_count=0,
            is_success=False,
            error_message=err_msg,
            repair_history=[],
            summary=f"Hata oluştu: {err_msg}",
        )


# ---------------------------------------------------------------------------
# 3. Şema ve Metadata Bilgileri (Schema Viewer)
# ---------------------------------------------------------------------------
@router.get(
    "/schema",
    response_model=SchemaResponse,
    summary="Veritabanı Şeması, Kolonlar ve DDL Bilgisi",
)
def get_database_schema() -> SchemaResponse:
    """
    Veritabanındaki tüm tabloları, kolon tiplerini, Primary/Foreign Key kısıtlamalarını
    ve üretilmiş DDL tanımlarını döner.
    """
    table_names = schema_manager.get_table_names()
    schema_details: List[SchemaTableInfo] = []

    for tbl in table_names:
        info = schema_manager.get_table_info(tbl) or {}
        columns_raw = info.get("columns", [])
        pks = info.get("primary_keys", [])
        fks = info.get("foreign_keys", [])
        desc = schema_manager.get_table_description(tbl)
        ddl = schema_manager.generate_ddl(tbl)

        columns = [
            SchemaColumnInfo(
                name=c["name"],
                type=c["type"],
                nullable=c.get("nullable", True),
                is_primary_key=c.get("is_primary_key", False),
            )
            for c in columns_raw
        ]

        schema_details.append(
            SchemaTableInfo(
                table_name=tbl,
                description=desc,
                columns=columns,
                primary_keys=pks,
                foreign_keys=fks,
                ddl=ddl,
            )
        )

    relationships = schema_manager.get_relationships()

    return SchemaResponse(
        table_count=len(table_names),
        tables=table_names,
        schema_details=schema_details,
        relationships=relationships,
    )


# ---------------------------------------------------------------------------
# 4. Sorgu Logları ve Analitik Metrikler (Logs Viewer)
# ---------------------------------------------------------------------------
@router.get(
    "/logs",
    response_model=LogsResponse,
    summary="Sorgu Logları ve Sistem Metrikleri",
)
def get_query_logs(
    limit: int = Query(50, ge=1, le=500, description="Döndürülecek maksimum log sayısı"),
) -> LogsResponse:
    """
    Kaydedilmiş son sorgu loglarını ve genel sistem istatistiklerini (başarı oranı, ortalama süre) döner.
    """
    logs_df = query_logger.get_recent_logs(limit=limit)
    summary_dict = query_logger.get_logs_summary()

    log_items: List[LogEntryItem] = []
    if not logs_df.empty:
        for _, row in logs_df.iterrows():
            ts = str(row["timestamp"]) if pd.notnull(row.get("timestamp")) else None
            log_items.append(
                LogEntryItem(
                    id=int(row["id"]),
                    timestamp=ts,
                    user_query=str(row["user_query"]),
                    generated_sql=str(row["generated_sql"]) if pd.notnull(row.get("generated_sql")) else None,
                    execution_time_ms=float(row["execution_time_ms"]),
                    row_count=int(row["row_count"]),
                    is_success=bool(row["is_success"]),
                    error_message=str(row["error_message"]) if pd.notnull(row.get("error_message")) else None,
                    retry_count=int(row["retry_count"]),
                )
            )

    summary = LogsSummary(
        total_queries=summary_dict.get("total_queries", 0),
        successful_queries=summary_dict.get("successful_queries", 0),
        failed_queries=summary_dict.get("failed_queries", 0),
        success_rate_percent=summary_dict.get("success_rate_percent", 0.0),
        avg_execution_time_ms=summary_dict.get("avg_execution_time_ms", 0.0),
        avg_retry_count=summary_dict.get("avg_retry_count", 0.0),
    )

    return LogsResponse(
        total_count=len(log_items),
        logs=log_items,
        summary=summary,
    )


@router.delete(
    "/logs",
    summary="Tüm Sorgu Loglarını Temizle",
)
def clear_all_query_logs() -> Dict[str, str]:
    """
    Veritabanında biriken tüm sorgu audit log kayıtlarını siler.
    """
    query_logger.clear_logs()
    return {"status": "success", "message": "Tüm sorgu logları başarıyla temizlendi."}
