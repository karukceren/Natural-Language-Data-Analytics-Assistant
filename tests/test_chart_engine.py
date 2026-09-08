"""
Dinamik Grafik Üretim Motoru (ChartEngine) için birim testleri.
"""

import json
import pandas as pd
import plotly.graph_objects as go
import pytest

from src.tools.chart_engine import ChartEngine
from src.tools.chart_selector import determine_chart_type


# ---------------------------------------------------------------------------
# 1. Bar Chart (Sütun Grafik) Üretim Testi
# ---------------------------------------------------------------------------

def test_generate_bar_chart():
    """Bar grafiğinin doğru konfigürasyonla geçerli bir go.Figure ürettiğini test eder."""
    df = pd.DataFrame({
        "CategoryName": ["Beverages", "Condiments", "Confections"],
        "TotalRevenue": [12000.0, 8500.0, 9300.0],
    })
    config = {
        "chart_type": "bar",
        "x_col": "CategoryName",
        "y_col": "TotalRevenue",
        "title": "Kategori Bazlı Ciro",
        "is_chartable": True,
    }

    fig = ChartEngine.generate_chart(df, config)

    assert isinstance(fig, go.Figure)
    assert len(fig.data) == 1
    assert fig.data[0].type == "bar"
    assert fig.layout.title.text == "Kategori Bazlı Ciro"


# ---------------------------------------------------------------------------
# 2. Line Chart (Çizgi / Trend Grafik) Üretim Testi
# ---------------------------------------------------------------------------

def test_generate_line_chart():
    """Line grafiğinin marker'lar ve çizgiyle birlikte üretildiğini test eder."""
    df = pd.DataFrame({
        "OrderMonth": ["2016-01", "2016-02", "2016-03"],
        "OrderCount": [10, 25, 40],
    })
    config = {
        "chart_type": "line",
        "x_col": "OrderMonth",
        "y_col": "OrderCount",
        "title": "Aylık Sipariş Trendi",
        "is_chartable": True,
    }

    fig = ChartEngine.generate_chart(df, config)

    assert isinstance(fig, go.Figure)
    assert len(fig.data) == 1
    assert fig.data[0].type == "scatter"
    assert fig.data[0].mode == "lines+markers"
    assert fig.layout.title.text == "Aylık Sipariş Trendi"


# ---------------------------------------------------------------------------
# 3. Pie / Donut Chart (Pasta Grafik) Üretim Testi
# ---------------------------------------------------------------------------

def test_generate_pie_donut_chart():
    """Donut stili (hole > 0) pasta grafiğin üretildiğini test eder."""
    df = pd.DataFrame({
        "ShipperName": ["Speedy Express", "United Package", "Federal Shipping"],
        "TotalFreight": [1500.0, 3200.0, 2100.0],
    })
    config = {
        "chart_type": "pie",
        "x_col": "ShipperName",
        "y_col": "TotalFreight",
        "title": "Kargo Şirketleri Payı",
        "is_chartable": True,
    }

    fig = ChartEngine.generate_chart(df, config)

    assert isinstance(fig, go.Figure)
    assert len(fig.data) == 1
    assert fig.data[0].type == "pie"
    assert fig.data[0].hole == 0.35
    assert fig.layout.title.text == "Kargo Şirketleri Payı"


# ---------------------------------------------------------------------------
# 4. Scatter Chart (Dağılım Grafiği) Üretim Testi
# ---------------------------------------------------------------------------

def test_generate_scatter_chart():
    """Dağılım (scatter) grafiğinin üretildiğini test eder."""
    df = pd.DataFrame({
        "UnitPrice": [10.0, 20.0, 50.0, 100.0],
        "UnitsInStock": [150, 80, 45, 10],
    })
    config = {
        "chart_type": "scatter",
        "x_col": "UnitPrice",
        "y_col": "UnitsInStock",
        "title": "Fiyat ve Stok İlişkisi",
        "is_chartable": True,
    }

    fig = ChartEngine.generate_chart(df, config)

    assert isinstance(fig, go.Figure)
    assert len(fig.data) == 1
    assert fig.data[0].type == "scatter"
    assert fig.data[0].mode == "markers"


