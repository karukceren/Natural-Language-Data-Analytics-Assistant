import os
import sys
import sqlite3
import urllib.request
from pathlib import Path
from typing import List, Tuple

# Windows konsol çıktıları için UTF-8 kodlama güvenliği
if sys.stdout and hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass

# Proje ana dizinleri
PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
DATA_DIR = PROJECT_ROOT / "data"
DB_PATH = DATA_DIR / "northwind.db"

# Güvenilir Northwind SQLite kaynakları
PRIMARY_DB_URL = "https://raw.githubusercontent.com/jpwhite3/northwind-SQLite3/master/dist/northwind.db"
BACKUP_DB_URL = "https://github.com/jpwhite3/northwind-SQLite3/raw/master/dist/northwind.db"


def download_database(target_path: Path) -> bool:
    """
    Northwind SQLite veritabanı dosyasını indirir.
    """
    target_path.parent.mkdir(parents=True, exist_ok=True)
    print(f"📥 Northwind veritabanı indiriliyor: {PRIMARY_DB_URL}")
    
    urls_to_try = [PRIMARY_DB_URL, BACKUP_DB_URL]
    
    for url in urls_to_try:
        try:
            req = urllib.request.Request(
                url,
                headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}
            )
            with urllib.request.urlopen(req, timeout=15) as response, open(target_path, "wb") as out_file:
                out_file.write(response.read())
            
            # İndirilen dosyanın geçerli bir SQLite veritabanı olduğunu doğrula
            conn = sqlite3.connect(str(target_path))
            cursor = conn.cursor()
            cursor.execute("SELECT count(*) FROM sqlite_master WHERE type='table';")
            count = cursor.fetchone()[0]
            conn.close()
            
            if count > 0:
                print(f"✅ Veritabanı başarıyla indirildi ve doğrulandı ({target_path})")
                return True
        except Exception as e:
            print(f"⚠️ {url} üzerinden indirme başarısız oldu: {e}")
            if target_path.exists():
                target_path.unlink()

    return False


