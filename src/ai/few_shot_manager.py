"""
Doğal Dil İşlemeli Akıllı Veri Analiz Asistanı - Few-Shot Prompting Yöneticisi (FewShotManager)
Northwind veritabanına özel, karmaşık JOIN'ler (4+ tablo), agregasyonlar, CTE'ler,
LEFT JOIN ve filtreleme içeren doğrulanmış örnek soru-SQL eşleşmelerini yönetir
ve LLM promptlarına dinamik olarak enjekte eder.
"""

from collections import defaultdict
import re
from typing import Any, Dict, List, Optional
from langchain_core.prompts import (
    ChatPromptTemplate,
    FewShotChatMessagePromptTemplate,
    PromptTemplate,
)


# ---------------------------------------------------------------------------
# Northwind Veritabanı Örnek Soru & SQL Eşleşmeleri Kütüphanesi
# ---------------------------------------------------------------------------
NORTHWIND_FEW_SHOT_EXAMPLES: List[Dict[str, Any]] = [
    {
        "question": "Geçen ay en çok satış ve ciro yapan 5 çalışan personel kimdir?",
        "sql": (
            "SELECT e.EmployeeID, e.FirstName || ' ' || e.LastName AS EmployeeName, "
            "ROUND(SUM(od.UnitPrice * od.Quantity * (1 - od.Discount)), 2) AS TotalSales "
            "FROM Employees e "
            "JOIN Orders o ON e.EmployeeID = o.EmployeeID "
            "JOIN \"Order Details\" od ON o.OrderID = od.OrderID "
            "WHERE strftime('%Y-%m', o.OrderDate) = (SELECT strftime('%Y-%m', MAX(OrderDate)) FROM Orders) "
            "GROUP BY e.EmployeeID, EmployeeName "
            "ORDER BY TotalSales DESC "
            "LIMIT 5"
        ),
        "description": "Veritabanındaki en son ay verisini baz alarak en çok ciro/satış yapan çalışan personelleri listeler.",
        "tables": ["Employees", "Orders", "Order Details"],
        "keywords": ["geçen", "ay", "son", "satış", "personel", "çalışan", "en çok", "ciro"],
    },
    {
        "question": "1997 yılında en çok ciro yapan ilk 5 çalışan kimdir?",
        "sql": (
            "SELECT e.EmployeeID, e.FirstName || ' ' || e.LastName AS EmployeeName, "
            "ROUND(SUM(od.UnitPrice * od.Quantity * (1 - od.Discount)), 2) AS TotalRevenue "
            "FROM Employees e "
            "JOIN Orders o ON e.EmployeeID = o.EmployeeID "
            "JOIN \"Order Details\" od ON o.OrderID = od.OrderID "
            "WHERE strftime('%Y', o.OrderDate) = '1997' "
            "GROUP BY e.EmployeeID, EmployeeName "
            "ORDER BY TotalRevenue DESC "
            "LIMIT 5"
        ),
        "description": "Çalışanların sipariş kalemleri üzerinden indirim uygulanmış toplam satış cirosunu (4 tablo JOIN) hesaplar.",
        "tables": ["Employees", "Orders", "Order Details"],
        "keywords": ["ciro", "çalışan", "personel", "satış", "1997", "gelir", "revenue", "employee"],
    },
    {
        "question": "Stok miktarı 10'un altına düşmüş ürünlerin tedarikçi şirket adları nelerdir?",
        "sql": (
            "SELECT p.ProductID, p.ProductName, p.UnitsInStock, s.SupplierID, s.CompanyName AS SupplierName "
            "FROM Products p "
            "JOIN Suppliers s ON p.SupplierID = s.SupplierID "
            "WHERE p.UnitsInStock < 10 "
            "ORDER BY p.UnitsInStock ASC"
        ),
        "description": "Kritik stok seviyesindeki ürünler ve tedarikçilerini JOIN ile listeler.",
        "tables": ["Products", "Suppliers"],
        "keywords": ["stok", "tedarikçi", "kritik", "ürün", "stock", "supplier", "product"],
    },
    {
        "question": "Hiç sipariş vermemiş müşterileri listele.",
        "sql": (
            "SELECT c.CustomerID, c.CompanyName, c.Country "
            "FROM Customers c "
            "LEFT JOIN Orders o ON c.CustomerID = o.CustomerID "
            "WHERE o.OrderID IS NULL "
            "ORDER BY c.CompanyName ASC"
        ),
        "description": "Siparişi bulunmayan pasif müşterileri LEFT JOIN ve IS NULL ile filtreler.",
        "tables": ["Customers", "Orders"],
        "keywords": ["sipariş vermemiş", "müşteri", "hiç", "pasif", "never ordered", "customer", "order"],
    },
    {
        "question": "Her kategorideki toplam ürün sayısını ve ortalama fiyatı getir.",
        "sql": (
            "SELECT c.CategoryID, c.CategoryName, COUNT(p.ProductID) AS TotalProducts, "
            "ROUND(AVG(p.UnitPrice), 2) AS AveragePrice "
            "FROM Categories c "
            "LEFT JOIN Products p ON c.CategoryID = p.CategoryID "
            "GROUP BY c.CategoryID, c.CategoryName "
            "ORDER BY TotalProducts DESC"
        ),
        "description": "Kategori bazında ürün sayısını ve ortalama birim fiyatı GROUP BY ile hesaplar.",
        "tables": ["Categories", "Products"],
        "keywords": ["kategori", "ortalama fiyat", "ürün sayısı", "adet", "category", "average price"],
    },
    {
        "question": "En çok satılan ilk 5 ürünün kategorisi ve toplam satış adedi nedir?",
        "sql": (
            "SELECT p.ProductID, p.ProductName, c.CategoryName, SUM(od.Quantity) AS TotalQuantitySold "
            "FROM Products p "
            "JOIN Categories c ON p.CategoryID = c.CategoryID "
            "JOIN \"Order Details\" od ON p.ProductID = od.ProductID "
            "GROUP BY p.ProductID, p.ProductName, c.CategoryName "
            "ORDER BY TotalQuantitySold DESC "
            "LIMIT 5"
        ),
        "description": "Ürün satış miktarlarını kategorileriyle birlikte 3'lü JOIN ile toplar.",
        "tables": ["Products", "Categories", "Order Details"],
        "keywords": ["en çok satan", "satış adedi", "kategori", "ürün", "top selling", "quantity"],
    },
    {
        "question": "Hangi kargo şirketi ile taşınan siparişlerin toplam navlun (freight) bedeli en yüksektir?",
        "sql": (
            "SELECT s.ShipperID, s.CompanyName AS ShipperName, COUNT(o.OrderID) AS TotalOrders, "
            "ROUND(SUM(o.Freight), 2) AS TotalFreight "
            "FROM Shippers s "
            "JOIN Orders o ON s.ShipperID = o.ShipVia "
            "GROUP BY s.ShipperID, ShipperName "
            "ORDER BY TotalFreight DESC"
        ),
        "description": "Kargo/nakliye firmalarının taşıdığı sipariş sayısı ve navlun toplamını hesaplar.",
        "tables": ["Shippers", "Orders"],
        "keywords": ["kargo", "nakliye", "navlun", "freight", "taşıma", "shipper"],
    },
    {
        "question": "Çalışanların bağlı olduğu yöneticilerin ad ve unvanları nelerdir?",
        "sql": (
            "SELECT e.EmployeeID, e.FirstName || ' ' || e.LastName AS EmployeeName, e.Title AS EmployeeTitle, "
            "m.EmployeeID AS ManagerID, m.FirstName || ' ' || m.LastName AS ManagerName, m.Title AS ManagerTitle "
            "FROM Employees e "
            "LEFT JOIN Employees m ON e.ReportsTo = m.EmployeeID "
            "ORDER BY e.EmployeeID ASC"
        ),
        "description": "Çalışan-yönetici hiyerarşisini Self-Join ile eşleştirir.",
        "tables": ["Employees"],
        "keywords": ["yönetici", "müdür", "amir", "çalışan", "unvan", "manager", "hierarchy", "reportsto"],
    },
    {
        "question": "1997 yılındaki aylık toplam sipariş adedi ve satış cirosu nedir?",
        "sql": (
            "SELECT strftime('%m', o.OrderDate) AS OrderMonth, COUNT(DISTINCT o.OrderID) AS TotalOrders, "
            "ROUND(SUM(od.UnitPrice * od.Quantity * (1 - od.Discount)), 2) AS MonthlyRevenue "
            "FROM Orders o "
            "JOIN \"Order Details\" od ON o.OrderID = od.OrderID "
            "WHERE strftime('%Y', o.OrderDate) = '1997' "
            "GROUP BY OrderMonth "
            "ORDER BY OrderMonth ASC"
        ),
        "description": "Tarih fonksiyonu (strftime) kullanarak aylık trend analizi yapar.",
        "tables": ["Orders", "Order Details"],
        "keywords": ["aylık", "ay", "trend", "1997", "ciro", "sipariş", "monthly", "trend"],
    },
]


