"""
FewShotManager ve Few-Shot destekli SQLGenerator için birim ve entegrasyon testleri.
"""

from typing import List
import pytest
from langchain_core.messages import AIMessage, BaseMessage
from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.outputs import ChatGeneration, ChatResult

from src.ai.few_shot_manager import FewShotManager, NORTHWIND_FEW_SHOT_EXAMPLES
from src.ai.schema_manager import SchemaManager
from src.ai.sql_generator import SQLGenerator
from src.core.database import execute_read_only_query, engine
from src.tools.sql_validator import SQLValidator


@pytest.fixture
def few_shot_manager():
    """FewShotManager örneği oluşturan fixture."""
    return FewShotManager()


# ---------------------------------------------------------------------------
# 1. Few-Shot Örnek Kütüphanesi Kapsam ve Doğruluk Testleri
# ---------------------------------------------------------------------------

def test_few_shot_mandatory_examples_exist(few_shot_manager):
    """Kullanıcının talep ettiği tüm zorunlu örnek soruların mevcut olduğunu doğrular."""
    mandatory_questions = [
        "1997 yılında en çok ciro yapan ilk 5 çalışan kimdir?",
        "Stok miktarı 10'un altına düşmüş ürünlerin tedarikçi şirket adları nelerdir?",
        "Hiç sipariş vermemiş müşterileri listele.",
        "Her kategorideki toplam ürün sayısını ve ortalama fiyatı getir.",
    ]
    examples = few_shot_manager.get_examples()
    existing_questions = [ex["question"] for ex in examples]

    for mq in mandatory_questions:
        assert any(mq.lower() in eq.lower() for eq in existing_questions), f"Eksik zorunlu örnek: {mq}"


def test_all_few_shot_sql_queries_pass_security_and_execute(few_shot_manager):
    """
    Kütüphanedeki tüm Few-Shot SQL sorgularının:
      1. SQLValidator güvenlik testinden (is_valid_select) geçtiğini,
      2. northwind.db üzerinde SQL syntax hatası vermeden çalıştığını doğrular.
    """
    for ex in NORTHWIND_FEW_SHOT_EXAMPLES:
        sql = ex["sql"]
        # 1. Güvenlik Denetimi
        is_safe, msg = SQLValidator.is_valid_select(sql)
        assert is_safe is True, f"Güvenlik ihlali: {ex['question']} -> {msg}"

        # 2. Veritabanında Çalıştırma Denetimi
        res = execute_read_only_query(sql)
        assert "columns" in res and len(res["columns"]) > 0
        assert "rows" in res
        assert "row_count" in res


# ---------------------------------------------------------------------------
# 2. FewShotManager Filtreleme ve Formatlama Testleri
# ---------------------------------------------------------------------------

def test_few_shot_manager_ranking_by_relevance(few_shot_manager):
    """Kullanıcı sorusuna en çok uyan Few-Shot örneğinin en başa sıralandığını doğrular."""
    # Senaryo 1: Ciro ve Çalışan sorusu
    q1 = "Geçen yıl en çok ciro yapan personeller kimlerdir?"
    ranked1 = few_shot_manager.get_examples(query=q1, max_examples=3)
    assert len(ranked1) == 3
    assert "ciro" in ranked1[0]["question"].lower() or "çalışan" in ranked1[0]["question"].lower()

    # Senaryo 2: Tedarikçi ve Stok sorusu
    q2 = "Hangi ürünlerin stoğu azaldı ve tedarikçisi kim?"
    ranked2 = few_shot_manager.get_examples(query=q2, max_examples=3)
    assert "stok" in ranked2[0]["question"].lower() or "tedarikçi" in ranked2[0]["question"].lower()

    # Senaryo 3: Hiç siparişi olmayan müşteriler
    q3 = "Hiç alışveriş yapmamış müşteriler listesi"
    ranked3 = few_shot_manager.get_examples(query=q3, max_examples=3)
    assert "sipariş vermemiş" in ranked3[0]["question"].lower() or "müşteri" in ranked3[0]["question"].lower()


def test_format_examples_text(few_shot_manager):
    """format_examples_text fonksiyonunun temiz markdown ürettiğini doğrular."""
    formatted = few_shot_manager.format_examples_text(max_examples=2)
    assert "FEW-SHOT EXAMPLES" in formatted
    assert "Örnek 1:" in formatted
    assert "```sql" in formatted
    assert "Soru:" in formatted


