"""
Doğal Dil İşlemeli Akıllı Veri Analiz Asistanı - Dinamik Grafik Üretim Motoru (ChartEngine)
ChartSelector tarafından belirlenen grafik yapılandırması ve DataFrame verisini kullanarak
modern, şık ve etkileşimli Plotly figürleri (bar, line, pie/donut, scatter) oluşturur.
"""

from typing import Any, Dict, List, Optional
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go


# Kurumsal ve modern renk paleti
DEFAULT_COLOR_PALETTE: List[str] = [
    "#2563EB",  # Mavi (Primary)
    "#7C3AED",  # Mor
    "#059669",  # Zümrüt Yeşili
    "#D97706",  # Kehribar Sarısı
    "#DC2626",  # Kırmızı
    "#0891B2",  # Camgöbeği
    "#4F46E5",  # İndigo
    "#DB2777",  # Pembe
    "#65A30D",  # Açık Yeşil
    "#EA580C",  # Turuncu
]


class ChartEngine:
    """
    Plotly kütüphanesini kullanarak dinamik, duyarlı ve görsel açıdan zengin grafikler üreten motor.
    """

    COLOR_PALETTE = DEFAULT_COLOR_PALETTE

    @classmethod
    def generate_chart(
        cls,
        df: Optional[pd.DataFrame],
        chart_config: Optional[Dict[str, Any]],
    ) -> Optional[go.Figure]:
        """
        Veri çerçevesi ve konfigürasyona göre uygun Plotly grafiğini oluşturur.

        Args:
            df: Grafiğe dönüştürülecek veri (pandas DataFrame).
            chart_config: ChartSelector'dan gelen yapılandırma sözlüğü
                          {'chart_type', 'x_col', 'y_col', 'title', 'is_chartable'}.

        Returns:
            plotly.graph_objects.Figure nesnesi veya görselleştirme uygun değilse None.
        """
        # 1. Temel Geçerlilik ve Fallback Kontrolleri
        if df is None or df.empty or not chart_config:
            return None

        is_chartable = chart_config.get("is_chartable", True)
        chart_type = chart_config.get("chart_type", "table")

        if not is_chartable or chart_type == "table":
            return None

        x_col = chart_config.get("x_col")
        y_col = chart_config.get("y_col")
        title = chart_config.get("title", "Veri Analiz Grafiği")

        if not x_col or not y_col:
            return None

        if x_col not in df.columns or y_col not in df.columns:
            return None

        # 2. Eksik (NaN/None) Değerlerin Temizlenmesi
        clean_df = df.dropna(subset=[x_col, y_col]).copy()
        if clean_df.empty:
            return None

        # 3. Grafik Türüne Göre Plotly Figürü Üretimi
        try:
            if chart_type == "bar":
                fig = cls._create_bar_chart(clean_df, x_col, y_col, title)
            elif chart_type == "line":
                fig = cls._create_line_chart(clean_df, x_col, y_col, title)
            elif chart_type == "pie":
                fig = cls._create_pie_chart(clean_df, x_col, y_col, title)
            elif chart_type == "scatter":
                fig = cls._create_scatter_chart(clean_df, x_col, y_col, title)
            else:
                return None

            # 4. Genel Modern Tema ve Düzen Özelleştirmeleri
            cls._apply_modern_layout(fig, title, x_col, y_col, chart_type)
            return fig

        except Exception:
            return None

    @classmethod
    def _create_bar_chart(
        cls,
        df: pd.DataFrame,
        x_col: str,
        y_col: str,
        title: str,
    ) -> go.Figure:
        """Sütun / Çubuk Grafik Oluşturucu."""
        fig = px.bar(
            df,
            x=x_col,
            y=y_col,
            title=title,
            template="plotly_white",
            color_discrete_sequence=cls.COLOR_PALETTE,
            text_auto=".2s" if pd.api.types.is_numeric_dtype(df[y_col]) else False,
        )
        fig.update_traces(
            marker_line_width=0,
            opacity=0.9,
            textposition="outside",
            hovertemplate=f"<b>%{{x}}</b><br>{y_col}: %{{y:,.2f}}<extra></extra>",
        )
        return fig

    @classmethod
    def _create_line_chart(
        cls,
        df: pd.DataFrame,
        x_col: str,
        y_col: str,
        title: str,
    ) -> go.Figure:
        """Çizgi / Trend Grafik Oluşturucu."""
        # Zaman serisi için x eksenine göre sırala
        sorted_df = df.sort_values(by=x_col)
        fig = px.line(
            sorted_df,
            x=x_col,
            y=y_col,
            title=title,
            markers=True,
            template="plotly_white",
            color_discrete_sequence=cls.COLOR_PALETTE,
        )
        fig.update_traces(
            line=dict(width=3),
            marker=dict(size=8, symbol="circle"),
            hovertemplate=f"<b>%{{x}}</b><br>{y_col}: %{{y:,.2f}}<extra></extra>",
        )
        return fig

    @classmethod
    def _create_pie_chart(
        cls,
        df: pd.DataFrame,
        x_col: str,
        y_col: str,
        title: str,
    ) -> go.Figure:
        """Donut (Delikli Pasta) Grafik Oluşturucu."""
        fig = px.pie(
            df,
            names=x_col,
            values=y_col,
            title=title,
            hole=0.35,  # Modern Donut stili
            template="plotly_white",
            color_discrete_sequence=cls.COLOR_PALETTE,
        )
        fig.update_traces(
            textposition="inside",
            textinfo="percent+label",
            marker=dict(line=dict(color="#FFFFFF", width=2)),
            hovertemplate=f"<b>%{{label}}</b><br>{y_col}: %{{value:,.2f}} (%{{percent}})<extra></extra>",
        )
        return fig

    @classmethod
    def _create_scatter_chart(
        cls,
        df: pd.DataFrame,
        x_col: str,
        y_col: str,
        title: str,
    ) -> go.Figure:
        """Dağılım / Korelasyon Grafiği Oluşturucu."""
        fig = px.scatter(
            df,
            x=x_col,
            y=y_col,
            title=title,
            template="plotly_white",
            color_discrete_sequence=cls.COLOR_PALETTE,
        )
        fig.update_traces(
            marker=dict(size=10, opacity=0.8, line=dict(width=1, color="#FFFFFF")),
            hovertemplate=f"{x_col}: %{{x:,.2f}}<br>{y_col}: %{{y:,.2f}}<extra></extra>",
        )
        return fig

    @classmethod
    def _apply_modern_layout(
        cls,
        fig: go.Figure,
        title: str,
        x_col: str,
        y_col: str,
        chart_type: str,
    ) -> None:
        """Grafiğe modern tipografi, kenar boşlukları ve şık bir görünüm uygular."""
        fig.update_layout(
            title=dict(
                text=title,
                font=dict(size=16, family="Inter, Arial, sans-serif", color="#1E293B"),
                x=0.02,
                xanchor="left",
            ),
            font=dict(family="Inter, Arial, sans-serif", size=12, color="#475569"),
            margin=dict(l=40, r=40, t=60, b=40),
            hoverlabel=dict(
                bgcolor="#1E293B",
                font_size=12,
                font_family="Inter, Arial, sans-serif",
                font_color="#FFFFFF",
            ),
            plot_bgcolor="rgba(0,0,0,0)",
            paper_bgcolor="rgba(0,0,0,0)",
        )

        if chart_type in ("bar", "line", "scatter"):
            fig.update_xaxes(
                title_text=x_col,
                showgrid=True,
                gridcolor="#F1F5F9",
                zeroline=False,
                linecolor="#CBD5E1",
            )
            fig.update_yaxes(
                title_text=y_col,
                showgrid=True,
                gridcolor="#F1F5F9",
                zeroline=False,
                linecolor="#CBD5E1",
            )

    @classmethod
    def to_json(cls, fig: Optional[go.Figure]) -> Optional[str]:
        """Plotly figürünü web ve API entegrasyonu için JSON dizesine dönüştürür."""
        if fig is None:
            return None
        return fig.to_json()

    @classmethod
    def to_html(
        cls,
        fig: Optional[go.Figure],
        include_plotlyjs: bool = False,
        full_html: bool = False,
    ) -> Optional[str]:
        """Plotly figürünü HTML parçacığı olarak döndürür."""
        if fig is None:
            return None
        return fig.to_html(include_plotlyjs=include_plotlyjs, full_html=full_html)
