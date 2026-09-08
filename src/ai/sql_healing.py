"""
Doğal Dil İşlemeli Akıllı Veri Analiz Asistanı - Self-Healing SQL Mekanizması (SQLSelfHealingAgent)
Üretilen SQL sorgularında veritabanı seviyesinde (yanlış kolon, sözdizimi, JOIN vb.)
hata meydana geldiğinde, hata mesajını ve hatalı sorguyu yakalayarak LLM üzerinden
otomatik tamir döngüsü (Self-Healing Loop) işletir ve doğru sonuca ulaşır.
"""

from typing import Any, Dict, List, Optional, Tuple
import pandas as pd
from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import HumanMessage, SystemMessage

from src.ai.schema_manager import SchemaManager
from src.ai.sql_generator import SQLGenerator, OutOfDomainQueryError
from src.core.config import settings
from src.core.security import execute_safe_query
from src.tools.sql_validator import SQLValidator, SecurityViolationError


# ---------------------------------------------------------------------------
# Self-Healing System Prompt Şablonu
# ---------------------------------------------------------------------------
HEALING_SYSTEM_PROMPT_TEMPLATE = """Sen veritabanı hata teşhisi ve SQL düzeltme konusunda uzmanlaşmış kıdemli bir SQL Mühendisisin.
Daha önce üretilen bir SQL sorgusu veritabanında çalıştırılırken hata verdi.
Görevin, hata mesajını ve şema tanımlarını analiz ederek sorguyu düzeltmek ve hatasız, optimize edilmiş salt-okunur bir SQL sorgusu üretmektir.

{schema_context}

### 🚨 DÜZELTME TALİMATLARI:
1. **Hata Analizi**: Veritabanının döndürdüğü hata mesajını dikkatle incele (Örnek: "no such column", "no such table", "syntax error" vb.).
2. **Şema Kontrolü**: Tablo ve kolon adlarını şemadaki gerçek adlarıyla birebir eşleştir.
   - Boşluklu tablo adları için MUTLAKA çift tırnak kullan: `"Order Details"`.
   - SQLite diyalektine uygun fonksiyonları kullan (`strftime`, `||`, vb.).
3. **Yalnızca SELECT**: ASLA veri veya şema değiştiren komutlar yazma.
4. **Çıkış Formatı**: YALNIZCA düzeltilmiş saf SQL kodunu döndür. Markdown kod bloğu veya açıklama ekleme.
"""


class QueryExecutionError(Exception):
    """
    Sorgunun izin verilen deneme sayısında tamir edilemediği veya
    çalıştırma hatasının aşılamadığı durumlarda fırlatılan özel istisna.
    """

    def __init__(
        self,
        message: str,
        question: Optional[str] = None,
        last_sql: Optional[str] = None,
        attempts: Optional[List[str]] = None,
    ):
        super().__init__(message)
        self.message = message
        self.question = question
        self.last_sql = last_sql
        self.attempts = attempts or []


