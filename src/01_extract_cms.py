"""
Extract CMS Medicare Part D Prescribers by Provider and Drug (2024 release)
for the states listed in config/territory_map.csv, using the data.cms.gov API.

Writes one CSV per state to data/raw/ plus a manifest.json recording rows
written vs. rows the API reports, which the warehouse validation step reconciles.
"""
import json
import sys
import time
from pathlib import Path

import pandas as pd
import requests

DATA_YEAR = 2024
# 2024 dataset version ID, from the data.cms.gov API docs for this dataset
DATASET_VERSION_ID = "d5aa71a8-dcc0-4570-8bcf-bd39deac69fe"
BASE_URL = f"https://data.cms.gov/data-api/v1/dataset/{DATASET_VERSION_ID}/data"
PAGE_SIZE = 5000
MAX_RETRIES = 5

EXPECTED_COLUMNS = [
    "Prscrbr_NPI", "Prscrbr_Last_Org_Name", "Prscrbr_First_Name", "Prscrbr_City",
    "Prscrbr_State_Abrvtn", "Prscrbr_State_FIPS", "Prscrbr_Type", "Prscrbr_Type_Src",
    "Brnd_Name", "Gnrc_Name", "Tot_Clms", "Tot_30day_Fills", "Tot_Day_Suply",
    "Tot_Drug_Cst", "Tot_Benes", "GE65_Sprsn_Flag", "GE65_Tot_Clms",
    "GE65_Tot_30day_Fills", "GE65_Tot_Drug_Cst", "GE65_Tot_Day_Suply",
    "GE65_Bene_Sprsn_Flag", "GE65_Tot_Benes",
]

ROOT = Path(__file__).resolve().parents[1]
RAW_DIR = ROOT / "data" / "raw"
TERRITORY_MAP = ROOT / "config" / "territory_map.csv"


def get_with_retry(session, url, params):
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            resp = session.get(url, params=params, timeout=120)
            resp.raise_for_status()
            return resp.json()
        except (requests.RequestException, ValueError) as exc:
            wait = 2 ** attempt
            print(f"  request failed ({exc}); retry {attempt}/{MAX_RETRIES} in {wait}s")
            time.sleep(wait)
    raise RuntimeError(f"Giving up after {MAX_RETRIES} attempts: {url} {params}")


def expected_rows(session, state):
    """Row count the API reports for this filter, or None if the stats endpoint is unavailable."""
    try:
        stats = get_with_retry(session, f"{BASE_URL}/stats", {"filter[Prscrbr_State_Abrvtn]": state})
        return int(stats["found_rows"])
    except Exception as exc:  # stats are a nice-to-have, not a blocker
        print(f"  stats endpoint unavailable for {state} ({exc}); continuing without expected count")
        return None


def extract_state(session, state):
    out_path = RAW_DIR / f"partd_{DATA_YEAR}_{state}.csv"
    if out_path.exists():
        out_path.unlink()

    offset, written = 0, 0
    while True:
        params = {"filter[Prscrbr_State_Abrvtn]": state, "size": PAGE_SIZE, "offset": offset}
        page = get_with_retry(session, BASE_URL, params)
        if not page:
            break

        if written == 0:
            missing = set(EXPECTED_COLUMNS) - set(page[0].keys())
            if missing:
                raise RuntimeError(f"API response is missing expected columns: {sorted(missing)}")

        pd.DataFrame(page, columns=EXPECTED_COLUMNS).to_csv(
            out_path, mode="a", header=(written == 0), index=False
        )
        written += len(page)
        offset += PAGE_SIZE
        if written % 100_000 < PAGE_SIZE:
            print(f"  {state}: {written:,} rows so far")
        if len(page) < PAGE_SIZE:
            break

    return out_path, written


def main():
    RAW_DIR.mkdir(parents=True, exist_ok=True)
    states = pd.read_csv(TERRITORY_MAP, dtype=str)["state_abbr"].str.strip().unique().tolist()
    manifest = {"data_year": DATA_YEAR, "dataset_version_id": DATASET_VERSION_ID, "states": {}}

    with requests.Session() as session:
        for state in states:
            print(f"Extracting {state} ...")
            expected = expected_rows(session, state)
            path, written = extract_state(session, state)

            if expected is None:
                status = "SKIP"
            else:
                status = "PASS" if expected == written else "FAIL"
            expected_txt = f"{expected:,}" if expected is not None else "unknown"
            print(f"  {state}: wrote {written:,} rows, API reports {expected_txt} [{status}]")

            manifest["states"][state] = {
                "file": path.name,
                "rows_written": written,
                "rows_expected": expected,
                "status": status,
            }

    (RAW_DIR / "manifest.json").write_text(json.dumps(manifest, indent=2))
    print(f"Manifest written to {RAW_DIR / 'manifest.json'}")

    if any(s["status"] == "FAIL" for s in manifest["states"].values()):
        sys.exit("Row count mismatch against the API. Check manifest.json before loading.")


if __name__ == "__main__":
    main()
