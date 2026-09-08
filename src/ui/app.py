"""
Doğal Dil İşlemeli Akıllı Veri Analiz Asistanı - Streamlit Web Kullanıcı Arayüzü (UI)
Text-to-SQL motoru, Self-Healing mekanizması, dinamik grafik görselleştirme (Plotly),
şema izleyici ve sorgu loglama yönetim panelini modern bir web arayüzünde sunar.
"""

import os
import sys
import time
from pathlib import Path
from typing import Any, Dict, Optional
import pandas as pd
import streamlit as st

# Proje kök dizinini sys.path'e ekle
PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.ai.schema_manager import SchemaManager
from src.ai.sql_generator import SQLGenerator
from src.ai.sql_healing import QueryExecutionError, SQLSelfHealingAgent
from src.core.config import settings
from src.core.database import engine, execute_read_only_query, test_connection
from src.core.logger import query_logger
from src.tools.chart_engine import ChartEngine
from src.tools.chart_selector import determine_chart_type
from src.ui.api_client import api_client


# ---------------------------------------------------------------------------
# 1. Sayfa Konfigürasyonu ve Özel CSS
# ---------------------------------------------------------------------------
st.set_page_config(
    page_title="Doğal Dil İşlemeli Akıllı Veri Analiz Asistanı",
    page_icon="🧠",
    layout="wide",
    initial_sidebar_state="expanded",
)

CUSTOM_CSS = """
<style>
    /* Ana Başlık ve Tipografi */
    @import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&display=swap');
    
    html, body, [class*="css"] {
        font-family: 'Inter', -apple-system, BlinkMacSystemFont, sans-serif;
    }
    
    /* Gradient Başlık Kartı */
    .hero-container {
        background: linear-gradient(135deg, #1E293B 0%, #0F172A 100%);
        border: 1px solid #334155;
        border-radius: 16px;
        padding: 24px 32px;
        margin-bottom: 24px;
        color: #FFFFFF;
        box-shadow: 0 10px 25px -5px rgba(0, 0, 0, 0.1);
    }
    
    .hero-title {
        font-size: 26px;
        font-weight: 700;
        margin-bottom: 6px;
        background: linear-gradient(90deg, #60A5FA, #A78BFA);
        -webkit-background-clip: text;
        -webkit-text-fill-color: transparent;
    }
    
    .hero-subtitle {
        font-size: 14px;
        color: #94A3B8;
        line-height: 1.5;
    }

    /* Metrik Kartları */
    .metric-card {
        background-color: #FFFFFF;
        border: 1px solid #E2E8F0;
        border-radius: 12px;
        padding: 16px 20px;
        box-shadow: 0 1px 3px rgba(0,0,0,0.05);
    }
    
    /* Hızlı Soru Butonları */
    .quick-btn {
        margin-bottom: 8px;
    }
    
    /* Sekme Başlıkları */
    .stTabs [data-baseweb="tab-list"] {
        gap: 12px;
    }
    
    .stTabs [data-baseweb="tab"] {
        font-weight: 600;
        padding: 10px 20px;
        border-radius: 8px;
    }
</style>
"""

st.markdown(CUSTOM_CSS, unsafe_allow_html=True)


# ---------------------------------------------------------------------------
# 2. Oturum Durumu (Session State) ve Servis Başlatıcılar
# ---------------------------------------------------------------------------
PROVIDER_OPTIONS = {
    "gemini": {"name": "♊ Google Gemini (Ücretsiz - Önerilen)", "default_model": "gemini-2.5-flash", "env_var": "GEMINI_API_KEY", "link": "https://aistudio.google.com/app/apikey"},
    "groq": {"name": "⚡ Groq (Llama 3.3 70B)", "default_model": "llama-3.3-70b-versatile", "env_var": "GROQ_API_KEY", "link": "https://console.groq.com/keys"},
    "openai": {"name": "🧠 OpenAI (GPT-4o)", "default_model": "gpt-4o", "env_var": "OPENAI_API_KEY", "link": "https://platform.openai.com/api-keys"},
    "anthropic": {"name": "🎭 Anthropic (Claude 3.5 Sonnet)", "default_model": "claude-3-5-sonnet-20241022", "env_var": "ANTHROPIC_API_KEY", "link": "https://console.anthropic.com/"},
    "ollama": {"name": "💻 Ollama (Yerel / Çevrimdışı)", "default_model": "llama3.1", "env_var": "", "link": "https://ollama.ai"},
}

