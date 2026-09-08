"""
Doğal Dil İşlemeli Akıllı Veri Analiz Asistanı - SQL Güvenlik ve Doğrulama Katmanı (SQLValidator)
sqlparse kütüphanesini kullanarak sorguları AST (Abstract Syntax Tree) seviyesinde
ayrıştırır, yalnızca salt-okunur SELECT/WITH sorgularına izin verir ve çoklu sorgu
(stacked query) ya da DDL/DML girişimlerini engeller.
"""

import re
from typing import Any, List, Optional, Set, Tuple
import sqlparse
from sqlparse.sql import Comment, Identifier, IdentifierList, Statement, Token, TokenList
from sqlparse.tokens import DDL, DML, Keyword, Punctuation


class SecurityViolationError(Exception):
    """
    Güvenlik kurallarının ihlal edildiği, zararlı veya izin verilmeyen
    SQL komutları tespit edildiğinde fırlatılan özel istisna sınıfı.
    """
    pass


class SQLValidator:
    """
    SQL sorgularını AST seviyesinde analiz eden ve güvenlik denetiminden geçiren sınıf.
    """

    # Kesinlikle yasaklanmış DDL / DML / Yönetim anahtar kelimeleri
    FORBIDDEN_KEYWORDS: Set[str] = {
        "DROP",
        "DELETE",
        "TRUNCATE",
        "INSERT",
        "UPDATE",
        "ALTER",
        "GRANT",
        "REVOKE",
        "EXEC",
        "EXECUTE",
        "CREATE",
        "REPLACE",
        "ATTACH",
        "DETACH",
        "PRAGMA",
        "MERGE",
        "CALL",
        "SHUTDOWN",
        "REINDEX",
        "VACUUM",
    }

    @classmethod
    def is_valid_select(cls, sql: str) -> Tuple[bool, str]:
        """
        Verilen SQL sorgusunun güvenli, tekil ve salt-okunur bir SELECT / CTE sorgusu
        olup olmadığını denetler.

        Args:
            sql: Denetlenecek ham veya temizlenmiş SQL sorgusu.

        Returns:
            (is_safe: bool, message: str)
            - Güvenliyse: (True, "")
            - İhlal varsa: (False, "Hata / İhlal açıklaması")
        """
        if not sql or not sql.strip():
            return False, "Sorgu boş olamaz."

        raw_sql = sql.strip()

        # 1. sqlparse ile AST ayrıştırması yap
        try:
            parsed_statements = sqlparse.parse(raw_sql)
        except Exception as exc:
            return False, f"SQL ayrıştırma (parse) hatası: {str(exc)}"

        if not parsed_statements:
            return False, "Geçerli bir SQL ifadesi bulunamadı."

        # Boş olmayan gerçek ifadeleri filtrele (yorum satırları veya sadece boşlukları ele)
        valid_statements = [
            s for s in parsed_statements
            if any(not t.is_whitespace and not isinstance(t, Comment) for t in s.tokens)
        ]

        if not valid_statements:
            return False, "Sorgu yalnızca yorum satırlarından veya boşluklardan oluşuyor."

        # 2. Çoklu sorgu (Stacked Query) denetimi
        # Noktalı virgülle birden fazla ifade çalıştırılmasını engelle
        if len(valid_statements) > 1:
            return False, "Güvenlik İhlali: Çoklu SQL ifadelerine (Stacked Queries / Semicolon Injection) izin verilmemektedir."

        stmt: Statement = valid_statements[0]

        # 3. AST Token Ağacını Tara (Öncelikli Yasaklı Kelime Taraması)
        forbidden_found = cls._scan_tokens_for_forbidden_keywords(stmt)
        if forbidden_found:
            return False, f"Güvenlik İhlali: Yasaklı '{forbidden_found}' komutu tespit edildi."

        # 4. İfade Tipi Kontrolü (Statement Type)
        first_keyword = cls._get_first_keyword(stmt)
        stmt_type = stmt.get_type().upper()

        if first_keyword not in ("SELECT", "WITH") and stmt_type != "SELECT":
            detected = first_keyword or stmt_type or "Bilinmeyen"
            return False, f"Güvenlik İhlali: Yalnızca SELECT sorgularına izin verilmektedir. Tespit edilen komut: '{detected}'"

        # 5. 'SELECT ... INTO ...' Tablo Oluşturma Modeli Kontrolü
        if cls._has_select_into(stmt):
            return False, "Güvenlik İhlali: 'SELECT INTO' ile yeni tablo oluşturma ifadesine izin verilmemektedir."

        # 6. Ek Güvenlik: Regex bazlı nihai kontrol
        regex_error = cls._regex_safety_check(raw_sql)
        if regex_error:
            return False, regex_error

        return True, ""

    @classmethod
    def validate(cls, sql: str) -> str:
        """
        SQL sorgusunu denetler. Güvenliyse temizlenmiş SQL metnini döner,
        ihlal durumunda SecurityViolationError fırlatır.

        Args:
            sql: Denetlenecek SQL sorgusu.

        Returns:
            Temizlenmiş SQL metni.

        Raises:
            SecurityViolationError: Güvenlik ihlali tespit edildiğinde.
        """
        is_safe, error_message = cls.is_valid_select(sql)
        if not is_safe:
            raise SecurityViolationError(error_message)

        cleaned = sql.strip().rstrip(";").strip()
        return cleaned

    @classmethod
    def _get_first_keyword(cls, stmt: Statement) -> str:
        """AST içindeki ilk anlamlı anahtar kelimeyi bulur."""
        for token in stmt.flatten():
            if token.is_whitespace or isinstance(token, Comment):
                continue
            val = token.value.strip().upper()
            if val:
                return val
        return ""

    @classmethod
    def _scan_tokens_for_forbidden_keywords(cls, token_list: TokenList) -> Optional[str]:
        """
        AST token listesini derinlemesine tarayarak yasaklı anahtar kelimeleri arar.
        """
        for token in token_list.flatten():
            if token.is_whitespace or isinstance(token, Comment):
                continue

            token_val = token.value.strip().upper()

            # Doğrudan anahtar kelime kontrolü
            if token_val in cls.FORBIDDEN_KEYWORDS:
                return token_val

            # DML veya DDL tipindeki token kontrolü
            if token.ttype in (DML, DDL):
                if token_val in cls.FORBIDDEN_KEYWORDS:
                    return token_val

        return None

    @classmethod
    def _has_select_into(cls, stmt: Statement) -> bool:
        """'SELECT ... INTO new_table' kalıbının varlığını denetler."""
        tokens = [t for t in stmt.flatten() if not t.is_whitespace and not isinstance(t, Comment)]
        for i, token in enumerate(tokens):
            if token.value.upper() == "INTO":
                # Bir önceki token SELECT veya kolon listesi bağlamındaysa
                return True
        return False

    @classmethod
    def _regex_safety_check(cls, sql: str) -> Optional[str]:
        """Regex ile ek güvenlik katmanı denetimi."""
        # Çoklu sorgu noktalı virgül denetimi (tırnak dışındaki ;)
        cleaned_no_quotes = re.sub(r"'[^']*'|\"[^\"]*\"", "", sql).strip()
        cleaned_no_quotes = cleaned_no_quotes.rstrip(";")
        if ";" in cleaned_no_quotes:
            return "Güvenlik İhlali: Çoklu SQL ifadesi (;) tespit edildi."

        # Yasaklı kelimeler sınır kontrolü
        for kw in cls.FORBIDDEN_KEYWORDS:
            pattern = rf"\b{kw}\b"
            if re.search(pattern, cleaned_no_quotes, re.IGNORECASE):
                match = re.search(pattern, cleaned_no_quotes, re.IGNORECASE).group(0)
                return f"Güvenlik İhlali: Yasaklı '{match}' ifadesi tespit edildi."

        return None

    @classmethod
    def extract_tables(cls, sql: str) -> List[str]:
        """
        AST üzerinden sorguda başvurulan (FROM / JOIN) tablo isimlerini ayıklar.
        """
        tables: List[str] = []
        try:
            parsed = sqlparse.parse(sql)
            if not parsed:
                return []

            stmt = parsed[0]
            from_seen = False

            for token in stmt.flatten():
                if token.is_whitespace or isinstance(token, Comment):
                    continue

                val = token.value.strip()
                val_upper = val.upper()

                if val_upper in ("FROM", "JOIN", "INNER JOIN", "LEFT JOIN", "RIGHT JOIN", "FULL JOIN"):
                    from_seen = True
                    continue

                if from_seen:
                    if val_upper in ("WHERE", "GROUP", "ORDER", "LIMIT", "HAVING", "SET", "ON", "USING", "AS"):
                        from_seen = False
                        continue

                    # Tablo adı olabilecek token
                    clean_table = val.strip('"`[]')
                    if clean_table and clean_table not in tables and re.match(r"^[A-Za-z0-9_ ]+$", clean_table):
                        tables.append(clean_table)
                        from_seen = False
        except Exception:
            pass

        return tables