def create_minimal_northwind_fallback(target_path: Path) -> None:
    """
    İnternet bağlantısı olmaması durumunda temel Northwind şeması ve örnek verilerini oluşturan yedek mekanizma.
    """
    print("📦 Çevrimdışı yedek şema ve veriler oluşturuluyor...")
    target_path.parent.mkdir(parents=True, exist_ok=True)
    
    conn = sqlite3.connect(str(target_path))
    cursor = conn.cursor()

    cursor.executescript("""
    CREATE TABLE IF NOT EXISTS Categories (
        CategoryID INTEGER PRIMARY KEY AUTOINCREMENT,
        CategoryName TEXT NOT NULL,
        Description TEXT
    );

    CREATE TABLE IF NOT EXISTS Suppliers (
        SupplierID INTEGER PRIMARY KEY AUTOINCREMENT,
        CompanyName TEXT NOT NULL,
        ContactName TEXT,
        Country TEXT
    );

    CREATE TABLE IF NOT EXISTS Products (
        ProductID INTEGER PRIMARY KEY AUTOINCREMENT,
        ProductName TEXT NOT NULL,
        SupplierID INTEGER,
        CategoryID INTEGER,
        UnitPrice REAL DEFAULT 0,
        UnitsInStock INTEGER DEFAULT 0,
        FOREIGN KEY (CategoryID) REFERENCES Categories(CategoryID),
        FOREIGN KEY (SupplierID) REFERENCES Suppliers(SupplierID)
    );

    CREATE TABLE IF NOT EXISTS Customers (
        CustomerID TEXT PRIMARY KEY,
        CompanyName TEXT NOT NULL,
        ContactName TEXT,
        City TEXT,
        Country TEXT
    );

    CREATE TABLE IF NOT EXISTS Employees (
        EmployeeID INTEGER PRIMARY KEY AUTOINCREMENT,
        LastName TEXT NOT NULL,
        FirstName TEXT NOT NULL,
        Title TEXT,
        BirthDate TEXT,
        City TEXT,
        Country TEXT
    );

    CREATE TABLE IF NOT EXISTS Shippers (
        ShipperID INTEGER PRIMARY KEY AUTOINCREMENT,
        CompanyName TEXT NOT NULL,
        Phone TEXT
    );

    CREATE TABLE IF NOT EXISTS Orders (
        OrderID INTEGER PRIMARY KEY AUTOINCREMENT,
        CustomerID TEXT,
        EmployeeID INTEGER,
        OrderDate TEXT,
        ShipperID INTEGER,
        Freight REAL DEFAULT 0,
        ShipCity TEXT,
        ShipCountry TEXT,
        FOREIGN KEY (CustomerID) REFERENCES Customers(CustomerID),
        FOREIGN KEY (EmployeeID) REFERENCES Employees(EmployeeID),
        FOREIGN KEY (ShipperID) REFERENCES Shippers(ShipperID)
    );

    CREATE TABLE IF NOT EXISTS "Order Details" (
        OrderID INTEGER,
        ProductID INTEGER,
        UnitPrice REAL NOT NULL,
        Quantity INTEGER NOT NULL,
        Discount REAL DEFAULT 0,
        PRIMARY KEY (OrderID, ProductID),
        FOREIGN KEY (OrderID) REFERENCES Orders(OrderID),
        FOREIGN KEY (ProductID) REFERENCES Products(ProductID)
    );

    -- Örnek Veriler
    INSERT OR IGNORE INTO Categories (CategoryID, CategoryName, Description) VALUES
    (1, 'Beverages', 'Soft drinks, coffees, teas, beers, and ales'),
    (2, 'Condiments', 'Sweet and savory sauces, relishes, spreads, and seasonings'),
    (3, 'Confections', 'Desserts, candies, and sweet breads'),
    (4, 'Dairy Products', 'Cheeses'),
    (5, 'Grains/Cereals', 'Breads, crackers, pasta, and cereal'),
    (6, 'Meat/Poultry', 'Prepared meats'),
    (7, 'Produce', 'Dried fruit and bean curd'),
    (8, 'Seafood', 'Seaweed and fish');

    INSERT OR IGNORE INTO Suppliers (SupplierID, CompanyName, ContactName, Country) VALUES
    (1, 'Exotic Liquids', 'Charlotte Cooper', 'UK'),
    (2, 'New Orleans Cajun Delights', 'Shelley Burke', 'USA'),
    (3, 'Grandma Kelly''s Homestead', 'Regina Murphy', 'USA'),
    (4, 'Tokyo Traders', 'Yoshi Nagase', 'Japan');

    INSERT OR IGNORE INTO Products (ProductID, ProductName, SupplierID, CategoryID, UnitPrice, UnitsInStock) VALUES
    (1, 'Chai', 1, 1, 18.00, 39),
    (2, 'Chang', 1, 1, 19.00, 17),
    (3, 'Aniseed Syrup', 1, 2, 10.00, 13),
    (4, 'Chef Anton''s Cajun Seasoning', 2, 2, 22.00, 53),
    (5, 'Chef Anton''s Gumbo Mix', 2, 2, 21.35, 0),
    (6, 'Grandma''s Boysenberry Spread', 3, 2, 25.00, 120),
    (7, 'Uncle Bob''s Organic Dried Pears', 3, 7, 30.00, 15),
    (8, 'Northwoods Cranberry Sauce', 3, 2, 40.00, 6),
    (9, 'Mishi Kobe Niku', 4, 6, 97.00, 29),
    (10, 'Ikura', 4, 8, 31.00, 31);

    INSERT OR IGNORE INTO Customers (CustomerID, CompanyName, ContactName, City, Country) VALUES
    ('ALFKI', 'Alfreds Futterkiste', 'Maria Anders', 'Berlin', 'Germany'),
    ('ANATR', 'Ana Trujillo Emparedados y helados', 'Ana Trujillo', 'México D.F.', 'Mexico'),
    ('ANTON', 'Antonio Moreno Taquería', 'Antonio Moreno', 'México D.F.', 'Mexico'),
    ('AROUT', 'Around the Horn', 'Thomas Hardy', 'London', 'UK'),
    ('BERGS', 'Berglunds snabbköp', 'Christina Berglund', 'Luleå', 'Sweden');

    INSERT OR IGNORE INTO Employees (EmployeeID, LastName, FirstName, Title, BirthDate, City, Country) VALUES
    (1, 'Davolio', 'Nancy', 'Sales Representative', '1968-12-08', 'Seattle', 'USA'),
    (2, 'Fuller', 'Andrew', 'Vice President, Sales', '1972-02-19', 'Tacoma', 'USA'),
    (3, 'Leverling', 'Janet', 'Sales Representative', '1983-08-30', 'Kirkland', 'USA'),
    (4, 'Peacock', 'Margaret', 'Sales Representative', '1978-09-19', 'Redmond', 'USA'),
    (5, 'Buchanan', 'Steven', 'Sales Manager', '1975-03-04', 'London', 'UK');

    INSERT OR IGNORE INTO Shippers (ShipperID, CompanyName, Phone) VALUES
    (1, 'Speedy Express', '(503) 555-9831'),
    (2, 'United Package', '(503) 555-3199'),
    (3, 'Federal Shipping', '(503) 555-9931');

    INSERT OR IGNORE INTO Orders (OrderID, CustomerID, EmployeeID, OrderDate, ShipperID, Freight, ShipCity, ShipCountry) VALUES
    (10248, 'VINET', 5, '1996-07-04', 3, 32.38, 'Reims', 'France'),
    (10249, 'TOMSP', 6, '1996-07-05', 1, 11.61, 'Münster', 'Germany'),
    (10250, 'HANAR', 4, '1996-07-08', 2, 65.83, 'Rio de Janeiro', 'Brazil'),
    (10251, 'VICTE', 3, '1996-07-08', 1, 41.34, 'Lyon', 'France'),
    (10252, 'SUPRD', 4, '1996-07-09', 2, 51.30, 'Charleroi', 'Belgium');

    INSERT OR IGNORE INTO "Order Details" (OrderID, ProductID, UnitPrice, Quantity, Discount) VALUES
    (10248, 1, 14.00, 12, 0),
    (10248, 2, 9.80, 10, 0),
    (10249, 3, 18.60, 9, 0),
    (10250, 4, 18.40, 15, 0.05),
    (10251, 5, 16.80, 6, 0.05);
    """)

    conn.commit()
    conn.close()
    print("✅ Yedek Northwind veritabanı başarıyla oluşturuldu.")


