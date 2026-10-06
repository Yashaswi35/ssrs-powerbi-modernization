"""
Load extracted CSVs into Azure SQL staging, build the star schema, and run
reconciliation checks. Connection settings come from .env (see .env.example).
"""
import json
import os
import re
import sys
import time
from pathlib import Path

import pandas as pd
import pyodbc
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[1]
RAW_DIR = ROOT / "data" / "raw"
SQL_DIR = ROOT / "sql"
TERRITORY_MAP = ROOT / "config" / "territory_map.csv"
CHUNK_ROWS = 50_000

STG_COLUMNS = [
    "Prscrbr_NPI", "Prscrbr_Last_Org_Name", "Prscrbr_First_Name", "Prscrbr_City",
    "Prscrbr_State_Abrvtn", "Prscrbr_State_FIPS", "Prscrbr_Type", "Prscrbr_Type_Src",
    "Brnd_Name", "Gnrc_Name", "Tot_Clms", "Tot_30day_Fills", "Tot_Day_Suply",
    "Tot_Drug_Cst", "Tot_Benes", "GE65_Sprsn_Flag", "GE65_Tot_Clms",
    "GE65_Tot_30day_Fills", "GE65_Tot_Drug_Cst", "GE65_Tot_Day_Suply",
    "GE65_Bene_Sprsn_Flag", "GE65_Tot_Benes",
]
INT_COLS = ["Tot_Clms", "Tot_Day_Suply", "Tot_Benes", "GE65_Tot_Clms", "GE65_Tot_Day_Suply", "GE65_Tot_Benes"]
DEC_COLS = ["Tot_30day_Fills", "Tot_Drug_Cst", "GE65_Tot_30day_Fills", "GE65_Tot_Drug_Cst"]
TEXT_COLS = [c for c in STG_COLUMNS if c not in INT_COLS + DEC_COLS]


def connect(retries=3):
    load_dotenv(ROOT / ".env")
    conn_str = (
        "Driver={ODBC Driver 18 for SQL Server};"
        f"Server=tcp:{os.environ['AZURE_SQL_SERVER']},1433;"
        f"Database={os.environ['AZURE_SQL_DATABASE']};"
        f"Uid={os.environ['AZURE_SQL_USER']};"
        f"Pwd={os.environ['AZURE_SQL_PASSWORD']};"
        "Encrypt=yes;TrustServerCertificate=no;Connection Timeout=90;"
    )
    # Serverless databases auto-pause, so the first connection can time out while resuming
    for attempt in range(1, retries + 1):
        try:
            return pyodbc.connect(conn_str, autocommit=False)
        except pyodbc.Error as exc:
            if attempt == retries:
                raise
            print(f"Connection failed ({exc.args[0]}); database may be resuming. Retrying in 30s ...")
            time.sleep(30)


def run_sql_file(conn, name):
    sql = (SQL_DIR / name).read_text()
    batches = [b.strip() for b in re.split(r"^\s*GO\s*$", sql, flags=re.MULTILINE | re.IGNORECASE)]
    cur = conn.cursor()
    for batch in filter(None, batches):
        cur.execute(batch)
        while cur.nextset():
            pass
    conn.commit()
    print(f"Ran {name}")


def to_rows(df):
    return list(df.astype(object).where(df.notna(), None).itertuples(index=False, name=None))


def clean(chunk):
    df = chunk[STG_COLUMNS].copy()
    for c in INT_COLS:
        df[c] = pd.to_numeric(df[c], errors="coerce").round().astype("Int64")
    for c in DEC_COLS:
        df[c] = pd.to_numeric(df[c], errors="coerce").round(2)
    for c in TEXT_COLS:
        df[c] = df[c].str.strip().replace({"": None})
    return df


def load_small_tables(conn, manifest):
    cur = conn.cursor()
    territories = pd.read_csv(TERRITORY_MAP, dtype=str)
    cur.executemany(
        "INSERT INTO stg.territory_map (state_abbr, territory_name, region_name) VALUES (?, ?, ?)",
        to_rows(territories[["state_abbr", "territory_name", "region_name"]]),
    )
    cur.executemany(
        "INSERT INTO stg.source_manifest (state_abbr, rows_written, rows_expected) VALUES (?, ?, ?)",
        [(s, v["rows_written"], v["rows_expected"]) for s, v in manifest["states"].items()],
    )
    conn.commit()


def load_staging(conn, manifest):
    year = manifest["data_year"]
    cols = ["data_year"] + STG_COLUMNS
    insert_sql = (
        f"INSERT INTO stg.partd_prescriber_drug ({', '.join(cols)}) "
        f"VALUES ({', '.join('?' * len(cols))})"
    )
    cur = conn.cursor()
    cur.fast_executemany = True

    for state, info in manifest["states"].items():
        path = RAW_DIR / info["file"]
        loaded = 0
        for chunk in pd.read_csv(path, dtype=str, keep_default_na=False, chunksize=CHUNK_ROWS):
            df = clean(chunk)
            df.insert(0, "data_year", year)
            cur.executemany(insert_sql, to_rows(df))
            conn.commit()
            loaded += len(df)
            print(f"  {state}: {loaded:,} rows loaded")


def print_validation(conn):
    cur = conn.cursor()
    cur.execute(
        "SELECT check_name, expected_value, actual_value, status FROM dw.validation_results "
        "WHERE run_id = (SELECT MAX(run_id) FROM dw.validation_results) ORDER BY check_name"
    )
    rows = cur.fetchall()
    print("\nValidation results")
    for name, expected, actual, status in rows:
        print(f"  [{status}] {name}: expected {expected}, actual {actual}")
    return all(r.status in ("PASS", "SKIP") for r in rows)


def main():
    # --reporting-only rebuilds just the report views and RLS table on an existing warehouse
    if "--reporting-only" in sys.argv:
        conn = connect()
        try:
            run_sql_file(conn, "04_reporting_layer.sql")
        finally:
            conn.close()
        return

    manifest = json.loads((RAW_DIR / "manifest.json").read_text())
    conn = connect()
    try:
        run_sql_file(conn, "01_schema.sql")
        load_small_tables(conn, manifest)
        print("Loading staging ...")
        load_staging(conn, manifest)
        run_sql_file(conn, "02_build_star.sql")
        run_sql_file(conn, "03_validation.sql")
        ok = print_validation(conn)
        run_sql_file(conn, "04_reporting_layer.sql")
    finally:
        conn.close()
    if not ok:
        sys.exit("One or more validation checks failed.")


if __name__ == "__main__":
    main()
