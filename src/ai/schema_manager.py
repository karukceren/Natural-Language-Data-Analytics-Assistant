"""
Doğal Dil İşlemeli Akıllı Veri Analiz Asistanı - Şema ve Metadata Yöneticisi (SchemaManager)
Veritabanı tablolarını, kolon tiplerini, Primary Key ve Foreign Key ilişkilerini
dinamik olarak analiz eder, LLM için optimize edilmiş DDL/şema metinleri üretir
ve kullanıcı sorularına göre ilgili tabloları (Table Pruning) filtreler.
"""

from collections import defaultdict, deque
import re
from typing import Any, Dict, List, Optional, Set, Tuple
from sqlalchemy import Engine, inspect, text
from sqlalchemy.engine import Inspector

from src.core.database import engine as default_engine


# ---------------------------------------------------------------------------
# Northwind Veritabanı Tablo & Kolon Metadata Sözlüğü
# ---------------------------------------------------------------------------
NORTHWIND_METADATA: Dict[str, Dict[str, Any]] = {
    "Customers": {
        "description": "Müşteri firma bilgileri, irtibat kişileri, unvanları ve iletişim/adres bilgileri.",
        "english_description": "Customer company details, contact person, title, city, and address info.",
        "key_columns": {
            "CustomerID": "Benzersiz 5 karakterli müşteri kodu (Primary Key)",
            "CompanyName": "Müşteri şirket/firma adı",
            "ContactName": "İletişim kurulacak yetkili kişi adı",
            "City": "Müşterinin bulunduğu şehir",
            "Country": "Müşterinin bulunduğu ülke",
        },
        "keywords": [
            "müşteri", "musteri", "şirket", "sirket", "firma", "müşteriler", "musteriler",
            "customer", "customers", "client", "buyer", "alıcı", "alici", "contact",
        ],
    },
    "Orders": {
        "description": "Müşterilere ait verilen ana sipariş bilgileri, sipariş/sevk tarihleri, kargo firması ve teslimat adresi.",
        "english_description": "Header order records, order/required/shipped dates, shipping fee, carrier, and destination.",
        "key_columns": {
            "OrderID": "Benzersiz sipariş numarası (Primary Key)",
            "CustomerID": "Siparişi veren müşterinin ID'si (Foreign Key -> Customers.CustomerID)",
            "EmployeeID": "Siparişi alan/oluşturan çalışanın ID'si (Foreign Key -> Employees.EmployeeID)",
            "OrderDate": "Sipariş verilme tarihi",
            "RequiredDate": "İstenen teslimat tarihi",
            "ShippedDate": "Fiili kargoya veriliş/sevk tarihi",
            "ShipVia": "Kargo/nakliye firması ID'si (Foreign Key -> Shippers.ShipperID)",
            "Freight": "Kargo/nakliye taşıma ücreti",
            "ShipCountry": "Teslimatın yapıldığı hedef ülke",
            "ShipCity": "Teslimatın yapıldığı hedef şehir",
        },
        "keywords": [
            "sipariş", "siparis", "siparişler", "siparisler", "satış", "satis", "satışlar", "satislar",
            "order", "orders", "sale", "sales", "sevk", "teslimat", "tarih", "freight", "kargo bedeli",
        ],
    },
    "Order Details": {
        "alias": "OrderDetails",
        "description": "Sipariş kalemleri/satırları; hangi siparişte hangi ürünün kaç adet, hangi birim fiyattan ve ne kadar indirimle satıldığı.",
        "english_description": "Line items for each order: ProductID, UnitPrice, Quantity, and Discount.",
        "key_columns": {
            "OrderID": "Sipariş ID (Primary Key, Foreign Key -> Orders.OrderID)",
            "ProductID": "Satılan ürün ID (Primary Key, Foreign Key -> Products.ProductID)",
            "UnitPrice": "Satış anındaki ürün birim fiyatı",
            "Quantity": "Sipariş edilen adet / miktar",
            "Discount": "Uygulanan indirim oranı (0.0 ile 1.0 arası reel sayı)",
        },
        "keywords": [
            "sipariş detayı", "siparis detayi", "sipariş kalemi", "siparis kalemi", "ürün adedi",
            "miktar", "adet", "adetler", "indirim", "iskonto", "ciro", "toplam tutar", "kazanç",
            "gelir", "hasılat", "quantity", "unitprice", "discount", "order details", "orderdetails", "revenue",
        ],
    },
    "Products": {
        "description": "Şirketin sattığı ürünler, birim satış fiyatları, mevcut stok miktarları, siparişteki miktarlar ve ürün kategorileri.",
        "english_description": "Product catalog, unit price, stock on hand, units on order, and category/supplier references.",
        "key_columns": {
            "ProductID": "Benzersiz ürün ID (Primary Key)",
            "ProductName": "Ürünün ticari adı",
            "SupplierID": "Tedarikçi firma ID (Foreign Key -> Suppliers.SupplierID)",
            "CategoryID": "Kategori ID (Foreign Key -> Categories.CategoryID)",
            "QuantityPerUnit": "Paket/kutu başına birim miktarı",
            "UnitPrice": "Güncel liste satış fiyatı",
            "UnitsInStock": "Mevcut depodaki stok miktarı",
            "UnitsOnOrder": "Tedarikçiden sipariş edilmiş bekleyen miktar",
            "ReorderLevel": "Yeniden sipariş verme eşik seviyesi",
            "Discontinued": "Ürünün satıştan kalkıp kalkmadığı ('1' veya '0')",
        },
        "keywords": [
            "ürün", "urun", "ürünler", "urunler", "stok", "stoklar", "fiyat", "birim fiyat",
            "ürün adı", "urun adi", "product", "products", "inventory", "price", "stock", "katalog",
        ],
    },
    "Employees": {
        "description": "Şirket personeli ve çalışanlar; ad, soyad, unvan, işe giriş tarihi, bağlı olduğu amir/yönetici ve iletişim bilgileri.",
        "english_description": "Company employees, titles, hire dates, manager hierarchies (ReportsTo), and contact info.",
        "key_columns": {
            "EmployeeID": "Benzersiz çalışan ID (Primary Key)",
            "LastName": "Çalışanın soyadı",
            "FirstName": "Çalışanın adı",
            "Title": "Görevi / İş unvanı (ör. Sales Representative)",
            "BirthDate": "Doğum tarihi",
            "HireDate": "İşe başlangıç tarihi",
            "ReportsTo": "Bağlı olduğu yöneticinin EmployeeID'si (Self-referencing Foreign Key -> Employees.EmployeeID)",
        },
        "keywords": [
            "çalışan", "calisan", "çalışanlar", "calisanlar", "personel", "eleman", "temsilci",
            "satış temsilcisi", "satis temsilcisi", "müdür", "mudur", "yönetici", "yonetici", "amir",
            "employee", "employees", "staff", "manager", "salesperson", "worker",
        ],
    },
    "Categories": {
        "description": "Ürünlerin ait olduğu ana kategoriler (İçecekler, Baharatlar, Süt Ürünleri, Deniz Ürünleri vb.) ve açıklamaları.",
        "english_description": "Product categories (Beverages, Condiments, Dairy, etc.) and category descriptions.",
        "key_columns": {
            "CategoryID": "Benzersiz kategori ID (Primary Key)",
            "CategoryName": "Kategori adı (ör. Beverages, Confections, Seafood)",
            "Description": "Kategoriye dair açıklama",
        },
        "keywords": [
            "kategori", "kategoriler", "kategoride", "kategori adı", "tür", "çeşit", "grup",
            "category", "categories", "categoryname", "beverages", "condiments", "seafood",
        ],
    },
    "Suppliers": {
        "description": "Ürünleri tedarik eden toptancı ve üretici firmalar, irtibat kişileri ve adresleri.",
        "english_description": "Suppliers and vendors supplying products, contact details, and locations.",
        "key_columns": {
            "SupplierID": "Benzersiz tedarikçi ID (Primary Key)",
            "CompanyName": "Tedarikçi firma adı",
            "ContactName": "Yetkili kişi adı",
            "City": "Tedarikçi şehri",
            "Country": "Tedarikçi ülkesi",
        },
        "keywords": [
            "tedarikçi", "tedarikci", "tedarikçiler", "tedarikciler", "üretici", "uretici", "toptancı",
            "supplier", "suppliers", "vendor", "vendors", "provider",
        ],
    },
    "Shippers": {
        "description": "Siparişleri müşterilere taşıyan kargo, nakliye ve lojistik şirketleri (ör. Speedy Express, United Package, Federal Shipping).",
        "english_description": "Shipping/carrier companies that transport orders to customers.",
        "key_columns": {
            "ShipperID": "Benzersiz kargo firması ID (Primary Key)",
            "CompanyName": "Kargo/nakliye firması adı",
            "Phone": "Telefon numarası",
        },
        "keywords": [
            "kargo", "kargocu", "kargo şirketi", "nakliye", "nakliyeci", "taşımacılık", "lojistik", "ulaştırma",
            "shipper", "shippers", "carrier", "shipping company", "freight forwarder",
        ],
    },
    "Regions": {
        "description": "Satış ve operasyon coğrafi bölgeleri (ör. Eastern, Western, Northern, Southern).",
        "english_description": "Geographical region definitions.",
        "key_columns": {
            "RegionID": "Bölge ID (Primary Key)",
            "RegionDescription": "Bölge adı/açıklaması",
        },
        "keywords": [
            "bölge", "bolge", "coğrafi bölge", "cografi bolge", "region", "regions",
        ],
    },
    "Territories": {
        "description": "Bölgelerin altındaki yerel satış sahaları / mikro bölgeler ve bağlı oldukları RegionID.",
        "english_description": "Sales territories linked to regions.",
        "key_columns": {
            "TerritoryID": "Saha/Mikro bölge kodu (Primary Key)",
            "TerritoryDescription": "Saha adı (ör. Boston, Chicago)",
            "RegionID": "Bağlı olduğu ana bölge (Foreign Key -> Regions.RegionID)",
        },
        "keywords": [
            "saha", "bölge sahası", "territory", "territories", "alt bölge",
        ],
    },
    "EmployeeTerritories": {
        "description": "Çalışanların sorumlu olduğu satış sahaları eşleşmesi (Employees ve Territories tabloları arası çoktan-çoğa köprü tablosu).",
        "english_description": "Many-to-many junction table mapping Employees to Territories.",
        "key_columns": {
            "EmployeeID": "Çalışan ID (Foreign Key -> Employees.EmployeeID)",
            "TerritoryID": "Saha ID (Foreign Key -> Territories.TerritoryID)",
        },
        "keywords": [
            "çalışan bölgesi", "personel sahası", "employee territories", "employeeterritories",
        ],
    },
    "CustomerDemographics": {
        "description": "Müşteri demografik grup tanımları.",
        "english_description": "Customer demographic type descriptions.",
        "key_columns": {
            "CustomerTypeID": "Demografik tip kodu (Primary Key)",
            "CustomerDesc": "Demografik grup açıklaması",
        },
        "keywords": [
            "demografi", "demografik", "customer demographics",
        ],
    },
    "CustomerCustomerDemo": {
        "description": "Müşteriler ile demografik tipler arasındaki çoktan-çoğa ilişki tablosu.",
        "english_description": "Many-to-many junction table linking Customers with Demographics.",
        "key_columns": {
            "CustomerID": "Müşteri ID (Foreign Key -> Customers.CustomerID)",
            "CustomerTypeID": "Demografik Tip ID (Foreign Key -> CustomerDemographics.CustomerTypeID)",
        },
        "keywords": [
            "müşteri demografi", "customercustomerdemo",
        ],
    },
}