# ---------------------------------------------------------------------------
# 5. Fallback & Güvenli Dönüş (None) Testleri
# ---------------------------------------------------------------------------

def test_fallback_to_none_for_table():
    """chart_type == 'table' veya is_chartable == False olduğunda None döndüğünü test eder."""
    df = pd.DataFrame({"Name": ["Alice", "Bob"], "City": ["Berlin", "London"]})
    config = {
        "chart_type": "table",
        "x_col": "Name",
        "y_col": None,
        "title": "Müşteri Listesi",
        "is_chartable": False,
    }

    fig = ChartEngine.generate_chart(df, config)
    assert fig is None


def test_fallback_to_none_for_invalid_inputs():
    """Geçersiz, boş veya hatalı veri/konfigürasyonda None döndüğünü test eder."""
    valid_config = {
        "chart_type": "bar",
        "x_col": "CategoryName",
        "y_col": "TotalRevenue",
        "is_chartable": True,
    }

    # 1. Boş DataFrame
    assert ChartEngine.generate_chart(pd.DataFrame(), valid_config) is None

    # 2. None DataFrame
    assert ChartEngine.generate_chart(None, valid_config) is None

    # 3. None konfigürasyon
    df = pd.DataFrame({"A": [1, 2], "B": [3, 4]})
    assert ChartEngine.generate_chart(df, None) is None

    # 4. Kolon adı DataFrame içinde yoksa
    bad_col_config = {
        "chart_type": "bar",
        "x_col": "NonExistentX",
        "y_col": "NonExistentY",
        "is_chartable": True,
    }
    assert ChartEngine.generate_chart(df, bad_col_config) is None

    # 5. Tüm değerler NaN ise
    nan_df = pd.DataFrame({"A": [None, None], "B": [None, None]})
    nan_config = {"chart_type": "bar", "x_col": "A", "y_col": "B", "is_chartable": True}
    assert ChartEngine.generate_chart(nan_df, nan_config) is None


# ---------------------------------------------------------------------------
# 6. ChartSelector + ChartEngine Uçtan Uca Entegrasyon Testi
# ---------------------------------------------------------------------------

def test_end_to_end_selector_and_engine_integration():
    """ChartSelector çıktısının doğrudan ChartEngine tarafından sorunsuz işlendiğini doğrular."""
    df = pd.DataFrame({
        "OrderMonth": ["2016-07", "2016-08", "2016-09", "2016-10"],
        "TotalRevenue": [25000.0, 31000.0, 28000.0, 39000.0],
    })
    question = "2016 yılı aylık ciro trendi nedir?"
    config = determine_chart_type(df, question=question)

    assert config["is_chartable"] is True
    assert config["chart_type"] == "line"

    fig = ChartEngine.generate_chart(df, config)
    assert isinstance(fig, go.Figure)
    assert fig.data[0].type == "scatter"


# ---------------------------------------------------------------------------
# 7. JSON ve HTML Serileştirme Yardımcı Testleri
# ---------------------------------------------------------------------------

def test_serialization_helpers():
    """to_json ve to_html metotlarının geçerli string çıktı verdiğini doğrular."""
    df = pd.DataFrame({"A": ["X", "Y"], "B": [10, 20]})
    config = {"chart_type": "bar", "x_col": "A", "y_col": "B", "is_chartable": True}
    fig = ChartEngine.generate_chart(df, config)

    # JSON Serileştirme
    json_str = ChartEngine.to_json(fig)
    assert json_str is not None
    parsed = json.loads(json_str)
    assert "data" in parsed
    assert "layout" in parsed

    # HTML Serileştirme
    html_str = ChartEngine.to_html(fig)
    assert html_str is not None
    assert "<div" in html_str

    # None girişler için
    assert ChartEngine.to_json(None) is None
    assert ChartEngine.to_html(None) is None