def get_services(provider: str = "gemini", model_name: str = "gemini-2.5-flash"):
    """Servis örneklerini dinamik olarak başlatır ve oturumda önbelleğe alır."""
    if "schema_mgr" not in st.session_state:
        st.session_state.schema_mgr = SchemaManager(engine=engine)
    
    current_key = f"{provider}_{model_name}"
    if "agent" not in st.session_state or st.session_state.get("_cached_provider_key") != current_key:
        gen = SQLGenerator(
            schema_manager=st.session_state.schema_mgr,
            provider=provider,
            model_name=model_name,
        )
        st.session_state.agent = SQLSelfHealingAgent(
            sql_generator=gen,
            schema_manager=st.session_state.schema_mgr,
            max_retries=settings.MAX_RETRY_ATTEMPTS,
        )
        st.session_state._cached_provider_key = current_key

    if "chat_history" not in st.session_state:
        st.session_state.chat_history = []


# ---------------------------------------------------------------------------
# 3. Kenar Çubuğu (Sidebar)
# ---------------------------------------------------------------------------
with st.sidebar:
    st.image(
        "https://cdn-icons-png.flaticon.com/512/8649/8649595.png",
        width=64,
    )
    st.markdown("### 🤖 Model & Sağlayıcı")

    # Varsayılan sağlayıcı indeksi
    provider_keys = list(PROVIDER_OPTIONS.keys())
    default_provider = settings.DEFAULT_LLM_PROVIDER if settings.DEFAULT_LLM_PROVIDER in provider_keys else "openai"
    default_idx = provider_keys.index(default_provider)

    selected_provider_key = st.selectbox(
        "Sağlayıcı Seçin:",
        options=provider_keys,
        index=default_idx,
        format_func=lambda k: PROVIDER_OPTIONS[k]["name"],
        help="Tamamen ücretsiz kullanım için 'Groq' veya 'Google Gemini' seçebilirsiniz.",
    )

    prov_meta = PROVIDER_OPTIONS[selected_provider_key]
    model_name = prov_meta["default_model"]
    env_var_name = prov_meta["env_var"]
    key_link = prov_meta["link"]

    st.caption(f"📌 Varsayılan Model: `{model_name}`")

    # API Anahtarı Durumu & Girişi
    if env_var_name:
        current_api_key = os.environ.get(env_var_name, "")
        if not current_api_key and hasattr(settings, env_var_name):
            current_api_key = getattr(settings, env_var_name, "") or ""
        
        if current_api_key:
            masked = current_api_key[:6] + "..." + current_api_key[-4:] if len(current_api_key) > 10 else "******"
            st.success(f"🔑 API Key: `{masked}`")
        else:
            st.warning(f"⚠️ {selected_provider_key.upper()} API Key tanımlı değil!")
            st.markdown(f"👉 [Ücretsiz Key Al ({prov_meta['name'].split()[1]})]({key_link})")

        with st.expander(f"🔑 {selected_provider_key.upper()} Key Girişi", expanded=not bool(current_api_key)):
            user_key_input = st.text_input(
                f"{selected_provider_key.upper()} API Key:",
                value=current_api_key,
                type="password",
                placeholder="gsk_... veya AIza... veya sk-...",
                help=f"{selected_provider_key.upper()} API anahtarınızı girin.",
                key=f"input_key_{selected_provider_key}",
            )
            if user_key_input and user_key_input.strip() != current_api_key:
                val = user_key_input.strip()
                os.environ[env_var_name] = val
                try:
                    if hasattr(settings, env_var_name):
                        setattr(settings, env_var_name, val)
                except Exception:
                    pass
                if "agent" in st.session_state:
                    del st.session_state["agent"]
                st.success("API Anahtarı başarıyla güncellendi!")
                st.rerun()

    get_services(provider=selected_provider_key, model_name=model_name)
    schema_mgr = st.session_state.schema_mgr
    agent = st.session_state.agent

    st.markdown("---")
    st.markdown("### 🗄️ Veritabanı Durumu")

    conn_status = test_connection()
    if conn_status["status"] == "success":
        st.success(f"Bağlantı Aktif ({conn_status['table_count']} Tablo)")
    else:
        st.error("Bağlantı Hatası!")

    st.markdown("---")
    st.markdown("### 🌐 Backend İletişim Modu")
    is_api_online = api_client.is_available()
    if is_api_online:
        use_fastapi = st.toggle(
            "FastAPI Backend Kullan",
            value=True,
            help="Sorguları FastAPI REST API (http://localhost:8000/api/query) üzerinden çalıştırır.",
        )
        st.caption("🟢 FastAPI Aktif (Port 8000)")
    else:
        use_fastapi = False
        st.caption("🖥️ Yerel Servis Modu (Direct Python)")

    st.markdown("---")
    st.markdown("### 📊 Canlı İstatistikler")
    summary = query_logger.get_logs_summary()
    col_s1, col_s2 = st.columns(2)
    col_s1.metric("Toplam Sorgu", summary["total_queries"])
    col_s2.metric("Başarı Oranı", f"%{summary['success_rate_percent']}")
    st.caption(f"⏱️ Ort. Yanıt Süresi: {summary['avg_execution_time_ms']} ms")

    st.markdown("---")
    if st.button("🗑️ Sohbet Geçmişini Temizle", use_container_width=True):
        st.session_state.chat_history = []
        st.rerun()


