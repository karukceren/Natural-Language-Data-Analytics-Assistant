"""
Doğal Dil İşlemeli Akıllı Veri Analiz Asistanı - Ana CLI ve Test Çalıştırma Arayüzü
"""

import argparse
from pathlib import Path
import sys

# Windows konsol UTF-8 çıktı desteği
if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except Exception:
        pass

# Proje kök dizinini sys.path'e ekle
PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from tabulate import tabulate

from src.ai.few_shot_manager import FewShotManager
from src.ai.schema_manager import SchemaManager
from src.ai.sql_generator import SQLGenerator
from src.ai.sql_healing import SQLSelfHealingAgent, QueryExecutionError
from src.core.config import settings
from src.core.database import test_connection, execute_read_only_query


def print_banner():
    print("=" * 70)
    print(f"[*] {settings.APP_NAME}")
    print(f"[*] Saglayici: {settings.DEFAULT_LLM_PROVIDER.upper()} | Model: {settings.DEFAULT_MODEL_NAME}")
    print("=" * 70)


def run_single_query(agent: SQLSelfHealingAgent, question: str, dry_run: bool = False):
    print(f"\n[?] Soru: {question}")
    print("-" * 50)

    try:
        if dry_run:
            sql = agent.sql_generator.generate_sql(question)
            print(f"[SQL] Uretilen SQL (Dry-Run):\n\n{sql}\n")
            return

        print("[*] Sorgu uretiliyor ve calistiriliyor (Self-Healing aktif)...")
        df, final_sql, history = agent.execute_with_healing(question)

        # Eger tamir denemeleri yapildiysa gecmisi goster
        if len(history) > 2:
            print("\n[i] Self-Healing Tamir Adimlari:")
            for h in history[:-1]:
                print(f"    -> {h}")

        print(f"\n[SQL] Nihai SQL:\n\n{final_sql}\n")

        if not df.empty:
            table_str = tabulate(
                df.head(20),
                headers="keys",
                tablefmt="rounded_grid",
                showindex=False,
            )
            print(table_str)
            print(f"\n[+] Toplam {len(df)} satir listelendi.")
        else:
            print("[!] Sorgu calisti fakat eslesen kayit bulunamadi (0 satir).")

    except QueryExecutionError as q_err:
        print(f"[-] Calistirma Hatasi: {q_err.message}")
        if q_err.attempts:
            print("[-] Tamir Gecmisi:")
            for att in q_err.attempts:
                print(f"    {att}")
    except Exception as exc:
        print(f"[-] Hata olustu: {exc}")


def interactive_mode(agent: SQLSelfHealingAgent):
    print("\n[i] Interaktif Sohbet Modu Acildi. Cikmak icin 'q' veya 'exit' yazin.\n")
    
    sample_questions = [
        "1. En pahali 5 urunu fiyatiyla birlikte listele.",
        "2. Hangi ulkelerden kacar tane musteri var?",
        "3. 1997 yilinda en cok siparis veren 3 musteri kimdir?",
    ]
    print("Ornek Sorular:")
    for sq in sample_questions:
        print(f"   {sq}")
    print("-" * 50)

    while True:
        try:
            user_input = input("\n[?] Sorunuzu girin > ").strip()
            if not user_input:
                continue
            if user_input.lower() in ("q", "exit", "quit", "cikis"):
                print("[*] Gorusmek uzere!")
                break

            run_single_query(agent, user_input)
        except (KeyboardInterrupt, EOFError):
            print("\n[*] Cikis yapildi.")
            break


def main():
    parser = argparse.ArgumentParser(
        description="Dogal Dil Islemeli Akilli Veri Analiz Asistani CLI"
    )
    parser.add_argument(
        "-q", "--question", type=str, help="Calistirilacak tekil dogal dil sorusu."
    )
    parser.add_argument(
        "--dry-run", action="store_true", help="Yalnizca SQL uret, veritabaninda calistirma."
    )
    parser.add_argument(
        "--test-db", action="store_true", help="Veritabani baglantisini ve tablolari test et."
    )
    parser.add_argument(
        "--schema", action="store_true", help="Formatlanmis semayi ve tablolari ekrana yazdir."
    )

    args = parser.parse_args()

    print_banner()

    if args.test_db:
        print("[*] Veritabani baglantisi kontrol ediliyor...")
        conn_res = test_connection()
        print(f"Durum: {conn_res['status']}")
        print(f"Tablo Sayisi: {conn_res['table_count']}")
        print(f"Tablolar: {', '.join(conn_res['tables'])}")
        return

    schema_mgr = SchemaManager()

    if args.schema:
        print(schema_mgr.get_formatted_schema())
        return

    agent = SQLSelfHealingAgent(schema_manager=schema_mgr)

    if args.question:
        run_single_query(agent, args.question, dry_run=args.dry_run)
    else:
        interactive_mode(agent)


if __name__ == "__main__":
    main()