def get_tables_info(db_path: Path) -> List[Tuple[str, int]]:
    """
    Veritabanındaki tüm tabloları ve satır sayılarını döndürür.
    """
    conn = sqlite3.connect(str(db_path))
    cursor = conn.cursor()
    
    # Tüm kullanıcı tablolarını al
    cursor.execute("""
        SELECT name FROM sqlite_master 
        WHERE type='table' AND name NOT LIKE 'sqlite_%'
        ORDER BY name;
    """)
    tables = cursor.fetchall()
    
    table_stats = []
    for (table_name,) in tables:
        # Boşluklu veya özel karakterli tablo isimleri için tırnak kullan
        safe_name = f'"{table_name}"'
        try:
            cursor.execute(f"SELECT COUNT(*) FROM {safe_name};")
            count = cursor.fetchone()[0]
            table_stats.append((table_name, count))
        except Exception:
            table_stats.append((table_name, 0))
            
    conn.close()
    return table_stats


def setup_database(force_download: bool = False) -> Path:
    """
    Veritabanı kurulumunu gerçekleştirir ve özet bilgileri ekrana basar.
    """
    print("=" * 60)
    print("🚀 Northwind Veritabanı Kurulum Süreci Başlatıldı")
    print("=" * 60)

    # Dosya yoksa veya boyutu geçersizse (<1024 bytes) yeniden oluştur/indir
    is_valid_db = DB_PATH.exists() and DB_PATH.stat().st_size > 1024

    if not is_valid_db or force_download:
        if DB_PATH.exists():
            DB_PATH.unlink()
        success = download_database(DB_PATH)
        if not success:
            create_minimal_northwind_fallback(DB_PATH)
    else:
        print(f"ℹ️ Veritabanı dosyası zaten mevcut: {DB_PATH}")

    # Tablo kontrolü ve özet gösterim
    table_stats = get_tables_info(DB_PATH)
    
    if not table_stats:
        print("⚠️ Tablolar bulunamadı, yedek şema yükleniyor...")
        create_minimal_northwind_fallback(DB_PATH)
        table_stats = get_tables_info(DB_PATH)
    
    print("\n📊 Veritabanı Tablo ve Kayıt Durumu:")
    print("-" * 45)
    print(f"{'Tablo Adı':<30} | {'Kayıt Sayısı':>10}")
    print("-" * 45)
    total_records = 0
    for name, count in table_stats:
        print(f"{name:<30} | {count:>10,}")
        total_records += count
    print("-" * 45)
    print(f"{'TOPLAM TABLO: ' + str(len(table_stats)):<30} | {'TOPLAM: ' + f'{total_records:,}':>10}")
    print("=" * 60)
    print("✅ Veritabanı kullanıma hazır!\n")
    
    return DB_PATH


if __name__ == "__main__":
    setup_database()
