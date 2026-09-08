"""
Doğal Dil İşlemeli Akıllı Veri Analiz Asistanı - FastAPI Pydantic Şemaları (Schemas)
İstek (Request) ve Yanıt (Response) veri modellerini tanımlar.
"""

from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field


# ---------------------------------------------------------------------------
# 1. Sorgu (Query) Şemaları
# ---------------------------------------------------------------------------
class QueryRequest(BaseModel):
    """Kullanıcının doğal dilde ilettiği sorgu isteği şeması."""
    question: str = Field(
        ...,
        min_length=2,
        description="Analiz edilmek istenen doğal dil sorusu (Türkçe veya İngilizce)",
        examples=["En pahalı 5 ürünü fiyatıyla birlikte listele."],
    )
    provider: Optional[str] = Field(
        default=None,
        description="LLM Sağlayıcısı ('groq', 'gemini', 'openai', 'anthropic', 'ollama')",
    )
    model_name: Optional[str] = Field(
        default=None,
        description="Model adı (örn: 'llama-3.3-70b-versatile', 'gpt-4o', 'gemini-1.5-flash')",
    )
    api_key: Optional[str] = Field(
        default=None,
        description="Opsiyonel istek bazlı API anahtarı",
    )


class QueryResponse(BaseModel):
    """Sorgu çalıştırma ve analiz sonucu yanıt şeması."""
    sql: str = Field(..., description="Üretilen veya onarılan nihai SQL sorgusu")
    data: List[Dict[str, Any]] = Field(
        default_factory=list,
        description="Sorgu sonucu dönen tablosal kayıtlar (JSON liste)",
    )
    columns: List[str] = Field(
        default_factory=list,
        description="Sonuç tablosundaki sütun adları listesi",
    )
    chart_config: Dict[str, Any] = Field(
        default_factory=dict,
        description="Grafik motoru için belirlenen görselleştirme yapılandırması",
    )
    execution_time_ms: float = Field(
        ...,
        description="Toplam işlem ve yürütme süresi (milisaniye cinsinden)",
    )
    retry_count: int = Field(
        0,
        description="Self-healing mekanizmasının yaptığı tamir denemesi sayısı",
    )
    is_success: bool = Field(
        True,
        description="Sorgunun başarıyla üretilip çalıştırılma durumu",
    )
    error_message: Optional[str] = Field(
        None,
        description="Oluşan hata mesajı (varsa)",
    )
    repair_history: List[str] = Field(
        default_factory=list,
        description="Self-healing denemelerinde kaydedilen adım detayları",
    )
    summary: str = Field(
        "",
        description="Kullanıcıya sunulacak otomatik özet metni",
    )


# ---------------------------------------------------------------------------
# 2. Şema (Schema) Bilgisi Şemaları
# ---------------------------------------------------------------------------
class SchemaColumnInfo(BaseModel):
    """Tablo sütunu detay modeli."""
    name: str = Field(..., description="Kolon adı")
    type: str = Field(..., description="Veri tipi (INTEGER, VARCHAR vb.)")
    nullable: bool = Field(True, description="NULL değer alabilir mi?")
    is_primary_key: bool = Field(False, description="Primary Key mi?")


class SchemaTableInfo(BaseModel):
    """Tek bir tablonun detaylı şema ve DDL modeli."""
    table_name: str = Field(..., description="Tablo adı")
    description: str = Field("", description="Tablonun iş tanımı/açıklaması")
    columns: List[SchemaColumnInfo] = Field(default_factory=list, description="Kolon listesi")
    primary_keys: List[str] = Field(default_factory=list, description="Primary Key kolonları")
    foreign_keys: List[Dict[str, Any]] = Field(default_factory=list, description="Foreign Key ilişkileri")
    ddl: str = Field("", description="Tabloya ait standart CREATE TABLE DDL metni")


class SchemaResponse(BaseModel):
    """Tüm veritabanı şemasını içeren yanıt şeması."""
    table_count: int = Field(..., description="Veritabanındaki toplam tablo sayısı")
    tables: List[str] = Field(..., description="Mevcut tablo isimleri listesi")
    schema_details: List[SchemaTableInfo] = Field(
        default_factory=list,
        description="Tabloların detaylı şema tanımları",
    )
    relationships: List[Dict[str, Any]] = Field(
        default_factory=list,
        description="Tablolar arası Foreign Key ilişki bağlantıları",
    )


# ---------------------------------------------------------------------------
# 3. Log (QueryLog) Şemaları
# ---------------------------------------------------------------------------
class LogEntryItem(BaseModel):
    """Tekil sorgu logu kayıt modeli."""
    id: int = Field(..., description="Log ID")
    timestamp: Optional[str] = Field(None, description="Sorgunun işlendiği tarih ve saat")
    user_query: str = Field(..., description="Kullanıcı sorusu")
    generated_sql: Optional[str] = Field(None, description="Üretilen SQL")
    execution_time_ms: float = Field(..., description="Çalışma süresi (ms)")
    row_count: int = Field(..., description="Dönen satır sayısı")
    is_success: bool = Field(..., description="Başarı durumu")
    error_message: Optional[str] = Field(None, description="Hata mesajı (varsa)")
    retry_count: int = Field(..., description="Tamir deneme sayısı")


class LogsSummary(BaseModel):
    """Sorgu logları özet analitik istatistikleri."""
    total_queries: int = Field(0, description="Toplam sorgu sayısı")
    successful_queries: int = Field(0, description="Başarılı sorgu sayısı")
    failed_queries: int = Field(0, description="Başarısız sorgu sayısı")
    success_rate_percent: float = Field(0.0, description="Başarı oranı (%)")
    avg_execution_time_ms: float = Field(0.0, description="Ortalama yanıt süresi (ms)")
    avg_retry_count: float = Field(0.0, description="Ortalama tamir deneme sayısı")


class LogsResponse(BaseModel):
    """Sorgu logları ve özet metrikler yanıt modeli."""
    total_count: int = Field(..., description="Dönen log kayıt sayısı")
    logs: List[LogEntryItem] = Field(default_factory=list, description="Log kayıtları listesi")
    summary: LogsSummary = Field(..., description="Özet sistem metrikleri")


# ---------------------------------------------------------------------------
# 4. Sistem Sağlığı (Health) Şeması
# ---------------------------------------------------------------------------
class HealthResponse(BaseModel):
    """Sistem ve veritabanı sağlık kontrolü yanıt şeması."""
    status: str = Field("healthy", description="Sistem sağlık durumu ('healthy' veya 'degraded')")
    app_name: str = Field(..., description="Uygulama adı")
    database_type: str = Field("sqlite", description="Bağlı veritabanı motoru")
    database_connected: bool = Field(True, description="Veritabanı bağlantısı aktif mi?")
    table_count: int = Field(..., description="Mevcut tablo adedi")
    model_provider: str = Field(..., description="Aktif LLM sağlayıcısı")
    model_name: str = Field(..., description="Aktif LLM model adı")