# ---------------------------------------------------------------------------
# 4. Ana Başlık Alanı (Hero Banner)
# ---------------------------------------------------------------------------
st.markdown(
    """
    <div class="hero-container">
        <div class="hero-title">🧠 Doğal Dil İşlemeli Akıllı Veri Analiz Asistanı</div>
        <div class="hero-subtitle">
            Northwind veritabanına Türkçe veya İngilizce doğal dil soruları sorun. 
            Yapay zeka SQL sorgusunu üretsin, hata durumunda kendini düzeltsin ve otomatik grafiklerle görselleştirsin.
        </div>
    </div>
    """,
    unsafe_allow_html=True,
)


# ---------------------------------------------------------------------------
# 5. Ana Sekmeler (Tabs)
# ---------------------------------------------------------------------------
tab_query, tab_schema_logs = st.tabs(
    ["💬 Sorgu & Analiz Paneli", "🗄️ Şema İzleyici & 📋 Sorgu Logları"]
)


# ===========================================================================
# TAB 1: SORGU & ANALİZ PANELİ
# ===========================================================================
with tab_query:
    st.markdown("#### ⚡ Hızlı Örnek Sorular")
    sample_queries = [
        "En pahalı 5 ürünü fiyatıyla birlikte listele.",
        "1997 yılında en çok ciro yapan ilk 5 çalışan kimdir?",
        "1997 yılındaki aylık toplam sipariş adedi ve satış cirosu nedir?",
        "Kargo şirketlerinin taşıdığı toplam navlun bedeli dağılımı nedir?",
        "Stok miktarı 10'un altına düşmüş ürünlerin tedarikçi şirket adları nelerdir?",
        "Hiç sipariş vermemiş müşterileri listele.",
    ]

    cols = st.columns(3)
    selected_sample = None
    for idx, sq in enumerate(sample_queries):
        if cols[idx % 3].button(f"💡 {sq}", key=f"sq_{idx}", use_container_width=True):
            selected_sample = sq

    st.markdown("---")

    # Önceki Sohbet Geçmişini Ekrana Bas
    for message in st.session_state.chat_history:
        with st.chat_message(message["role"]):
            if message["role"] == "user":
                st.write(message["content"])
            else:
                data = message.get("data", {})
                sql = data.get("sql")
                df = data.get("df")
                fig = data.get("fig")
                repair_history = data.get("repair_history", [])
                exec_time = data.get("exec_time", 0.0)
                chart_type = data.get("chart_type", "table")
                summary_text = data.get("summary", "")

                if repair_history and len(repair_history) > 2:
                    with st.expander("🛠️ Self-Healing Tamir Adımları", expanded=False):
                        for step in repair_history:
                            st.caption(step)

                if sql:
                    st.code(sql, language="sql")

                m_col1, m_col2, m_col3 = st.columns(3)
                m_col1.metric("Dönen Kayıt", f"{len(df) if df is not None else 0} satır")
                m_col2.metric("Çalışma Süresi", f"{exec_time:.1f} ms")
                m_col3.metric("Görselleştirme", chart_type.upper())

                if fig is not None:
                    st.plotly_chart(fig, use_container_width=True)

                if df is not None and not df.empty:
                    st.dataframe(df, use_container_width=True)
                    csv_data = df.to_csv(index=False).encode("utf-8")
                    st.download_button(
                        label="📥 CSV Olarak İndir",
                        data=csv_data,
                        file_name="analiz_sonucu.csv",
                        mime="text/csv",
                        key=f"dl_{message.get('id', time.time())}",
                    )

                if summary_text:
                    st.info(summary_text)

    # Yeni Soru Girişi
    user_input = st.chat_input(
        "Veritabanına bir soru sorun (örn: En çok satan ilk 5 ürünün kategorisi ve satış adedi)..."
    )

    query_to_run = selected_sample or user_input

    if query_to_run:
        # Kullanıcı mesajını kaydet ve ekrana yazdır
        st.session_state.chat_history.append({"role": "user", "content": query_to_run})
        with st.chat_message("user"):
            st.write(query_to_run)

        # Asistan yanıtını üret
        with st.chat_message("assistant"):
            with st.spinner("🧠 Yapay zeka sorguyu analiz ediyor, SQL üretiyor ve çalıştırıyor..."):
                start_time = time.perf_counter()
                try:
                    if use_fastapi:
                        # 1. FastAPI REST API üzerinden çalıştır
                        active_key = current_api_key if env_var_name else None
                        api_res = api_client.run_query(
                            question=query_to_run,
                            provider=selected_provider_key,
                            model_name=model_name,
                            api_key=active_key,
                        )
                        if not api_res.get("is_success", True):
                            raise QueryExecutionError(
                                message=api_res.get("error_message") or "Sorgu çalıştırılamadı.",
                                last_sql=api_res.get("sql", ""),
                                attempts=api_res.get("repair_history", []),
                            )

                        final_sql = api_res.get("sql", "")
                        data_records = api_res.get("data", [])
                        cols = api_res.get("columns", [])
                        if data_records:
                            df = pd.DataFrame(data_records)
                        elif cols:
                            df = pd.DataFrame(columns=cols)
                        else:
                            df = pd.DataFrame()

                        chart_config = api_res.get("chart_config", {})
                        fig = ChartEngine.generate_chart(df, chart_config) if not df.empty else None
                        chart_type = chart_config.get("chart_type", "table")
                        history = api_res.get("repair_history", [])
                        exec_time_ms = float(api_res.get("execution_time_ms", 0.0))
                        summary_text = api_res.get("summary", "")
                    else:
                        # 2. Doğrudan Yerel Python Servisleri ile çalıştır
                        df, final_sql, history = agent.execute_with_healing(query_to_run)
                        exec_time_ms = (time.perf_counter() - start_time) * 1000

                        # Grafik türünü belirle ve figür üret
                        chart_config = determine_chart_type(df, question=query_to_run)
                        fig = ChartEngine.generate_chart(df, chart_config)
                        chart_type = chart_config.get("chart_type", "table")

                        # Log kaydı oluştur
                        query_logger.log_query(
                            user_query=query_to_run,
                            generated_sql=final_sql,
                            execution_time_ms=exec_time_ms,
                            row_count=len(df),
                            is_success=True,
                            retry_count=max(0, len(history) - 2),
                        )

                        # Otomatik Veri Özeti Metni
                        summary_text = (
                            f"✅ Sorgu başarıyla tamamlandı. Toplam **{len(df)}** kayıt listelendi. "
                            f"Veri yapısına uygun olarak **{chart_type.upper()}** görselleştirmesi seçildi."
                        )

                    # Arayüz Çıktıları
                    if history and len(history) > 2:
                        st.warning("⚠️ Sorgu veritabanı hatası aldı ve Self-Healing ile otomatik düzeltilerek çalıştırıldı!")
                        with st.expander("🛠️ Self-Healing Tamir Geçmişi", expanded=True):
                            for step in history:
                                st.write(f"- {step}")

                    st.markdown("##### 💻 Üretilen SQL:")
                    st.code(final_sql, language="sql")

                    m_col1, m_col2, m_col3 = st.columns(3)
                    m_col1.metric("Dönen Kayıt", f"{len(df)} satır")
                    m_col2.metric("Çalışma Süresi", f"{exec_time_ms:.1f} ms")
                    m_col3.metric("Görselleştirme", chart_type.upper())

                    if fig is not None:
                        st.plotly_chart(fig, use_container_width=True)

                    if not df.empty:
                        st.markdown("##### 📋 Veri Tablosu:")
                        st.dataframe(df, use_container_width=True)

                        csv_data = df.to_csv(index=False).encode("utf-8")
                        st.download_button(
                            label="📥 CSV Olarak İndir",
                            data=csv_data,
                            file_name="analiz_sonucu.csv",
                            mime="text/csv",
                        )

                    st.info(summary_text)

                    # Sohbet geçmişine kaydet
                    st.session_state.chat_history.append(
                        {
                            "role": "assistant",
                            "id": time.time(),
                            "content": f"SQL: {final_sql}",
                            "data": {
                                "sql": final_sql,
                                "df": df,
                                "fig": fig,
                                "repair_history": history,
                                "exec_time": exec_time_ms,
                                "chart_type": chart_type,
                                "summary": summary_text,
                            },
                        }
                    )

                except QueryExecutionError as q_err:
                    exec_time_ms = (time.perf_counter() - start_time) * 1000
                    st.error(f"❌ **Sorgu Çalıştırılamadı:** {q_err.message}")

                    if q_err.attempts:
                        with st.expander("🛠️ Yapılan Tamir Denemeleri", expanded=True):
                            for att in q_err.attempts:
                                st.write(f"- {att}")

                    if not use_fastapi:
                        # Başarısız log kaydı
                        query_logger.log_query(
                            user_query=query_to_run,
                            generated_sql=q_err.last_sql,
                            execution_time_ms=exec_time_ms,
                            row_count=0,
                            is_success=False,
                            error_message=q_err.message,
                            retry_count=settings.MAX_RETRY_ATTEMPTS,
                        )

                except Exception as exc:
                    exec_time_ms = (time.perf_counter() - start_time) * 1000
                    err_msg = str(exc)
                    st.error(f"❌ **Hata Oluştu:** {err_msg}")

                    if not use_fastapi:
                        query_logger.log_query(
                            user_query=query_to_run,
                            generated_sql=None,
                            execution_time_ms=exec_time_ms,
                            row_count=0,
                            is_success=False,
                            error_message=err_msg,
                        )


