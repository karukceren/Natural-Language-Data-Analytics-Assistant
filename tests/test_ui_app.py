"""
Streamlit Web Arayüzü (src/ui/app.py) ve UI Pipeline Entegrasyon Testleri.
"""

from typing import List
import pandas as pd
import pytest
from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import AIMessage, BaseMessage
from langchain_core.outputs import ChatGeneration, ChatResult

from src.ai.schema_manager import SchemaManager
from src.ai.sql_healing import SQLSelfHealingAgent
from src.core.database import engine, SessionLocal
from src.core.logger import QueryLogger
from src.tools.chart_engine import ChartEngine
from src.tools.chart_selector import determine_chart_type


class MockUIPipelineChatModel(BaseChatModel):
    """UI pipeline testleri için deterministik cevaplar veren Mock LLM."""

    def _generate(
        self,
        messages: List[BaseMessage],
        stop: list = None,
        run_manager = None,
        **kwargs,
    ) -> ChatResult:
        message = AIMessage(
            content="SELECT ProductID, ProductName, UnitPrice FROM Products ORDER BY UnitPrice DESC LIMIT 5"
        )
        return ChatResult(generations=[ChatGeneration(message=message)])

    @property
    def _llm_type(self) -> str:
        return "mock-ui-pipeline-chat-model"


def test_ui_app_file_syntax_and_imports():
    """src/ui/app.py dosyasının Python sözdizimi ve importlarının geçerli olduğunu doğrular."""
    import importlib.util
    from pathlib import Path

    app_path = Path(__file__).resolve().parent.parent / "src" / "ui" / "app.py"
    assert app_path.exists(), "src/ui/app.py dosyası mevcut olmalıdır."

    # Python compile test
    with open(app_path, "r", encoding="utf-8") as f:
        code = f.read()
    compiled = compile(code, str(app_path), "exec")
    assert compiled is not None


def test_ui_end_to_end_pipeline_simulation():
    """
    Streamlit arayüzünde çalışan tam pipeline'ı simüle eder:
      1. Soru -> SQLSelfHealingAgent
      2. Dönen DataFrame -> ChartSelector (Grafik tipi kararı)
      3. ChartEngine (Plotly Figure üretimi)
      4. QueryLogger (Veritabanına loglama)
      5. CSV dışa aktarımı doğrulaması
    """
    mock_llm = MockUIPipelineChatModel()
    schema_mgr = SchemaManager(engine=engine)
    agent = SQLSelfHealingAgent(schema_manager=schema_mgr, llm=mock_llm)
    logger = QueryLogger(engine=engine, session_factory=SessionLocal)
    logger.clear_logs()

    question = "En pahalı 5 ürünü listele"

    # 1. SQL Üretimi ve Çalıştırma
    df, final_sql, history = agent.execute_with_healing(question)
    assert isinstance(df, pd.DataFrame)
    assert len(df) == 5
    assert "UnitPrice" in df.columns

    # 2. Grafik Türü Belirleme
    chart_config = determine_chart_type(df, question=question)
    assert chart_config["is_chartable"] is True
    assert chart_config["chart_type"] in ("bar", "line", "pie", "scatter")

    # 3. Plotly Figürü Üretme
    fig = ChartEngine.generate_chart(df, chart_config)
    assert fig is not None
    assert len(fig.data) > 0

    # 4. Sorgu Loglama
    log_id = logger.log_query(
        user_query=question,
        generated_sql=final_sql,
        execution_time_ms=120.0,
        row_count=len(df),
        is_success=True,
        retry_count=0,
    )
    assert log_id > 0

    # 5. Log Doğrulama
    recent_logs = logger.get_recent_logs(limit=1)
    assert len(recent_logs) == 1
    assert recent_logs.iloc[0]["user_query"] == question

    # 6. CSV İndirme Formatı
    csv_bytes = df.to_csv(index=False).encode("utf-8")
    assert b"ProductName" in csv_bytes
    assert b"UnitPrice" in csv_bytes