def test_get_few_shot_prompt_template(few_shot_manager):
    """LangChain FewShotChatMessagePromptTemplate nesnesinin doğru oluşturulduğunu doğrular."""
    template = few_shot_manager.get_few_shot_prompt_template(max_examples=2)
    assert template is not None
    assert len(template.examples) == 2


# ---------------------------------------------------------------------------
# 3. SQLGenerator Entegrasyonu & 4 Katmanlı Prompt Testleri
# ---------------------------------------------------------------------------

class MockFewShotChatModel(BaseChatModel):
    """Prompt mesajlarını kaydeden ve sahte SQL dönen Mock LLM."""
    last_messages: list = []

    def _generate(
        self,
        messages: List[BaseMessage],
        stop: list = None,
        run_manager = None,
        **kwargs,
    ) -> ChatResult:
        MockFewShotChatModel.last_messages = messages
        message = AIMessage(
            content="SELECT e.EmployeeID, SUM(od.UnitPrice * od.Quantity) AS Revenue FROM Employees e JOIN Orders o ON e.EmployeeID = o.EmployeeID JOIN \"Order Details\" od ON o.OrderID = od.OrderID GROUP BY e.EmployeeID ORDER BY Revenue DESC LIMIT 5"
        )
        return ChatResult(generations=[ChatGeneration(message=message)])

    @property
    def _llm_type(self) -> str:
        return "mock-few-shot-chat-model"


def test_sql_generator_build_prompt_messages_hierarchy():
    """
    SQLGenerator'ın 4 katmanlı hiyerarşik prompt yapısını eksiksiz kurduğunu doğrular:
      1. Sistem & Güvenlik Kuralları
      2. Şema & DDL & İlişkiler
      3. Few-Shot Örnek Soru & SQL Eşleşmeleri
      4. Güncel Kullanıcı Sorusu
    """
    schema_mgr = SchemaManager(engine=engine)
    few_shot_mgr = FewShotManager()
    mock_llm = MockFewShotChatModel()

    generator = SQLGenerator(
        schema_manager=schema_mgr,
        few_shot_manager=few_shot_mgr,
        llm=mock_llm,
    )

    question = "1997 yılında en çok sipariş alan personeller kimlerdir?"
    messages = generator.build_prompt_messages(question, max_few_shot_examples=3)

    # 1. SystemMessage kontrolü (Kurallar + Şema)
    assert len(messages) >= 7  # 1 System + (3 Human + 3 AI) Few-Shots + 1 Final Human
    system_msg = messages[0].content
    assert "Sadece SELECT Sorguları" in system_msg
    assert "Diyalekt Uyumluluğu (SQLite)" in system_msg
    assert "VERİTABANI ŞEMA VE METADATA TANIMLARI" in system_msg

    # 2. Few-Shot mesaj çiftleri kontrolü
    has_few_shot_human = any("Kullanıcı Sorusu:" in m.content for m in messages[1:-1] if m.type == "human")
    has_few_shot_ai = any("SELECT" in m.content for m in messages[1:-1] if m.type == "ai")
    assert has_few_shot_human is True
    assert has_few_shot_ai is True

    # 3. Son Kullanıcı Sorusu kontrolü
    last_msg = messages[-1]
    assert last_msg.type == "human"
    assert "1997 yılında en çok sipariş alan personeller kimlerdir?" in last_msg.content


def test_complex_join_sql_generation_and_execution():
    """
    Karmaşık JOIN içeren bir senaryoda SQLGenerator'ın SQL üretip veritabanında çalıştırdığını doğrular.
    """
    schema_mgr = SchemaManager(engine=engine)
    few_shot_mgr = FewShotManager()
    mock_llm = MockFewShotChatModel()

    generator = SQLGenerator(
        schema_manager=schema_mgr,
        few_shot_manager=few_shot_mgr,
        llm=mock_llm,
    )

    result = generator.generate_and_execute("En çok ciro yapan 5 çalışan")
    assert result["status"] == "success"
    assert result["error"] is None
    assert result["row_count"] > 0
    assert "EmployeeID" in result["columns"]
    assert "Revenue" in result["columns"]
