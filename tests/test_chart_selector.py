"""
Otomatik Grafik Seçim Motoru (ChartSelector) için birim testleri.
"""

import pandas as pd
import pytest

from src.tools.chart_selector import ChartSelector, determine_chart_type


# ---------------------------------------------------------------------------
# 1. Zaman Serisi (Line Chart) Testleri
# ---------------------------------------------------------------------------

def test_line_chart_for_time_series():
    """Aylık satış/trend verilerinde çizgi (line) grafiğin seçildiğini doğrular."""
    df = pd.DataFrame({
        "OrderMonth": ["1997-01", "1997-02", "1997-03", "1997-04", "1997-05", "1997-06"],
        "TotalRevenue": [15200.50, 18450.00, 22100.80, 19800.00, 25400.20, 28900.00],
    })
    decision = determine_chart_type(df, question="1997 yılındaki aylık satış cirosu trendi nedir?")

    assert decision["chart_type"] == "line"
    assert decision["x_col"] == "OrderMonth"
    assert decision["y_col"] == "TotalRevenue"
    assert decision["is_chartable"] is True
    assert "Çizgi" in decision["reason"] or "çizgi" in decision["reason"]


def test_line_chart_with_datetime_objects():
    """Tarih nesnesi (datetime64) içeren veri setinde line grafiğin seçildiğini doğrular."""
    df = pd.DataFrame({
        "OrderDate": pd.date_range("2016-01-01", periods=5, freq="ME"),
        "OrderCount": [45, 60, 52, 78, 90],
    })
    decision = determine_chart_type(df, question="Aylık sipariş sayıları")

    assert decision["chart_type"] == "line"
    assert decision["x_col"] == "OrderDate"
    assert decision["y_col"] == "OrderCount"
    assert decision["is_chartable"] is True


# ---------------------------------------------------------------------------
# 2. Kategorik Karşılaştırma & Sıralama (Bar Chart) Testleri
# ---------------------------------------------------------------------------

def test_bar_chart_for_categories():
    """Kategori bazlı ciro/satış verilerinde sütun/çubuk (bar) grafiğin seçildiğini doğrular."""
    df = pd.DataFrame({
        "CategoryName": [
            "Beverages", "Condiments", "Confections", "Dairy Products",
            "Grains/Cereals", "Meat/Poultry", "Produce", "Seafood"
        ],
        "TotalRevenue": [55000.0, 32000.0, 41000.0, 62000.0, 28000.0, 49000.0, 24000.0, 38000.0],
    })
    decision = determine_chart_type(df, question="Kategorilere göre toplam satış cirosu")

    assert decision["chart_type"] == "bar"
    assert decision["x_col"] == "CategoryName"
    assert decision["y_col"] == "TotalRevenue"
    assert decision["is_chartable"] is True


def test_bar_chart_for_top_ranked_items():
    """İlk N sıralama (Top 5 çalışan) verilerinde bar grafiğin seçildiğini doğrular."""
    df = pd.DataFrame({
        "EmployeeName": ["Margaret Peacock", "Janet Leverling", "Nancy Davolio", "Andrew Fuller", "Robert King"],
        "TotalOrders": [156, 127, 123, 96, 72],
    })
    decision = determine_chart_type(df, question="En çok sipariş alan ilk 5 çalışan kimdir?")

    assert decision["chart_type"] == "bar"
    assert decision["x_col"] == "EmployeeName"
    assert decision["y_col"] == "TotalOrders"
    assert decision["is_chartable"] is True


# ---------------------------------------------------------------------------
# 3. Oransal Dağılım (Pie Chart) Testleri
# ---------------------------------------------------------------------------

