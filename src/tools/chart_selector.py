"""
Doğal Dil İşlemeli Akıllı Veri Analiz Asistanı - Otomatik Grafik Seçim Motoru (ChartSelector)
Dönen pandas.DataFrame sonuçlarını ve kullanıcının doğal dildeki sorusunu analiz ederek
en uygun görselleştirme türünü (line, bar, pie, scatter, table), eksenleri ve başlığı belirler.
"""

import re
from typing import Any, Dict, List, Optional, Tuple
import pandas as pd


class ChartSelector:
    """
    Veri kümesi yapısına ve analitik soru içeriğine göre grafik türünü belirleyen karar motoru.
    """

    # Pasta grafik için maksimum önerilen dilim sayısı
    MAX_PIE_CATEGORIES = 6

    # Pasta grafiği tetikleyen anahtar kelimeler
    PIE_KEYWORDS = {
        "oran", "orani", "oranı", "yuzde", "yüzde", "pay", "payi", "payı",
        "dagilim", "dağılım", "dağılımı", "pie", "share", "percentage",
        "proportion", "distribution", "hisse"
    }

    # Çizgi (Trend) grafiği tetikleyen anahtar kelimeler
    LINE_KEYWORDS = {
        "trend", "aylik", "aylık", "yillik", "yıllık", "gunluk", "günlük",
        "zaman", "zamana gore", "zamana göre", "degisim", "değişim",
        "gelisim", "gelişim", "evolution", "monthly", "yearly", "daily", "timeline"
    }

    # Dağılım (Scatter) grafiği tetikleyen anahtar kelimeler
    SCATTER_KEYWORDS = {
        "korelasyon", "iliski", "ilişki", "iliskisi", "ilişkisi",
        "dagilim", "dağılım", "scatter", "correlation", "versus", "vs", "karsilastir"
    }

    @classmethod
    def is_date_column(cls, series: pd.Series, col_name: str) -> bool:
        """Bir serinin tarih/zaman ekseni olup olmadığını tespit eder."""
        # 1. Doğrudan datetime türü
        if pd.api.types.is_datetime64_any_dtype(series):
            return True

        col_lower = col_name.lower().strip()
        date_name_patterns = [
            r"date", r"tarih", r"month", r"ay\b", r"year", r"yil", r"yıl",
            r"day", r"gun", r"gün", r"quarter", r"ceyrek", r"çeyrek",
            r"period", r"donem", r"dönem", r"time", r"zaman", r"orderdate", r"shippeddate"
        ]
        has_date_name = any(re.search(pat, col_lower) for pat in date_name_patterns)

        # 2. String/object içindeki tarihsel formatları kontrol et
        if pd.api.types.is_object_dtype(series) or pd.api.types.is_string_dtype(series):
            sample_values = series.dropna().astype(str).head(10).tolist()
            if not sample_values:
                return has_date_name

            # YYYY-MM-DD, YYYY-MM, YYYY, DD.MM.YYYY, DD/MM/YYYY regex kontrolleri
            date_regex = re.compile(
                r"^(?:\d{4}[-/]\d{2}(?:[-/]\d{2})?|\d{2}[-./]\d{2}[-./]\d{4}|\d{4}|(?:0[1-9]|1[0-2]))$"
            )
            matches = sum(1 for v in sample_values if date_regex.match(v.strip()))
            if matches >= len(sample_values) * 0.7:
                return True

        return has_date_name

    @classmethod
    def is_numeric_column(cls, series: pd.Series, col_name: str) -> bool:
        """Bir serinin sayısal bir metrik olup olmadığını tespit eder."""
        if not pd.api.types.is_numeric_dtype(series):
            return False

        if pd.api.types.is_bool_dtype(series):
            return False

        col_lower = col_name.lower().strip()

        # ID kolonları genellikle metrik değil kategoridir (örn. CustomerID, CategoryID)
        # Ancak COUNT(CustomerID) veya SUM gibi isimler metriktir
        is_aggregate_name = any(
            col_lower.startswith(prefix)
            for prefix in ("total", "sum", "count", "avg", "min", "max", "toplam", "adet", "ortalama", "ciro")
        )
        if is_aggregate_name:
            return True

        if col_lower.endswith("id") and not is_aggregate_name:
            # Sadece tekil ID değerleriyse metrik sayma
            return False

        return True

    @classmethod
    def is_categorical_column(cls, series: pd.Series, col_name: str) -> bool:
        """Bir serinin kategorik/boyut kolonu olup olmadığını tespit eder."""
        if cls.is_date_column(series, col_name):
            return False

        if pd.api.types.is_object_dtype(series) or pd.api.types.is_string_dtype(series) or isinstance(series.dtype, pd.CategoricalDtype):
            return True

        # Sayısal ID kolonları da kategorik boyut olarak kullanılabilir (CategoryID vb.)
        col_lower = col_name.lower().strip()
        if pd.api.types.is_numeric_dtype(series) and col_lower.endswith("id"):
            return True

        return False

    @classmethod
    def classify_columns(cls, df: pd.DataFrame) -> Tuple[List[str], List[str], List[str]]:
        """
        DataFrame kolonlarını Date, Numeric ve Categorical olarak ayrıştırır.

        Returns:
            (date_cols, numeric_cols, categorical_cols)
        """
        date_cols: List[str] = []
        numeric_cols: List[str] = []
        cat_cols: List[str] = []

        for col in df.columns:
            series = df[col]
            if cls.is_date_column(series, col):
                date_cols.append(col)
            elif cls.is_numeric_column(series, col):
                numeric_cols.append(col)
            elif cls.is_categorical_column(series, col):
                cat_cols.append(col)
            else:
                # Varsayılan olarak kategorik kabul et
                cat_cols.append(col)

        return date_cols, numeric_cols, cat_cols

    @classmethod
    def generate_chart_title(
        cls,
        question: str,
        chart_type: str,
        x_col: Optional[str] = None,
        y_col: Optional[str] = None,
    ) -> str:
        """Grafik için açıklayıcı bir başlık üretir."""
        if question and len(question.strip()) > 3:
            clean_q = question.strip().rstrip("?.!")
            # İlk harfi büyük yap
            return clean_q[0].upper() + clean_q[1:]

        if x_col and y_col:
            return f"{x_col} Bazında {y_col} Analizi"
        elif y_col:
            return f"{y_col} Dağılımı"
        return "Veri Analiz Grafiği"

    @classmethod
    def determine_chart_type(
        cls,
        df: Optional[pd.DataFrame],
        question: str = "",
    ) -> Dict[str, Any]:
        """
        DataFrame yapısını ve kullanıcı sorusunu analiz ederek en uygun grafik türünü belirler.

        Args:
            df: Analiz edilecek pandas DataFrame.
            question: Kullanıcının doğal dil sorusu.

        Returns:
            {
                "chart_type": "line" | "bar" | "pie" | "scatter" | "table",
                "x_col": str | None,
                "y_col": str | None,
                "title": str,
                "is_chartable": bool,
                "reason": str
            }
        """
        # 1. Boş veya Geçersiz DataFrame Kontrolü
        if df is None or df.empty or len(df.columns) == 0:
            return {
                "chart_type": "table",
                "x_col": None,
                "y_col": None,
                "title": "Veri Bulunamadı",
                "is_chartable": False,
                "reason": "Veri kümesi boş veya kolon içermiyor.",
            }

        # 2. Tek hücreli Skaler Çıktı (Örnek: SELECT COUNT(*) FROM Orders -> 830)
        if len(df) == 1 and len(df.columns) == 1:
            col_name = df.columns[0]
            val = df.iloc[0, 0]
            return {
                "chart_type": "table",
                "x_col": col_name,
                "y_col": None,
                "title": f"{col_name}: {val}",
                "is_chartable": False,
                "reason": "Tekil skaler değer döndü, tablo formatı daha uygun.",
            }

        date_cols, numeric_cols, cat_cols = cls.classify_columns(df)
        q_lower = question.lower() if question else ""

        # 3. Sayısal Metrik Yoksa -> Yalnızca Tablo
        if not numeric_cols:
            return {
                "chart_type": "table",
                "x_col": cat_cols[0] if cat_cols else df.columns[0],
                "y_col": None,
                "title": cls.generate_chart_title(question, "table"),
                "is_chartable": False,
                "reason": "Veri setinde sayısal metrik kolonu bulunmadığı için tablo olarak listelendi.",
            }

        # 4. KURAL: Zaman Serisi (Tarih Kolonu + Sayısal Kolon) -> LINE GRAFİK
        if date_cols:
            x_col = date_cols[0]
            y_col = numeric_cols[0]
            title = cls.generate_chart_title(question, "line", x_col, y_col)
            return {
                "chart_type": "line",
                "x_col": x_col,
                "y_col": y_col,
                "title": title,
                "is_chartable": True,
                "reason": f"Tarih/Zaman boyutu ({x_col}) ve sayısal metrik ({y_col}) tespit edildiği için çizgi grafik seçildi.",
            }

        # 5. KURAL: 2 Sayısal Kolon ve Korelasyon / Dağılım Sorusu -> SCATTER GRAFİK
        has_scatter_intent = any(kw in q_lower for kw in cls.SCATTER_KEYWORDS)
        if len(numeric_cols) >= 2 and (has_scatter_intent or len(cat_cols) == 0):
            x_col = numeric_cols[0]
            y_col = numeric_cols[1]
            title = cls.generate_chart_title(question, "scatter", x_col, y_col)
            return {
                "chart_type": "scatter",
                "x_col": x_col,
                "y_col": y_col,
                "title": title,
                "is_chartable": True,
                "reason": f"İki sayısal metrik ({x_col} ve {y_col}) arasındaki ilişki ve dağılım için dağılım grafiği seçildi.",
            }

        # 6. KURAL: 1 Kategorik + 1 Sayısal Kolon
        if cat_cols and numeric_cols:
            x_col = cat_cols[0]
            y_col = numeric_cols[0]
            n_categories = df[x_col].nunique()

            has_pie_intent = any(kw in q_lower for kw in cls.PIE_KEYWORDS)

            # Kategori sayısı azsa (<= 6) ve oran/dağılım belirtilmişse ya da 2-4 kategori varsa -> PIE
            if n_categories <= cls.MAX_PIE_CATEGORIES and (has_pie_intent or n_categories <= 4):
                title = cls.generate_chart_title(question, "pie", x_col, y_col)
                return {
                    "chart_type": "pie",
                    "x_col": x_col,
                    "y_col": y_col,
                    "title": title,
                    "is_chartable": True,
                    "reason": f"Düşük sayıda kategori ({n_categories}) ve oransal dağılım yapısı için pasta grafik seçildi.",
                }
            else:
                title = cls.generate_chart_title(question, "bar", x_col, y_col)
                return {
                    "chart_type": "bar",
                    "x_col": x_col,
                    "y_col": y_col,
                    "title": title,
                    "is_chartable": True,
                    "reason": f"Kategorik karşılaştırma ve sıralama için sütun/çubuk grafik ({x_col} vs {y_col}) seçildi.",
                }

        # 7. Varsayılan Fallback: Tablo
        return {
            "chart_type": "table",
            "x_col": df.columns[0],
            "y_col": numeric_cols[0] if numeric_cols else None,
            "title": cls.generate_chart_title(question, "table"),
            "is_chartable": False,
            "reason": "Standart grafik kalıplarına uymayan veri yapısı tablo olarak gösterildi.",
        }


def determine_chart_type(df: Optional[pd.DataFrame], question: str = "") -> Dict[str, Any]:
    """ChartSelector.determine_chart_type için kolay erişim fonksiyonu."""
    return ChartSelector.determine_chart_type(df=df, question=question)
