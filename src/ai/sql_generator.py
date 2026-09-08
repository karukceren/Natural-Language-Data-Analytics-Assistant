"""
Doğal Dil İşlemeli Akıllı Veri Analiz Asistanı - Text-to-SQL Üreteci (SQLGenerator)
Kullanıcının doğal dildeki (Türkçe / İngilizce) sorularını SchemaManager'dan
alınan zenginleştirilmiş şema bilgisi ve FewShotManager'dan alınan örneklerle
birleştirip LLM (OpenAI / Anthropic) aracılığıyla güvenli, optimize ve
çalıştırılabilir SQL sorgularına dönüştürür.
"""

import os
import re
from typing import Any, Dict, List, Optional, Tuple
from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, SystemMessage
from langchain_core.prompts import (
    ChatPromptTemplate,
    FewShotChatMessagePromptTemplate,
)

from src.ai.few_shot_manager import FewShotManager
from src.ai.schema_manager import SchemaManager
from src.core.config import settings
from src.core.database import execute_read_only_query


class OutOfDomainQueryError(ValueError):
    """
    Kullanıcının sorduğu sorunun veritabanı şeması ve iş alanı ile hiçbir ilgisi
    olmadığında (örn: şifreler, bitcoin, hava durumu vb.) fırlatılan özel hata sınıfı.
    """
    def __init__(self, message: str = "Bu soru veritabanı şemasında bulunan tablolarla ilişkili değildir."):
        super().__init__(message)
        self.message = message


# ---------------------------------------------------------------------------
# Text-to-SQL System Prompt Şablonu (1. Katman: Sistem & Güvenlik Kuralları)
# ---------------------------------------------------------------------------
SQL_SYSTEM_RULES_TEMPLATE = """Sen kurumsal bir veri ambarında görevli uzman bir SQL Mühendisi ve Veri Analistisin.
Görevin, kullanıcının doğal dilde (Türkçe veya İngilizce) sorduğu soruları, aşağıda verilen veritabanı şemasına ve iş kurallarına tam uyumlu, optimize edilmiş ve hatasız bir SQL sorgusuna dönüştürmektir.

### 🚨 ÇOK ÖNEMLİ KURALLAR VE TALİMATLAR:
1. **Sadece SELECT Sorguları**: ASLA `DROP`, `DELETE`, `INSERT`, `UPDATE`, `ALTER`, `TRUNCATE`, `EXEC`, `CREATE`, `ATTACH` veya `PRAGMA` gibi veriyi/şemayı değiştiren komutlar yazma. YALNIZCA salt okunur `SELECT` sorguları üret.
2. **Diyalekt Uyumluluğu (SQLite)**:
   - Boşluk içeren tablo isimlerini (özellikle `"Order Details"`) MUTLAKA çift tırnak (`"`) içine al. Örnek: `FROM "Order Details"` veya `JOIN "Order Details" ON ...`.
   - SQLite tarih fonksiyonlarına dikkat et: Yıl filtreleri için `strftime('%Y', OrderDate) = '1997'` veya `OrderDate LIKE '1997%'` veya `substr(OrderDate, 1, 4) = '1997'` kullanabilirsin.
   - Metin birleştirme için `||` operatörünü kullan (Örnek: `FirstName || ' ' || LastName AS FullName`).
3. **Tablo Birleştirmeleri (JOIN)**:
   - Şema rehberindeki Foreign Key ilişkilerine sadık kal.
   - Örneğin `Customers` ve `Products` bilgilerini bağlamak için `Orders` ve `"Order Details"` tablolarını ara tablo (köprü) olarak kullan.
4. **Gruplama ve Sıralama**:
   - Agregasyon (`COUNT`, `SUM`, `AVG`, `MAX`, `MIN`) yapılan sorgularda `GROUP BY` ifadesini eksiksiz yaz.
   - "En çok", "en pahalı", "ilk N" gibi isteklerde `ORDER BY ... DESC LIMIT N` kullan.
5. **Çıkış Formatı**:
   - YALNIZCA saf SQL kodunu döndür.
   - Açıklama, markdown kod bloğu (```sql veya ```), selamlaşma veya ek yorum ASLA EKLEME. Sadece çalıştırılabilir SQL metnini döndür.
6. **Alan Dışı ve Geçersiz Sorular (Out-of-Domain)**:
   - Eğer soru veritabanı şemasında bulunmayan tamamen alakasız varlıklar hakkındaysa (Örnek: "Bitcoin fiyatı", "Kullanıcı şifreleri", "Hava durumu" vb.), asla uydurma/halüsinasyon SQL üretme. YALNIZCA `OUT_OF_DOMAIN` metnini döndür.
7. **Göreceli Tarih Filtreleri (Geçen ay, son ay, son yıl vb.)**:
   - Veritabanı geçmiş dönem verilerini içerdiğinden, "geçen ay", "son ay", "son dönem", "bu yıl" gibi göreceli zaman filtrelerinde bugünün gerçek takvim tarihi (`DATE('now')`) yerine veritabanındaki en son sipariş tarihini baz al: `(SELECT MAX(OrderDate) FROM Orders)`.
   - Örnek (Son/Geçen Ay): `WHERE strftime('%Y-%m', o.OrderDate) = (SELECT strftime('%Y-%m', MAX(OrderDate)) FROM Orders)`
   - Örnek (Son/Geçen Yıl): `WHERE strftime('%Y', o.OrderDate) = (SELECT strftime('%Y', MAX(OrderDate)) FROM Orders)`
"""

