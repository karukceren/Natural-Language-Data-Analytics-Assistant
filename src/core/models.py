"""
Doğal Dil İşlemeli Akıllı Veri Analiz Asistanı - Veritabanı Modelleri (SQLAlchemy ORM)
Kullanıcı sorgularını, üretilen SQL ifadelerini, yürütme sürelerini ve hata kayıtlarını saklar.
"""

from datetime import datetime
from typing import Any, Dict, Optional
from sqlalchemy import Boolean, Column, DateTime, Float, Integer, Text
from src.core.database import Base


class QueryLog(Base):
    """
    Kullanıcı doğal dil sorguları, AI tarafından üretilen SQL'ler,
    yanıt süreleri ve yürütme sonuçlarını kaydeden log tablosu modeli.
    """

    __tablename__ = "query_logs"

    id = Column(Integer, primary_key=True, autoincrement=True)
    timestamp = Column(DateTime, default=datetime.utcnow, nullable=False, index=True)
    user_query = Column(Text, nullable=False)
    generated_sql = Column(Text, nullable=True)
    execution_time_ms = Column(Float, default=0.0, nullable=False)
    row_count = Column(Integer, default=0, nullable=False)
    is_success = Column(Boolean, default=True, nullable=False, index=True)
    error_message = Column(Text, nullable=True)
    retry_count = Column(Integer, default=0, nullable=False)

    def to_dict(self) -> Dict[str, Any]:
        """Model nesnesini sözlük formatına dönüştürür."""
        return {
            "id": self.id,
            "timestamp": self.timestamp.isoformat() if self.timestamp else None,
            "user_query": self.user_query,
            "generated_sql": self.generated_sql,
            "execution_time_ms": round(self.execution_time_ms, 2),
            "row_count": self.row_count,
            "is_success": self.is_success,
            "error_message": self.error_message,
            "retry_count": self.retry_count,
        }

    def __repr__(self) -> str:
        status = "SUCCESS" if self.is_success else "FAILED"
        return f"<QueryLog id={self.id} status={status} time={self.execution_time_ms}ms query='{self.user_query[:30]}...'>"
