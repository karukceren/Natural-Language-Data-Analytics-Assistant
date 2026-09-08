"""
Doğal Dil İşlemeli Akıllı Veri Analiz Asistanı - Sorgu Loglama ve İzleme Servisi (QueryLogger)
Kullanıcı sorularını, SQL çıktılarını, yürütme sürelerini, satır sayılarını ve hata kayıtlarını
veritabanında depolar ve yönetim paneli / analitik izleme için istatistikler üretir.
"""

from typing import Any, Dict, List, Optional
import pandas as pd
from sqlalchemy import func, inspect
from sqlalchemy.orm import Session, sessionmaker

from src.core.database import Base, SessionLocal, engine as default_engine
from src.core.models import QueryLog


class QueryLogger:
    """
    Sorgu loglarını veritabanına kaydeden ve analitik özetlerini çıkaran servis sınıfı.
    """

    def __init__(self, engine=None, session_factory=None):
        """
        QueryLogger yapılandırıcısı.

        Args:
            engine: SQLAlchemy Engine nesnesi (None ise varsayılan engine kullanılır).
            session_factory: SQLAlchemy Session fabrikası (None ise SessionLocal kullanılır).
        """
        self.engine = engine if engine is not None else default_engine
        self.session_factory = session_factory if session_factory is not None else SessionLocal

        # Tablonun varlığını denetle ve yoksa oluştur
        self._init_db()

    def _init_db(self) -> None:
        """QueryLog tablosunu veritabanında otomatik oluşturur."""
        try:
            Base.metadata.create_all(bind=self.engine, tables=[QueryLog.__table__])
        except Exception:
            pass

    def log_query(
        self,
        user_query: str,
        generated_sql: Optional[str] = None,
        execution_time_ms: float = 0.0,
        row_count: int = 0,
        is_success: bool = True,
        error_message: Optional[str] = None,
        retry_count: int = 0,
    ) -> int:
        """
        Yeni bir sorgu yürütme kaydı oluşturur ve veritabanına yazar.

        Args:
            user_query: Kullanıcının girdiği doğal dil sorusu.
            generated_sql: Üretilen veya düzeltilen nihai SQL sorgusu.
            execution_time_ms: AI üretim ve DB çalıştırma toplam süresi (ms).
            row_count: Dönen sonuç satır sayısı.
            is_success: Sorgu başarıyla çalıştı mı?
            error_message: Varsa hata detayı.
            retry_count: Self-healing döngüsündeki deneme sayısı.

        Returns:
            Oluşturulan kaydın ID'si.
        """
        session: Session = self.session_factory()
        try:
            log_entry = QueryLog(
                user_query=user_query,
                generated_sql=generated_sql,
                execution_time_ms=execution_time_ms,
                row_count=row_count,
                is_success=is_success,
                error_message=error_message,
                retry_count=retry_count,
            )
            session.add(log_entry)
            session.commit()
            session.refresh(log_entry)
            return log_entry.id
        except Exception as exc:
            session.rollback()
            raise exc
        finally:
            session.close()

    def get_recent_logs(self, limit: int = 50) -> pd.DataFrame:
        """
        Son sorgu kayıtlarını azalan zaman sırasına göre bir pandas DataFrame olarak döndürür.

        Args:
            limit: Döndürülecek maksimum kayıt sayısı.

        Returns:
            Log kayıtlarını içeren pandas.DataFrame.
        """
        session: Session = self.session_factory()
        try:
            records = (
                session.query(QueryLog)
                .order_by(QueryLog.timestamp.desc())
                .limit(limit)
                .all()
            )

            if not records:
                return pd.DataFrame(
                    columns=[
                        "id",
                        "timestamp",
                        "user_query",
                        "generated_sql",
                        "execution_time_ms",
                        "row_count",
                        "is_success",
                        "error_message",
                        "retry_count",
                    ]
                )

            data = [r.to_dict() for r in records]
            df = pd.DataFrame(data)
            return df
        finally:
            session.close()

    def get_logs_summary(self) -> Dict[str, Any]:
        """
        İzleme paneli için log kayıtlarının genel istatistiklerini hesaplar.

        Returns:
            {
                "total_queries": int,
                "successful_queries": int,
                "failed_queries": int,
                "success_rate_percent": float,
                "avg_execution_time_ms": float,
                "avg_retry_count": float
            }
        """
        session: Session = self.session_factory()
        try:
            total_count = session.query(func.count(QueryLog.id)).scalar() or 0
            if total_count == 0:
                return {
                    "total_queries": 0,
                    "successful_queries": 0,
                    "failed_queries": 0,
                    "success_rate_percent": 100.0,
                    "avg_execution_time_ms": 0.0,
                    "avg_retry_count": 0.0,
                }

            success_count = (
                session.query(func.count(QueryLog.id))
                .filter(QueryLog.is_success == True)  # noqa: E712
                .scalar()
                or 0
            )
            failed_count = total_count - success_count
            success_rate = round((success_count / total_count) * 100.0, 2)

            avg_time = (
                session.query(func.avg(QueryLog.execution_time_ms)).scalar() or 0.0
            )
            avg_retries = (
                session.query(func.avg(QueryLog.retry_count)).scalar() or 0.0
            )

            return {
                "total_queries": total_count,
                "successful_queries": success_count,
                "failed_queries": failed_count,
                "success_rate_percent": success_rate,
                "avg_execution_time_ms": round(float(avg_time), 2),
                "avg_retry_count": round(float(avg_retries), 2),
            }
        finally:
            session.close()

    def clear_logs(self) -> int:
        """Tüm log kayıtlarını siler (Test ve bakım amaçlı)."""
        session: Session = self.session_factory()
        try:
            deleted = session.query(QueryLog).delete()
            session.commit()
            return deleted
        except Exception as exc:
            session.rollback()
            raise exc
        finally:
            session.close()


# Singleton instance
query_logger = QueryLogger()