# Geriye dönük uyumluluk takma adı (Alias)
SQL_SYSTEM_PROMPT_TEMPLATE = SQL_SYSTEM_RULES_TEMPLATE


class SQLGenerator:
    """
    Doğal dil sorularını Few-Shot destekli SQL sorgularına dönüştüren ve güvenliğini denetleyen sınıf.
    """

    def __init__(
        self,
        schema_manager: Optional[SchemaManager] = None,
        few_shot_manager: Optional[FewShotManager] = None,
        provider: Optional[str] = None,
        model_name: Optional[str] = None,
        temperature: Optional[float] = None,
        llm: Optional[BaseChatModel] = None,
    ):
        """
        SQLGenerator yapılandırıcısı.

        Args:
            schema_manager: Şema ve metadata yöneticisi (None ise varsayılan oluşturulur).
            few_shot_manager: Few-shot örnek yöneticisi (None ise varsayılan oluşturulur).
            provider: 'openai' veya 'anthropic' (None ise settings'den okunur).
            model_name: LLM model adı (ör. 'gpt-4o', 'claude-3-5-sonnet-20241022').
            temperature: Yaratıcılık katsayısı (SQL için önerilen 0.0).
            llm: Doğrudan özel bir LangChain ChatModel örneği (Testlerde Mock/Fake LLM için).
        """
        self.schema_manager: SchemaManager = (
            schema_manager if schema_manager is not None else SchemaManager()
        )
        self.few_shot_manager: FewShotManager = (
            few_shot_manager if few_shot_manager is not None else FewShotManager()
        )
        self.provider = (provider or settings.DEFAULT_LLM_PROVIDER).lower()
        self.model_name = model_name or settings.DEFAULT_MODEL_NAME
        self.temperature = temperature if temperature is not None else settings.TEMPERATURE
        
        self._llm: Optional[BaseChatModel] = llm

    @property
    def llm(self) -> BaseChatModel:
        """
        LangChain ChatModel istemcisini tembel (lazy) olarak ilklendirir.
        """
        if self._llm is not None:
            return self._llm

        if self.provider == "openai":
            from langchain_openai import ChatOpenAI
            from dotenv import load_dotenv
            load_dotenv(override=True)
            api_key = os.getenv("OPENAI_API_KEY") or settings.OPENAI_API_KEY
            if not api_key or not api_key.strip():
                raise ValueError(
                    "OpenAI API anahtarı bulunamadı! Lütfen .env dosyasına OPENAI_API_KEY ekleyin ve dosyayı kaydedin (Ctrl+S)."
                )
            self._llm = ChatOpenAI(
                model=self.model_name or "gpt-4o",
                temperature=self.temperature,
                api_key=api_key.strip(),
            )
        elif self.provider == "anthropic":
            from langchain_anthropic import ChatAnthropic
            from dotenv import load_dotenv
            load_dotenv(override=True)
            api_key = os.getenv("ANTHROPIC_API_KEY") or settings.ANTHROPIC_API_KEY
            if not api_key or not api_key.strip():
                raise ValueError(
                    "Anthropic API anahtarı bulunamadı! Lütfen .env dosyasına ANTHROPIC_API_KEY ekleyin ve dosyayı kaydedin (Ctrl+S)."
                )
            self._llm = ChatAnthropic(
                model_name=self.model_name or "claude-3-5-sonnet-20241022",
                temperature=self.temperature,
                api_key=api_key.strip(),
            )
        elif self.provider == "groq":
            from langchain_openai import ChatOpenAI
            from dotenv import load_dotenv
            load_dotenv(override=True)
            api_key = os.getenv("GROQ_API_KEY") or settings.GROQ_API_KEY
            if not api_key or not api_key.strip():
                raise ValueError(
                    "Groq API anahtarı bulunamadı! Lütfen .env dosyasına GROQ_API_KEY ekleyin veya sol menüden girin."
                )
            model = self.model_name if self.model_name not in ("gpt-4o", "gpt-4o-mini", "claude-3-5-sonnet-20241022") else "llama-3.3-70b-versatile"
            self._llm = ChatOpenAI(
                model=model,
                temperature=self.temperature,
                api_key=api_key.strip(),
                base_url="https://api.groq.com/openai/v1",
            )
        elif self.provider in ("gemini", "google"):
            from langchain_openai import ChatOpenAI
            from dotenv import load_dotenv
            load_dotenv(override=True)
            api_key = os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY") or settings.GEMINI_API_KEY
            if not api_key or not api_key.strip():
                raise ValueError(
                    "Google Gemini API anahtarı bulunamadı! Lütfen .env dosyasına GEMINI_API_KEY ekleyin."
                )
            # Google Gemini 2.5 / Flash uyumluluğu
            req_model = (self.model_name or "").lower()
            if "1.5" in req_model or not req_model or "gemini" not in req_model:
                model = "gemini-2.5-flash"
            else:
                model = self.model_name
            self._llm = ChatOpenAI(
                model=model,
                temperature=self.temperature,
                api_key=api_key.strip(),
                base_url="https://generativelanguage.googleapis.com/v1beta/openai/",
            )
        elif self.provider == "openrouter":
            from langchain_openai import ChatOpenAI
            from dotenv import load_dotenv
            load_dotenv(override=True)
            api_key = os.getenv("OPENROUTER_API_KEY") or settings.OPENROUTER_API_KEY
            if not api_key or not api_key.strip():
                raise ValueError(
                    "OpenRouter API anahtarı bulunamadı! Lütfen .env dosyasına OPENROUTER_API_KEY ekleyin."
                )
            model = self.model_name or "meta-llama/llama-3.3-70b-instruct:free"
            self._llm = ChatOpenAI(
                model=model,
                temperature=self.temperature,
                api_key=api_key.strip(),
                base_url="https://openrouter.ai/api/v1",
            )
        elif self.provider == "ollama":
            from langchain_openai import ChatOpenAI
            model = self.model_name or "llama3.1"
            self._llm = ChatOpenAI(
                model=model,
                temperature=self.temperature,
                api_key="ollama",
                base_url=settings.OLLAMA_BASE_URL,
            )
        else:
            raise ValueError(f"Desteklenmeyen LLM sağlayıcısı: {self.provider}")

        return self._llm

    @llm.setter
    def llm(self, value: Optional[BaseChatModel]) -> None:
        """Özel bir LLM istemcisi atar (Mock / Testing desteği)."""
        self._llm = value

    def build_prompt_messages(
        self,
        question: str,
        table_names: Optional[List[str]] = None,
        max_relevant_tables: int = 5,
        max_few_shot_examples: int = 4,
        use_chat_few_shot_template: bool = True,
    ) -> List[BaseMessage]:
        """
        4 Katmanlı Hiyerarşik Prompt Yapısını Oluşturur:
          1. Sistem & Güvenlik Kuralları
          2. Veritabanı Şeması, DDL ve Tablo İlişkileri (SchemaManager)
          3. Few-Shot Örnek Soru & SQL Eşleşmeleri (FewShotManager)
          4. Kullanıcının Güncel Sorusu

        Args:
            question: Kullanıcı sorusu.
            table_names: Zorunlu tutulacak tablolar (None ise otomatik filtrelenir).
            max_relevant_tables: Şemaya dahil edilecek maksimum ilgili tablo sayısı.
            max_few_shot_examples: Prompta dahil edilecek maksimum few-shot örnek sayısı.
            use_chat_few_shot_template: Few-shot örneklerini ayrı Human/AI mesajları olarak ekleme (True)
                                        veya System mesajı içine metin olarak gömme (False).

        Returns:
            LangChain BaseMessage listesi.
        """
        # 1 & 2. Katman: Şema ve Tablo Seçimi
        if table_names is None:
            target_tables = self.schema_manager.get_relevant_tables(
                query=question,
                max_tables=max_relevant_tables,
                include_foreign_keys=True,
            )
        else:
            target_tables = table_names

        schema_context = self.schema_manager.get_formatted_schema(
            table_names=target_tables,
            include_descriptions=True,
            include_relationships=True,
        )

        system_prompt_content = f"{SQL_SYSTEM_RULES_TEMPLATE}\n\n{schema_context}"

        # 3. Katman: Soruya en uygun Few-Shot örneklerini seç
        few_shot_examples = self.few_shot_manager.get_examples(
            query=question,
            max_examples=max_few_shot_examples,
        )

        messages: List[BaseMessage] = []

        if use_chat_few_shot_template and few_shot_examples:
            # LangChain FewShotChatMessagePromptTemplate ile çok turlu (Multi-turn) mesaj yapısı
            messages.append(SystemMessage(content=system_prompt_content))

            for ex in few_shot_examples:
                messages.append(
                    HumanMessage(
                        content=f"Kullanıcı Sorusu: {ex['question']}\n\nLütfen yalnızca yukarıdaki kurallara uygun SQL sorgusunu üret:"
                    )
                )
                messages.append(AIMessage(content=ex["sql"]))

            # 4. Katman: Güncel Kullanıcı Sorusu
            messages.append(
                HumanMessage(
                    content=f"Kullanıcı Sorusu: {question}\n\nLütfen yalnızca yukarıdaki kurallara uygun SQL sorgusunu üret:"
                )
            )
        else:
            # Tekil System + Human mesaj yapısı
            few_shot_text = self.few_shot_manager.format_examples_text(
                examples=few_shot_examples
            )
            full_system_content = f"{system_prompt_content}\n\n{few_shot_text}" if few_shot_text else system_prompt_content

            messages.append(SystemMessage(content=full_system_content))
            messages.append(
                HumanMessage(
                    content=f"Kullanıcı Sorusu: {question}\n\nLütfen yalnızca yukarıdaki kurallara uygun SQL sorgusunu üret:"
                )
            )

        return messages

    @staticmethod
    def clean_sql_output(raw_sql: str) -> str:
        """
        LLM tarafından üretilen ham metindeki Markdown kod bloklarını (```sql ... ```),
        başındaki ve sonundaki boşlukları, tırnakları ve gereksiz noktalı virgülleri temizler.
        """
        if not raw_sql:
            return ""

        cleaned = raw_sql.strip()

        # 1. ```sql ... ``` veya ``` ... ``` bloklarını ayıkla
        markdown_match = re.search(r"```(?:sql)?\s*([\s\S]*?)\s*```", cleaned, re.IGNORECASE)
        if markdown_match:
            cleaned = markdown_match.group(1).strip()

        # 2. "SQL:" veya "Query:" gibi olası ön ekleri temizle
        cleaned = re.sub(r"^(?:SQL|Query|Sorgu)\s*:\s*", "", cleaned, flags=re.IGNORECASE).strip()

        # 3. Birden fazla satırdaki gereksiz çift satır başlarını tek satıra indir
        cleaned = re.sub(r"\n\s*\n", "\n", cleaned)

        # 4. Sondaki noktalı virgülü kaldır (SQLAlchemy execution standartlığı için)
        cleaned = cleaned.rstrip(";").strip()

        return cleaned

    @staticmethod
    def validate_safety(sql: str) -> Tuple[bool, Optional[str]]:
        """
        Sorgunun yalnızca güvenli SELECT sorgusu olduğunu SQLValidator ile doğrular.
        Zararlı DML/DDL (DROP, DELETE, INSERT, UPDATE, ALTER, TRUNCATE, EXEC, ATTACH vb.)
        ifadeleri tespit edilirse (False, Hata Mesajı) döner.
        """
        from src.tools.sql_validator import SQLValidator
        is_safe, error_msg = SQLValidator.is_valid_select(sql)
        return is_safe, (error_msg if not is_safe else None)

    def generate_sql(
        self,
        question: str,
        table_names: Optional[List[str]] = None,
        max_relevant_tables: int = 5,
        max_few_shot_examples: int = 4,
    ) -> str:
        """
        Doğal dil sorusunu Few-Shot zenginleştirilmiş bağlamla işleyip güvenli SQL sorgusu üretir.

        Args:
            question: Kullanıcının doğal dildeki sorusu.
            table_names: Zorunlu tutulmak istenen tablo listesi (None ise otomatik seçilir).
            max_relevant_tables: Otomatik seçimde alınacak maksimum tablo sayısı.
            max_few_shot_examples: Dahil edilecek maksimum few-shot örnek sayısı.

        Returns:
            Temizlenmiş ve doğrulanmış SQL sorgusu metni.

        Raises:
            ValueError: Güvenlik doğrulamasından geçemeyen veya boş dönen sorgularda.
        """
        messages = self.build_prompt_messages(
            question=question,
            table_names=table_names,
            max_relevant_tables=max_relevant_tables,
            max_few_shot_examples=max_few_shot_examples,
        )

        response = self.llm.invoke(messages)
        raw_output = response.content if hasattr(response, "content") else str(response)

        cleaned_sql = self.clean_sql_output(raw_output)

        if "OUT_OF_DOMAIN" in cleaned_sql.upper():
            raise OutOfDomainQueryError("Bu soru veritabanı şemasında bulunan tablolarla ilişkili değildir.")

        is_safe, error_msg = self.validate_safety(cleaned_sql)
        if not is_safe:
            raise ValueError(f"Üretilen SQL güvenlik testini geçemedi: {error_msg}\nÜretilen: {cleaned_sql}")

        return cleaned_sql

    def generate_and_execute(
        self,
        question: str,
        table_names: Optional[List[str]] = None,
        limit: Optional[int] = None,
    ) -> Dict[str, Any]:
        """
        Doğal dil sorusundan SQL üretir ve veritabanında çalıştırarak sonuçları döner.

        Returns:
            {
                "question": question,
                "generated_sql": sql,
                "columns": [...],
                "rows": [...],
                "row_count": N,
                "status": "success" | "error",
                "error": error_message (varsa)
            }
        """
        try:
            sql = self.generate_sql(question, table_names=table_names)
            result = execute_read_only_query(sql, limit=limit)
            return {
                "question": question,
                "generated_sql": sql,
                "columns": result["columns"],
                "rows": result["rows"],
                "row_count": result["row_count"],
                "status": "success",
                "error": None,
            }
        except Exception as exc:
            return {
                "question": question,
                "generated_sql": getattr(locals(), "sql", None),
                "columns": [],
                "rows": [],
                "row_count": 0,
                "status": "error",
                "error": str(exc),
            }