class SQLSelfHealingAgent:
    """
    Hatalı SQL sorgularını otomatik olarak tamir eden ve güvenli biçimde
    çalıştıran Self-Healing Ajanı.
    """

    def __init__(
        self,
        sql_generator: Optional[SQLGenerator] = None,
        schema_manager: Optional[SchemaManager] = None,
        max_retries: Optional[int] = None,
        llm: Optional[BaseChatModel] = None,
        provider: Optional[str] = None,
        model_name: Optional[str] = None,
    ):
        """
        SQLSelfHealingAgent yapılandırıcısı.

        Args:
            sql_generator: İlk SQL üretimini yapacak SQLGenerator örneği.
            schema_manager: Şema yöneticisi (None ise varsayılan oluşturulur).
            max_retries: Maksimum düzeltme deneme sayısı (None ise settings.MAX_RETRY_ATTEMPTS).
            llm: Tamir adımlarında kullanılacak özel LangChain ChatModel örneği.
            provider: LLM sağlayıcısı ('groq', 'gemini', 'openai', 'anthropic', 'ollama').
            model_name: Model adı (örn: 'llama-3.3-70b-versatile', 'gemini-1.5-flash').
        """
        self.schema_manager: SchemaManager = (
            schema_manager if schema_manager is not None else SchemaManager()
        )
        self.sql_generator: SQLGenerator = (
            sql_generator
            if sql_generator is not None
            else SQLGenerator(
                schema_manager=self.schema_manager,
                provider=provider,
                model_name=model_name,
                llm=llm,
            )
        )
        self.max_retries: int = (
            max_retries if max_retries is not None else settings.MAX_RETRY_ATTEMPTS
        )
        self._llm: Optional[BaseChatModel] = llm

    @property
    def llm(self) -> BaseChatModel:
        """Kullanılacak LLM istemcisi."""
        if self._llm is not None:
            return self._llm
        return self.sql_generator.llm

    @llm.setter
    def llm(self, value: Optional[BaseChatModel]) -> None:
        """Özel bir LLM istemcisi atar (Mock / Testing desteği)."""
        self._llm = value
        if self.sql_generator is not None:
            self.sql_generator.llm = value

    def build_healing_messages(
        self,
        question: str,
        failed_sql: str,
        error_message: str,
        table_names: Optional[List[str]] = None,
        max_relevant_tables: int = 5,
    ) -> List[Any]:
        """
        Hata mesajını, hatalı SQL'i ve şema bağlamını içeren tamir promptunu oluşturur.
        """
        if table_names is None:
            target_tables = self.schema_manager.get_relevant_tables(
                query=f"{question} {failed_sql}",
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

        system_content = HEALING_SYSTEM_PROMPT_TEMPLATE.format(schema_context=schema_context)
        
        human_content = (
            f"Kullanıcı Sorusu: {question}\n\n"
            f"❌ Önceki Hatalı SQL:\n```sql\n{failed_sql}\n```\n\n"
            f"⚠️ Alınan Veritabanı Hata Mesajı:\n{error_message}\n\n"
            f"Lütfen yukarıdaki hatayı düzelterek geçerli ve çalışan yalnızca SQL sorgusunu üret:"
        )

        return [
            SystemMessage(content=system_content),
            HumanMessage(content=human_content),
        ]

    def heal_sql(
        self,
        question: str,
        failed_sql: str,
        error_message: str,
        table_names: Optional[List[str]] = None,
    ) -> str:
        """
        Hatalı SQL sorgusunu ve hata mesajını LLM'e göndererek düzeltilmiş SQL üretir.
        """
        messages = self.build_healing_messages(
            question=question,
            failed_sql=failed_sql,
            error_message=error_message,
            table_names=table_names,
        )

        response = self.llm.invoke(messages)
        raw_output = response.content if hasattr(response, "content") else str(response)

        cleaned_sql = SQLGenerator.clean_sql_output(raw_output)
        return cleaned_sql

    def execute_with_healing(
        self,
        question: str,
        table_names: Optional[List[str]] = None,
        max_rows: Optional[int] = None,
    ) -> Tuple[pd.DataFrame, str, List[str]]:
        """
        Doğal dil sorusundan SQL üretir, çalıştırır ve hata alması durumunda
        maksimum 'max_retries' defa kendini tamir ederek veriyi çeker.

        Args:
            question: Kullanıcının doğal dildeki sorusu.
            table_names: İlgili tablolar (None ise otomatik tespit edilir).
            max_rows: Maksimum satır limiti.

        Returns:
            (df: pd.DataFrame, final_sql: str, repair_history: List[str])

        Raises:
            QueryExecutionError: Belirlenen deneme sayısı aşıldığında veya düzeltilemediğinde.
        """
        history: List[str] = []
        current_sql: str = ""
        last_error: str = ""

        # 0. Adım: Alan Dışı / Şema Dışı Soru Kontrolü (Halüsinasyon Önleme)
        if table_names is None:
            is_relevant, score, _ = self.schema_manager.is_query_domain_relevant(question)
            if not is_relevant:
                msg = "Bu soru veritabanı şemasında bulunan tablolarla ilişkili değildir."
                history.append(f"[Alan Dışı] {msg}")
                raise QueryExecutionError(
                    message=msg,
                    question=question,
                    last_sql="",
                    attempts=history,
                )

        for attempt in range(1, self.max_retries + 1):
            try:
                # 1. Adım: İlk denemede standart üretim yap, sonraki denemelerde tamir et
                if attempt == 1:
                    current_sql = self.sql_generator.generate_sql(
                        question=question,
                        table_names=table_names,
                    )
                    history.append(f"[Deneme {attempt}] İlk SQL üretildi: {current_sql}")
                else:
                    history.append(f"[Deneme {attempt}] Hata sonrası tamir ediliyor...")
                    current_sql = self.heal_sql(
                        question=question,
                        failed_sql=current_sql,
                        error_message=last_error,
                        table_names=table_names,
                    )
                    history.append(f"[Deneme {attempt}] Düzeltilmiş SQL üretildi: {current_sql}")

                # 2. Adım: AST Güvenlik Kontrolü
                validated_sql = SQLValidator.validate(current_sql)

                # 3. Adım: Salt-Okunur Veritabanında Çalıştır
                df = execute_safe_query(validated_sql, max_rows=max_rows)

                # Başarılı çalıştırma!
                history.append(f"[Başarılı] Sorgu {attempt}. denemede {len(df)} satır veri döndürdü.")
                return df, validated_sql, history

            except OutOfDomainQueryError as ood_err:
                history.append(f"[Alan Dışı] {ood_err.message}")
                raise QueryExecutionError(
                    message=ood_err.message,
                    question=question,
                    last_sql="",
                    attempts=history,
                )
            except Exception as exc:
                last_error = str(exc)
                history.append(f"[Deneme {attempt} Başarısız] Hata: {last_error}")

        # Tüm denemeler tükendi
        error_summary = (
            f"Maksimum deneme sayısı ({self.max_retries}) aşıldı. "
            f"Sorgu başarıyla çalıştırılamadı. Son Hata: {last_error}"
        )
        raise QueryExecutionError(
            message=error_summary,
            question=question,
            last_sql=current_sql,
            attempts=history,
        )
