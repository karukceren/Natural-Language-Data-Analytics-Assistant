import os
from typing import Optional, Literal
from pathlib import Path
from dotenv import load_dotenv

# .env dosyasını manuel de yükle
PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
ENV_PATH = PROJECT_ROOT / ".env"
if ENV_PATH.exists():
    load_dotenv(dotenv_path=ENV_PATH)
else:
    load_dotenv()

try:
    from pydantic_settings import BaseSettings, SettingsConfigDict

    class Settings(BaseSettings):
        """
        Uygulama genel yapılandırma ve ortam değişkenleri yönetim sınıfı (pydantic-settings).
        """
        APP_NAME: str = "Doğal Dil İşlemeli Akıllı Veri Analiz Asistanı"
        APP_ENV: Literal["development", "production", "testing"] = "development"
        DEBUG: bool = True

        OPENAI_API_KEY: Optional[str] = None
        ANTHROPIC_API_KEY: Optional[str] = None
        GROQ_API_KEY: Optional[str] = None
        GEMINI_API_KEY: Optional[str] = None
        OPENROUTER_API_KEY: Optional[str] = None
        OLLAMA_BASE_URL: str = "http://localhost:11434/v1"
        DATABASE_URL: str = "sqlite:///./data/northwind.db"

        DEFAULT_LLM_PROVIDER: str = "gemini"
        DEFAULT_MODEL_NAME: str = "gemini-2.5-flash"
        TEMPERATURE: float = 0.0

        SQL_TIMEOUT_SECONDS: int = 10
        MAX_ROW_LIMIT: int = 500
        MAX_RETRY_ATTEMPTS: int = 3

        model_config = SettingsConfigDict(
            env_file=str(ENV_PATH),
            env_file_encoding="utf-8",
            extra="ignore",
            case_sensitive=True,
        )

except ImportError:
    from pydantic import BaseModel, Field

    class Settings(BaseModel):
        """
        pydantic-settings paketi eksik olduğunda standart Pydantic v2 ve os.getenv ile çalışan yedek sınıf.
        """
        APP_NAME: str = Field(default_factory=lambda: os.getenv("APP_NAME", "Doğal Dil İşlemeli Akıllı Veri Analiz Asistanı"))
        APP_ENV: str = Field(default_factory=lambda: os.getenv("APP_ENV", "development"))
        DEBUG: bool = Field(default_factory=lambda: os.getenv("DEBUG", "True").lower() in ("true", "1", "yes"))

        OPENAI_API_KEY: Optional[str] = Field(default_factory=lambda: os.getenv("OPENAI_API_KEY") or None)
        ANTHROPIC_API_KEY: Optional[str] = Field(default_factory=lambda: os.getenv("ANTHROPIC_API_KEY") or None)
        GROQ_API_KEY: Optional[str] = Field(default_factory=lambda: os.getenv("GROQ_API_KEY") or None)
        GEMINI_API_KEY: Optional[str] = Field(default_factory=lambda: os.getenv("GEMINI_API_KEY") or None)
        OPENROUTER_API_KEY: Optional[str] = Field(default_factory=lambda: os.getenv("OPENROUTER_API_KEY") or None)
        OLLAMA_BASE_URL: str = Field(default_factory=lambda: os.getenv("OLLAMA_BASE_URL", "http://localhost:11434/v1"))
        DATABASE_URL: str = Field(default_factory=lambda: os.getenv("DATABASE_URL", "sqlite:///./data/northwind.db"))

        DEFAULT_LLM_PROVIDER: str = Field(default_factory=lambda: os.getenv("DEFAULT_LLM_PROVIDER", "gemini"))
        DEFAULT_MODEL_NAME: str = Field(default_factory=lambda: os.getenv("DEFAULT_MODEL_NAME", "gemini-2.5-flash"))
        TEMPERATURE: float = Field(default_factory=lambda: float(os.getenv("TEMPERATURE", "0.0")))

        SQL_TIMEOUT_SECONDS: int = Field(default_factory=lambda: int(os.getenv("SQL_TIMEOUT_SECONDS", "10")))
        MAX_ROW_LIMIT: int = Field(default_factory=lambda: int(os.getenv("MAX_ROW_LIMIT", "500")))
        MAX_RETRY_ATTEMPTS: int = Field(default_factory=lambda: int(os.getenv("MAX_RETRY_ATTEMPTS", "3")))


# Singleton settings nesnesi
settings = Settings()