def test_pie_chart_for_small_proportions():
    """Az sayıda kategori ve oran/dağılım sorusunda pasta (pie) grafiğin seçildiğini doğrular."""
    df = pd.DataFrame({
        "ShipperName": ["Speedy Express", "United Package", "Federal Shipping"],
        "TotalFreight": [12400.0, 24500.0, 18900.0],
    })
    decision = determine_chart_type(
        df, question="Kargo şirketlerinin taşıdığı navlun dağılımı ve pazar payı oranı nedir?"
    )

    assert decision["chart_type"] == "pie"
    assert decision["x_col"] == "ShipperName"
    assert decision["y_col"] == "TotalFreight"
    assert decision["is_chartable"] is True


# ---------------------------------------------------------------------------
# 4. Korelasyon & Dağılım (Scatter Chart) Testleri
# ---------------------------------------------------------------------------

def test_scatter_chart_for_correlation():
    """İki sayısal metrik arasındaki ilişki/korelasyon sorularında scatter grafiğin seçildiğini doğrular."""
    df = pd.DataFrame({
        "UnitPrice": [10.0, 25.0, 50.0, 80.0, 120.0, 200.0],
        "UnitsInStock": [100, 85, 45, 20, 15, 5],
    })
    decision = determine_chart_type(
        df, question="Ürün birim fiyatı ile stok miktarları arasındaki ilişki ve korelasyon"
    )

    assert decision["chart_type"] == "scatter"
    assert decision["x_col"] == "UnitPrice"
    assert decision["y_col"] == "UnitsInStock"
    assert decision["is_chartable"] is True


# ---------------------------------------------------------------------------
# 5. Metinsel Listeleme ve Görselleştirilemeyen Çıktılar (Table) Testleri
# ---------------------------------------------------------------------------

def test_table_for_contact_list():
    """Sayısal metrik içermeyen metinsel müşteri iletişim listesi için tablo formatı seçildiğini doğrular."""
    df = pd.DataFrame({
        "CompanyName": ["Alfreds Futterkiste", "Ana Trujillo Emparedados", "Antonio Moreno Taquería"],
        "ContactName": ["Maria Anders", "Ana Trujillo", "Antonio Moreno"],
        "City": ["Berlin", "México D.F.", "México D.F."],
        "Phone": ["030-0074321", "(5) 555-4729", "(5) 555-3932"],
    })
    decision = determine_chart_type(df, question="Almanya ve Meksika'daki müşteri iletişim bilgileri")

    assert decision["chart_type"] == "table"
    assert decision["is_chartable"] is False
    assert "tablo" in decision["reason"].lower()


def test_table_for_empty_and_scalar_data():
    """Boş dataframe veya tekil skaler değerlerde tablo formatı seçildiğini doğrular."""
    # Boş DataFrame
    empty_df = pd.DataFrame()
    d_empty = determine_chart_type(empty_df, question="Hiçbir kayıt dönmeyen sorgu")
    assert d_empty["chart_type"] == "table"
    assert d_empty["is_chartable"] is False

    # Tekil Skaler Sonuç (Örnek: Toplam müşteri sayısı)
    scalar_df = pd.DataFrame({"TotalCustomers": [91]})
    d_scalar = determine_chart_type(scalar_df, question="Toplam müşteri sayısı kaçtır?")
    assert d_scalar["chart_type"] == "table"
    assert d_scalar["is_chartable"] is False
    assert "91" in d_scalar["title"]


# ---------------------------------------------------------------------------
# 6. Kolon Tipi Sınıflandırma Yardımcı Fonksiyon Testleri
# ---------------------------------------------------------------------------

def test_column_classification_helpers():
    """Kolon sınıflandırma (Date, Numeric, Categorical) fonksiyonlarının doğruluğunu test eder."""
    df = pd.DataFrame({
        "OrderDate": ["2016-07-04", "2016-07-05"],
        "CustomerID": ["ALFKI", "ANATR"],
        "Freight": [32.38, 11.61],
        "CategoryName": ["Beverages", "Condiments"],
    })

    dates, numerics, categoricals = ChartSelector.classify_columns(df)

    assert "OrderDate" in dates
    assert "Freight" in numerics
    assert "CategoryName" in categoricals
    assert "CustomerID" in categoricals