def _turkish_lower(text: str) -> str:
    """Türkçe karakter uyumlu küçük harfe dönüştürücü."""
    if not text:
        return ""
    mapping = {"İ": "i", "I": "ı", "Ş": "ş", "Ğ": "ğ", "Ü": "ü", "Ö": "ö", "Ç": "ç"}
    for u, l in mapping.items():
        text = text.replace(u, l)
    return text.lower()


class FewShotManager:
    """
    Few-shot örnek soru-SQL kütüphanesini yöneten ve sorguya en uygun örnekleri
    seçip LangChain prompt şablonuna dönüştüren sınıf.
    """

    def __init__(self, examples: Optional[List[Dict[str, Any]]] = None):
        """
        FewShotManager yapılandırıcısı.

        Args:
            examples: Özel soru-SQL listesi (None ise NORTHWIND_FEW_SHOT_EXAMPLES kullanılır).
        """
        self.examples: List[Dict[str, Any]] = (
            examples if examples is not None else NORTHWIND_FEW_SHOT_EXAMPLES
        )

    def get_examples(
        self,
        query: Optional[str] = None,
        max_examples: Optional[int] = None,
    ) -> List[Dict[str, str]]:
        """
        Tanımlı örnek soru-SQL çiftlerini döndürür. Eğer 'query' verilirse,
        kullanıcı sorusundaki anahtar kelimelere göre en ilgili örnekleri sıralar.

        Args:
            query: Kullanıcı sorusu (alaka düzeyine göre sıralama için).
            max_examples: Döndürülecek maksimum örnek sayısı.

        Returns:
            [{"question": "...", "sql": "..."}, ...]
        """
        if not query or not query.strip():
            selected = self.examples[:max_examples] if max_examples else self.examples
            return [{"question": ex["question"], "sql": ex["sql"]} for ex in selected]

        query_norm = _turkish_lower(query)
        words = set(re.findall(r"\b\w+\b", query_norm))

        scored_examples: List[tuple[float, Dict[str, Any]]] = []

        for ex in self.examples:
            score = 0.0
            # 1. Soru metni benzerliği
            q_norm = _turkish_lower(ex["question"])
            if q_norm == query_norm:
                score += 50.0

            # 2. Anahtar kelimeler
            keywords = ex.get("keywords", [])
            for kw in keywords:
                kw_norm = _turkish_lower(kw)
                if kw_norm in words:
                    score += 10.0
                elif any(w.startswith(kw_norm) for w in words if len(kw_norm) >= 3):
                    score += 6.0
                elif kw_norm in query_norm and len(kw_norm) >= 4:
                    score += 4.0

            # 3. İlgili tablolar
            for table in ex.get("tables", []):
                t_norm = _turkish_lower(table)
                if t_norm in query_norm:
                    score += 5.0

            scored_examples.append((score, ex))

        # Puana göre azalan sırada sırala
        ranked = [ex for s, ex in sorted(scored_examples, key=lambda x: x[0], reverse=True)]

        if max_examples is not None and max_examples > 0:
            ranked = ranked[:max_examples]

        return [{"question": ex["question"], "sql": ex["sql"]} for ex in ranked]

    def format_examples_text(
        self,
        examples: Optional[List[Dict[str, str]]] = None,
        query: Optional[str] = None,
        max_examples: int = 4,
    ) -> str:
        """
        Örnekleri Markdown metin formatında döner (Prompt içine string olarak enjeksiyon için).
        """
        if examples is None:
            examples = self.get_examples(query=query, max_examples=max_examples)

        if not examples:
            return ""

        lines = ["### 💡 ÖRNEK SORU VE SQL EŞLEŞMELERİ (FEW-SHOT EXAMPLES):"]
        lines.append("Aşağıdaki örneklerdeki JOIN, agregasyon ve diyalekt kalıplarını referans alın:\n")

        for idx, ex in enumerate(examples, 1):
            lines.append(f"**Örnek {idx}:**")
            lines.append(f"❓ **Soru:** {ex['question']}")
            lines.append(f"```sql\n{ex['sql']}\n```\n")

        return "\n".join(lines).strip()

    def get_few_shot_prompt_template(
        self,
        examples: Optional[List[Dict[str, str]]] = None,
        query: Optional[str] = None,
        max_examples: int = 4,
    ) -> FewShotChatMessagePromptTemplate:
        """
        LangChain FewShotChatMessagePromptTemplate nesnesi üretir.
        """
        if examples is None:
            examples = self.get_examples(query=query, max_examples=max_examples)

        example_prompt = ChatPromptTemplate.from_messages(
            [
                ("human", "Kullanıcı Sorusu: {question}\nLütfen yalnızca yukarıdaki kurallara uygun SQL sorgusunu üret:"),
                ("ai", "{sql}"),
            ]
        )

        few_shot_prompt = FewShotChatMessagePromptTemplate(
            example_prompt=example_prompt,
            examples=examples,
        )

        return few_shot_prompt