def _turkish_lower(text_to_convert: str) -> str:
    """
    Türkçe karakterleri güvenli ve doğru biçimde küçük harfe dönüştürür.
    (İ -> i, I -> ı vb.)
    """
    if not text_to_convert:
        return ""
    mapping = {
        "İ": "i", "I": "ı", "Ş": "ş", "Ğ": "ğ", "Ü": "ü", "Ö": "ö", "Ç": "ç"
    }
    for upper_char, lower_char in mapping.items():
        text_to_convert = text_to_convert.replace(upper_char, lower_char)
    return text_to_convert.lower()


class SchemaManager:
    """
    Veritabanı şemasını dinamik olarak okuyan, ilişkileri (PK/FK) analiz eden,
    LLM promptlarına uygun DDL + açıklamaları formatlayan ve soru odaklı tablo
    seçimi (Table Pruning) gerçekleştiren merkezi yönetici sınıf.
    """

    def __init__(
        self,
        engine: Optional[Engine] = None,
        metadata_dict: Optional[Dict[str, Dict[str, Any]]] = None,
    ):
        """
        SchemaManager yapılandırıcısı.

        Args:
            engine: SQLAlchemy Engine nesnesi (None ise core/database.py içindeki engine kullanılır).
            metadata_dict: Tablo açıklamaları sözlüğü (None ise NORTHWIND_METADATA kullanılır).
        """
        self.engine: Engine = engine if engine is not None else default_engine
        self.metadata_dict: Dict[str, Dict[str, Any]] = (
            metadata_dict if metadata_dict is not None else NORTHWIND_METADATA
        )
        self._inspector: Optional[Inspector] = None
        self._schema_cache: Dict[str, Dict[str, Any]] = {}
        self._table_names: List[str] = []
        self._relationship_graph: Dict[str, Set[str]] = defaultdict(set)
        
        # İlk yüklemeyi başlat
        self.refresh_schema()

    def refresh_schema(self) -> None:
        """
        Veritabanı şema bilgilerini yeniden inceler ve önbelleği günceller.
        """
        self._inspector = inspect(self.engine)
        self._table_names = sorted(self._inspector.get_table_names())
        self._schema_cache.clear()
        self._relationship_graph.clear()

        for table_name in self._table_names:
            table_info = self._inspect_table(table_name)
            self._schema_cache[table_name] = table_info
            
            # İlişki grafiğini oluştur
            for fk in table_info["foreign_keys"]:
                ref_table = fk.get("referred_table")
                if ref_table:
                    # Çift yönlü kenar ekle (ilişki grafiği aramaları için)
                    self._relationship_graph[table_name].add(ref_table)
                    self._relationship_graph[ref_table].add(table_name)

    def _inspect_table(self, table_name: str) -> Dict[str, Any]:
        """
        Belirtilen tablonun kolonlarını, veri tiplerini, PK ve FK'larını çıkarır.
        """
        columns = self._inspector.get_columns(table_name)
        pk_constraint = self._inspector.get_pk_constraint(table_name)
        foreign_keys = self._inspector.get_foreign_keys(table_name)

        pk_cols = pk_constraint.get("constrained_columns", []) if pk_constraint else []

        formatted_columns = []
        for col in columns:
            col_name = col["name"]
            col_type = str(col["type"])
            nullable = col.get("nullable", True)
            is_pk = col_name in pk_cols

            formatted_columns.append({
                "name": col_name,
                "type": col_type,
                "nullable": nullable,
                "is_primary_key": is_pk,
                "default": col.get("default"),
            })

        formatted_fks = []
        for fk in foreign_keys:
            formatted_fks.append({
                "constrained_columns": fk.get("constrained_columns", []),
                "referred_table": fk.get("referred_table"),
                "referred_columns": fk.get("referred_columns", []),
                "name": fk.get("name"),
            })

        return {
            "table_name": table_name,
            "columns": formatted_columns,
            "primary_keys": pk_cols,
            "foreign_keys": formatted_fks,
        }

    def get_table_names(self) -> List[str]:
        """
        Veritabanında bulunan tüm tablo isimlerini alfabetik sırada döner.
        """
        return list(self._table_names)

    def get_all_tables(self) -> List[str]:
        """
        Veritabanında bulunan tüm tablo isimlerini alfabetik sırada döner (get_table_names ile eşdeğerdir).
        """
        return self.get_table_names()

    def resolve_table_name(self, table_name: str) -> Optional[str]:
        """
        Büyük/küçük harf veya boşluk/bitişik yazım (ör. OrderDetails vs 'Order Details')
        farklılıklarını tolere ederek gerçek tablo adını döner.
        """
        if table_name in self._table_names:
            return table_name

        cleaned_target = re.sub(r"[_\s]", "", table_name).lower()

        # Önce metadata alias kontrolü
        for actual_name, meta in self.metadata_dict.items():
            if meta.get("alias") and meta["alias"].lower() == cleaned_target:
                if actual_name in self._table_names:
                    return actual_name

        # Sonra veritabanındaki tablolar arasında ara
        for actual_name in self._table_names:
            cleaned_actual = re.sub(r"[_\s]", "", actual_name).lower()
            if cleaned_actual == cleaned_target:
                return actual_name

        return None

    def get_table_info(self, table_name: str) -> Optional[Dict[str, Any]]:
        """
        Tek bir tablonun detaylı şema bilgisini döner.
        """
        resolved = self.resolve_table_name(table_name)
        if not resolved:
            return None
        return self._schema_cache.get(resolved)

    def get_table_description(self, table_name: str) -> str:
        """
        Tablonun metadata sözlüğündeki Türkçe iş tanımını döner.
        """
        resolved = self.resolve_table_name(table_name)
        if not resolved:
            return ""
        
        meta = self.metadata_dict.get(resolved)
        if meta and "description" in meta:
            return meta["description"]

        # Alias üzerinden dene
        for k, v in self.metadata_dict.items():
            if v.get("alias") == resolved or k == resolved:
                return v.get("description", "")
        return ""

    def generate_ddl(self, table_name: str) -> str:
        """
        Tek bir tablo için okunabilir, SQL standartlarında CREATE TABLE DDL metni üretir.
        Boşluk içeren tablo isimlerini çift tırnak (`"Order Details"`) ile sarar.
        """
        resolved = self.resolve_table_name(table_name)
        if not resolved:
            return f"-- Tablo bulunamadı: {table_name}"

        info = self._schema_cache[resolved]
        quoted_table_name = f'"{resolved}"' if " " in resolved else resolved

        lines = [f"CREATE TABLE {quoted_table_name} ("]
        col_defs = []

        for col in info["columns"]:
            col_name = f'"{col["name"]}"' if " " in col["name"] else col["name"]
            type_str = col["type"]
            nullable_str = "" if col["nullable"] else " NOT NULL"
            pk_str = " PRIMARY KEY" if (col["is_primary_key"] and len(info["primary_keys"]) == 1) else ""
            col_defs.append(f"    {col_name} {type_str}{nullable_str}{pk_str}")

        # Bileşik Primary Key varsa ekle
        if len(info["primary_keys"]) > 1:
            quoted_pks = [f'"{pk}"' if " " in pk else pk for pk in info["primary_keys"]]
            col_defs.append(f"    PRIMARY KEY ({', '.join(quoted_pks)})")

        # Foreign Key kısıtlamalarını ekle
        for fk in info["foreign_keys"]:
            ref_table = fk["referred_table"]
            if ref_table:
                quoted_ref_table = f'"{ref_table}"' if " " in ref_table else ref_table
                constrained = [f'"{c}"' if " " in c else c for c in fk["constrained_columns"]]
                referred = [f'"{r}"' if " " in r else r for r in fk["referred_columns"]]
                col_defs.append(
                    f"    FOREIGN KEY ({', '.join(constrained)}) REFERENCES {quoted_ref_table} ({', '.join(referred)})"
                )

        lines.append(",\n".join(col_defs))
        lines.append(");")
        return "\n".join(lines)

    def get_relationships(self, table_names: Optional[List[str]] = None) -> List[Dict[str, str]]:
        """
        Seçili tablolar (veya tüm tablolar) arasındaki Foreign Key ilişkilerini
        okunabilir bir liste halinde döner.
        """
        target_tables = set()
        if table_names is None:
            target_tables = set(self._table_names)
        else:
            for name in table_names:
                resolved = self.resolve_table_name(name)
                if resolved:
                    target_tables.add(resolved)

        relationships = []
        for table_name in sorted(target_tables):
            info = self._schema_cache.get(table_name, {})
            for fk in info.get("foreign_keys", []):
                ref_table = fk.get("referred_table")
                if not ref_table:
                    continue

                # Eğer iki tablo da hedef kümedeyse veya tablo filtresi verilmediyse ekle
                if table_names is None or ref_table in target_tables:
                    from_cols = fk.get("constrained_columns", [])
                    to_cols = fk.get("referred_columns", [])
                    from_str = f"{table_name}.({', '.join(from_cols)})"
                    to_str = f"{ref_table}.({', '.join(to_cols)})"

                    relationships.append({
                        "from_table": table_name,
                        "from_columns": from_cols,
                        "to_table": ref_table,
                        "to_columns": to_cols,
                        "join_condition": f"{from_str} -> {to_str}",
                        "sql_join_example": f"{table_name}.{from_cols[0]} = {ref_table}.{to_cols[0]}" if from_cols and to_cols else "",
                    })

        return relationships

    def get_formatted_schema(
        self,
        table_names: Optional[List[str]] = None,
        include_descriptions: bool = True,
        include_relationships: bool = True,
        sample_rows_count: int = 0,
    ) -> str:
        """
        LLM System Prompt'una doğrudan enjekte edilebilecek temiz, zenginleştirilmiş
        Markdown/DDL şema metni üretir.

        Args:
            table_names: Formatlanacak tabloların listesi (None ise tüm tablolar).
            include_descriptions: Tablo ve kritik kolon açıklamalarının eklenip eklenmeyeceği.
            include_relationships: Şema sonuna açık Foreign Key ilişki özetinin eklenip eklenmeyeceği.
            sample_rows_count: Her tablodan eklenecek örnek veri satırı sayısı (varsayılan 0).

        Returns:
            LLM için hazır formatlanmış şema metni.
        """
        resolved_tables: List[str] = []
        if table_names is None:
            resolved_tables = list(self._table_names)
        else:
            for name in table_names:
                resolved = self.resolve_table_name(name)
                if resolved and resolved not in resolved_tables:
                    resolved_tables.append(resolved)

        if not resolved_tables:
            return "Veritabanında görüntülenecek tablo bulunamadı."

        sections: List[str] = ["### VERİTABANI ŞEMA VE METADATA TANIMLARI\n"]

        for table_name in resolved_tables:
            quoted_name = f'"{table_name}"' if " " in table_name else table_name
            sections.append(f"#### Tablo: `{table_name}` (SQL: `{quoted_name}`)")

            # Tablo Açıklaması
            if include_descriptions:
                desc = self.get_table_description(table_name)
                if desc:
                    sections.append(f"- **İş Açıklaması:** {desc}")

                # Kolon detayları ve ipuçları
                meta = self.metadata_dict.get(table_name) or {}
                key_columns = meta.get("key_columns", {})
                if key_columns:
                    col_hints = []
                    for col_k, col_v in key_columns.items():
                        col_hints.append(f"`{col_k}`: {col_v}")
                    sections.append(f"- **Önemli Kolonlar:** {'; '.join(col_hints)}")

            # DDL Bloğu
            ddl = self.generate_ddl(table_name)
            sections.append("```sql")
            sections.append(ddl)
            sections.append("```")

            # Örnek Satırlar (İsteğe bağlı)
            if sample_rows_count > 0:
                try:
                    with self.engine.connect() as conn:
                        q_name = f'"{table_name}"' if " " in table_name else table_name
                        res = conn.execute(text(f"SELECT * FROM {q_name} LIMIT {sample_rows_count}"))
                        rows = res.fetchall()
                        cols = list(res.keys())
                        if rows:
                            sections.append(f"**Örnek Veri ({len(rows)} satır):**")
                            header = "| " + " | ".join(cols) + " |"
                            divider = "| " + " | ".join(["---"] * len(cols)) + " |"
                            data_lines = [
                                "| " + " | ".join(str(val) if val is not None else "NULL" for val in r) + " |"
                                for r in rows
                            ]
                            sections.append("\n".join([header, divider] + data_lines))
                except Exception:
                    pass

            sections.append("")  # Tablolar arası boşluk

        # İlişkiler Özeti
        if include_relationships:
            relationships = self.get_relationships(resolved_tables)
            if relationships:
                sections.append("### TABLOLAR ARASI İLİŞKİLER (JOIN REHBERİ)")
                sections.append(
                    "Sorgularda tabloları birleştirirken (JOIN) aşağıdaki ilişkileri ve anahtarları kullanın:\n"
                )
                for rel in relationships:
                    sections.append(
                        f"- `{rel['from_table']}` -> `{rel['to_table']}` : `ON {rel['sql_join_example']}`"
                    )
                sections.append("")

        return "\n".join(sections).strip()

    def is_query_domain_relevant(self, query: str) -> Tuple[bool, float, List[str]]:
        """
        Kullanıcı sorusunun Northwind veritabanı şeması ve iş alanı ile ilgili olup olmadığını inceler.
        
        Out-of-domain (alan dışı) sorgular:
        - Veritabanı şemasıyla hiçbir ilgisi olmayan konular (şifreler, bitcoin/kripto, hava durumu, döviz vb.).
        - Anahtar kelime, tablo adı ve kolon eşleşme skoru 0 olan veya belirgin alan dışı kelimeler içeren sorular.

        Returns:
            (is_relevant: bool, total_relevance_score: float, relevant_tables: list[str])
        """
        if not query or not query.strip():
            return False, 0.0, []

        normalized_query = _turkish_lower(query.strip())
        words = set(re.findall(r"\b\w+\b", normalized_query))

        # Açıkça alan dışı veya güvenlik dışı anahtar kelimeler
        explicit_out_of_domain = [
            "bitcoin", "btc", "kripto", "ethereum", "crypto", "blockchain",
            "hava durumu", "havadurumu", "weather",
            "şifre", "sifre", "password", "parola", "secret", "token", "auth_token",
            "dolar kuru", "euro kuru", "altın fiyatı", "borsa",
            "futbol", "maç skoru", "mac skoru", "basketbol",
        ]
        for bad_kw in explicit_out_of_domain:
            if bad_kw in normalized_query:
                return False, 0.0, []

        scores: Dict[str, float] = defaultdict(float)

        for table_name in self._table_names:
            meta = self.metadata_dict.get(table_name, {})
            score = 0.0

            t_norm = _turkish_lower(table_name)
            if t_norm in normalized_query:
                score += 20.0

            alias = meta.get("alias")
            if alias and _turkish_lower(alias) in normalized_query:
                score += 20.0

            keywords = meta.get("keywords", [])
            for kw in keywords:
                kw_norm = _turkish_lower(kw)
                if kw_norm in words:
                    score += 10.0
                elif any(w.startswith(kw_norm) for w in words if len(kw_norm) >= 3):
                    score += 8.0
                elif kw_norm in normalized_query and len(kw_norm) >= 4:
                    score += 5.0

            info = self._schema_cache.get(table_name, {})
            for col in info.get("columns", []):
                col_name_norm = _turkish_lower(col["name"])
                if col_name_norm in words:
                    score += 6.0
                elif any(w.startswith(col_name_norm) for w in words if len(col_name_norm) >= 4):
                    score += 4.0
                elif len(col_name_norm) >= 5 and col_name_norm in normalized_query:
                    score += 3.0

            desc = meta.get("description", "")
            if desc:
                desc_norm = _turkish_lower(desc)
                matched_desc_words = [w for w in words if len(w) > 3 and w in desc_norm]
                score += len(matched_desc_words) * 1.5

            if score > 0:
                scores[table_name] = score

        total_score = sum(scores.values())
        if total_score < 4.0:
            return False, total_score, []

        relevant_tables = self.get_relevant_tables(query)
        return True, total_score, relevant_tables

    def get_relevant_tables(
        self,
        query: str,
        max_tables: Optional[int] = None,
        include_foreign_keys: bool = True,
    ) -> List[str]:
        """
        Kullanıcının sorduğu doğal dil sorusuna (Türkçe/İngilizce) göre en ilgili
        tabloları tespit eder (Table Pruning).

        Algoritma:
        1. Soru metnini normalize eder ve anahtar kelime eşleşmelerini puanlar.
        2. Tablo isimleri, kolon adları, metadata anahtar kelimeleri ve tanımları üzerinden puanlama yapar.
        3. Eşleşen tablolar arasında Foreign Key bağımlılıklarını inceler.
           Örneğin `Customers` ve `Products` seçildiyse aradaki `Orders` ve `Order Details`
           köprü tablolarını otomatik olarak dahil eder (FK Genişletme).
        4. Eşleşme bulunamazsa en kritik ana tabloları döner.

        Args:
            query: Kullanıcının girdiği doğal dil sorusu.
            max_tables: Döndürülecek maksimum tablo sayısı (None ise kısıtlama yok).
            include_foreign_keys: Seçilen tabloları bağlayan köprü tabloların otomatik eklenmesi.

        Returns:
            Seçilen ilgili tablo adlarının listesi.
        """
        if not query or not query.strip():
            default_core = ["Customers", "Orders", "Order Details", "Products"]
            return [t for t in default_core if t in self._table_names][:max_tables]

        normalized_query = _turkish_lower(query)
        words = set(re.findall(r"\b\w+\b", normalized_query))

        scores: Dict[str, float] = defaultdict(float)

        for table_name in self._table_names:
            meta = self.metadata_dict.get(table_name, {})
            score = 0.0

            # 1. Tablo adı doğrudan sorguda geçiyor mu?
            t_norm = _turkish_lower(table_name)
            if t_norm in normalized_query:
                score += 20.0

            alias = meta.get("alias")
            if alias and _turkish_lower(alias) in normalized_query:
                score += 20.0

            # 2. Metadata Anahtar Kelimeleri (Keywords) Eşleşmesi
            keywords = meta.get("keywords", [])
            for kw in keywords:
                kw_norm = _turkish_lower(kw)
                if kw_norm in words:
                    score += 10.0
                elif any(w.startswith(kw_norm) for w in words if len(kw_norm) >= 3):
                    score += 8.0
                elif kw_norm in normalized_query and len(kw_norm) >= 4:
                    score += 5.0

            # 3. Kolon Adları Eşleşmesi
            info = self._schema_cache.get(table_name, {})
            for col in info.get("columns", []):
                col_name_norm = _turkish_lower(col["name"])
                if col_name_norm in words:
                    score += 6.0
                elif any(w.startswith(col_name_norm) for w in words if len(col_name_norm) >= 4):
                    score += 4.0
                elif len(col_name_norm) >= 5 and col_name_norm in normalized_query:
                    score += 3.0

            # 4. İş Tanımı ve Kolon İpuçları Eşleşmesi
            desc = meta.get("description", "")
            if desc:
                desc_norm = _turkish_lower(desc)
                matched_desc_words = [w for w in words if len(w) > 3 and w in desc_norm]
                score += len(matched_desc_words) * 1.5

            if score > 0:
                scores[table_name] = score

        # Pozitif puan alan tabloları sırala
        positive_scored = [
            (t, s) for t, s in sorted(scores.items(), key=lambda item: item[1], reverse=True)
            if s > 0
        ]

        if not positive_scored:
            fallback = ["Customers", "Orders", "Order Details", "Products", "Employees"]
            ranked_tables = [t for t in fallback if t in self._table_names]
        else:
            top_score = positive_scored[0][1]
            threshold = max(top_score * 0.35, 5.0)
            selected_tables = [t for t, s in positive_scored if s >= threshold]
            if not selected_tables:
                selected_tables = [positive_scored[0][0]]
            ranked_tables = selected_tables

        # FK Genişletme (Bridge Table Expansion):
        # Seçilen tablolar arasında bağlantı kopukluğu varsa (ör: Customers ve Products var ama Orders ve Order Details yoksa)
        # en kısa yol (BFS) ile aradaki köprü tabloları ekle.
        if include_foreign_keys and len(ranked_tables) >= 2:
            expanded_set: Set[str] = set(ranked_tables)
            initial_selected = list(ranked_tables)

            for i in range(len(initial_selected)):
                for j in range(i + 1, len(initial_selected)):
                    t1, t2 = initial_selected[i], initial_selected[j]
                    path = self._find_shortest_relationship_path(t1, t2)
                    if path:
                        for bridge_table in path:
                            expanded_set.add(bridge_table)

            # Orijinal sıralamayı koru, yeni eklenen köprü tabloları arkasına ekle
            final_tables = [t for t in ranked_tables]
            for t in expanded_set:
                if t not in final_tables and t in self._table_names:
                    final_tables.append(t)
            ranked_tables = final_tables

        if max_tables is not None and max_tables > 0:
            return ranked_tables[:max_tables]

        return ranked_tables

    def _find_shortest_relationship_path(self, start_table: str, target_table: str) -> List[str]:
        """
        İki tablo arasındaki en kısa Foreign Key ilişki yolunu (BFS) bulur.
        Örnek: Customers -> Orders -> Order Details -> Products
        """
        if start_table == target_table:
            return [start_table]

        queue: deque[Tuple[str, List[str]]] = deque([(start_table, [start_table])])
        visited: Set[str] = {start_table}

        while queue:
            current, path = queue.popleft()
            if len(path) > 4:  # Çok uzun alakasız zincirleri engelle
                continue

            for neighbor in self._relationship_graph.get(current, set()):
                if neighbor == target_table:
                    return path + [neighbor]
                if neighbor not in visited:
                    visited.add(neighbor)
                    queue.append((neighbor, path + [neighbor]))

        return []

    def get_database_summary(self) -> Dict[str, Any]:
        """
        Veritabanının genel istatistiklerini (tablo sayısı, toplam kolon, ilişkiler) özetler.
        """
        total_columns = sum(len(info["columns"]) for info in self._schema_cache.values())
        all_relationships = self.get_relationships()

        return {
            "database_type": self.engine.name,
            "table_count": len(self._table_names),
            "tables": self._table_names,
            "total_columns": total_columns,
            "relationship_count": len(all_relationships),
            "relationships": all_relationships,
        }