# ===========================================================================
# TAB 2: ŞEMA İZLEYİCİ & SOGU LOGLARI
# ===========================================================================
with tab_schema_logs:
    schema_tab, logs_tab = st.tabs(["🗄️ Veritabanı Şeması", "📋 Sorgu Logları & Analitik İzleme"])

    # 1. ŞEMA İZLEYİCİ
    with schema_tab:
        st.markdown("### 🗄️ Northwind Veritabanı Şema Tanımları")
        st.caption("Aşağıda veritabanındaki 13 tablonun kolonları, veri tipleri, PK ve FK ilişkileri listelenmektedir.")

        all_tables = schema_mgr.get_table_names()
        table_search = st.text_input("🔍 Tablo Ara...", placeholder="Örn: Products, Orders, Customers...")

        filtered_tables = (
            [t for t in all_tables if table_search.lower() in t.lower()]
            if table_search
            else all_tables
        )

        for tbl in filtered_tables:
            with st.expander(f"📦 **{tbl}** Tablosu", expanded=False):
                ddl = schema_mgr.generate_ddl(tbl)
                st.code(ddl, language="sql")

                # Örnek 3 satır veri önizlemesi
                try:
                    preview_df = execute_read_only_query(
                        f'SELECT * FROM "{tbl}" LIMIT 3'
                    )
                    if preview_df["rows"]:
                        st.caption("Örnek 3 Satır Veri:")
                        st.dataframe(pd.DataFrame(preview_df["rows"]), use_container_width=True)
                except Exception:
                    pass

    # 2. LOGLAR VE ANALİTİK İZLEME
    with logs_tab:
        st.markdown("### 📋 Sorgu Logları ve Sistem Metrikleri")

        # Metrik Kartları
        current_summary = query_logger.get_logs_summary()
        c1, c2, c3, c4, c5 = st.columns(5)
        c1.metric("Toplam Sorgu", current_summary["total_queries"])
        c2.metric("Başarılı", current_summary["successful_queries"])
        c3.metric("Başarısız", current_summary["failed_queries"])
        c4.metric("Başarı Oranı", f"%{current_summary['success_rate_percent']}")
        c5.metric("Ort. Yanıt Süresi", f"{current_summary['avg_execution_time_ms']} ms")

        st.markdown("---")

        col_l1, col_l2 = st.columns([4, 1])
        with col_l1:
            st.markdown("#### 📜 Son 50 Sorgu Kaydı")
        with col_l2:
            if st.button("🗑️ Logları Temizle", use_container_width=True):
                query_logger.clear_logs()
                st.success("Tüm log kayıtları temizlendi.")
                st.rerun()

        logs_df = query_logger.get_recent_logs(limit=50)

        if not logs_df.empty:
            st.dataframe(
                logs_df,
                use_container_width=True,
                column_config={
                    "is_success": st.column_config.CheckboxColumn("Başarılı mı?"),
                    "execution_time_ms": st.column_config.NumberColumn("Süre (ms)", format="%.1f ms"),
                    "timestamp": st.column_config.DatetimeColumn("Tarih / Saat"),
                },
            )
        else:
            st.info("Henüz kaydedilmiş bir sorgu logu bulunmuyor.")


# ---------------------------------------------------------------------------
# Footer
# ---------------------------------------------------------------------------
st.markdown("---")
st.caption("🚀 Doğal Dil İşlemeli Akıllı Veri Analiz Asistanı | LangChain, SQLAlchemy, Plotly ve Streamlit ile geliştirilmiştir.")
