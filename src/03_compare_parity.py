"""
Compare a legacy paginated report export (CSV from Report Builder) against
Power BI exports of the rebuilt report (one or more CSVs, e.g. one per territory).

Usage:
  python src/03_compare_parity.py prescribers exports/legacy_top_prescribers.csv exports/powerbi_prescribers/
  python src/03_compare_parity.py drugs       exports/legacy_top_drugs.csv       exports/powerbi_drugs/

Writes validation/parity_<report>.json and, if anything differs,
validation/parity_<report>_mismatches.csv.
"""
import json
import re
import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
OUT_DIR = ROOT / "validation"

REPORTS = {
    "prescribers": {
        "keys": ["territory_name", "npi"],
        "measures": ["total_claims", "total_drug_cost", "cost_per_claim", "drug_count"],
    },
    "drugs": {
        "keys": ["territory_name", "brand_name", "generic_name"],
        "measures": ["total_claims", "total_30day_fills", "total_drug_cost",
                     "cost_per_claim", "prescriber_count", "pct_of_territory_cost"],
    },
}
PCT_COLUMNS = {"pct_of_territory_cost"}


def normalize_name(name):
    return re.sub(r"[^a-z0-9]+", "_", str(name).strip().lower()).strip("_")


def parse_number(value):
    """Handles raw numbers and formatted ones like '$1,234.50', '(12.00)', '12.34%'."""
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return None
    s = str(value).strip()
    if s == "":
        return None
    is_pct = s.endswith("%")
    negative = s.startswith("(") and s.endswith(")")
    s = re.sub(r"[$,%()\s]", "", s)
    number = float(s)
    if negative:
        number = -number
    return number / 100 if is_pct else number


def load(paths, spec, label):
    files = []
    for p in paths:
        p = Path(p)
        files.extend(sorted(p.glob("*.csv")) if p.is_dir() else [p])
    if not files:
        sys.exit(f"No CSV files found for {label}: {paths}")

    frames = []
    for f in files:
        df = pd.read_csv(f, dtype=str, encoding="utf-8-sig", keep_default_na=False)
        df.columns = [normalize_name(c) for c in df.columns]
        if "territory_name" not in df.columns:
            # One export per territory: take the territory from the file name (arkansas.csv -> Arkansas)
            df["territory_name"] = f.stem.replace("_", " ").title()
            print(f"  {label} {f.name}: territory_name taken from file name -> {df['territory_name'].iloc[0]}")
        needed = spec["keys"] + spec["measures"]
        missing = [c for c in needed if c not in df.columns]
        if missing:
            sys.exit(
                f"{label} file {f.name} is missing columns {missing}.\n"
                f"Columns found: {list(df.columns)}\n"
                "Rename the textboxes (Report Builder) or visual fields (Power BI) to match."
            )
        frames.append(df[needed])

    df = pd.concat(frames, ignore_index=True)
    for k in spec["keys"]:
        df[k] = df[k].str.strip().str.replace(r"\.0$", "", regex=True)
    for m in spec["measures"]:
        df[m] = df[m].map(parse_number)
    return df, [f.name for f in files]


def tolerance(column, baseline_value):
    if column in PCT_COLUMNS:
        return 0.0001
    return max(0.01, abs(baseline_value or 0) * 1e-6)


def main():
    if len(sys.argv) < 4 or sys.argv[1] not in REPORTS:
        sys.exit(__doc__)
    report, legacy_path, powerbi_paths = sys.argv[1], sys.argv[2], sys.argv[3:]
    spec = REPORTS[report]

    legacy, legacy_files = load([legacy_path], spec, "Legacy")
    pbi, pbi_files = load(powerbi_paths, spec, "Power BI")

    merged = legacy.merge(pbi, on=spec["keys"], how="outer",
                          suffixes=("_legacy", "_pbi"), indicator=True)

    mismatches = []
    for _, row in merged[merged["_merge"] != "both"].iterrows():
        side = "legacy only" if row["_merge"] == "left_only" else "Power BI only"
        mismatches.append({**{k: row[k] for k in spec["keys"]}, "measure": "(row)",
                           "legacy": None, "power_bi": None, "issue": side})

    matched = merged[merged["_merge"] == "both"]
    cells_checked = cells_matched = 0
    for _, row in matched.iterrows():
        for m in spec["measures"]:
            a, b = row[f"{m}_legacy"], row[f"{m}_pbi"]
            cells_checked += 1
            same = (a is None and b is None) or (
                a is not None and b is not None and abs(a - b) <= tolerance(m, a)
            )
            if same:
                cells_matched += 1
            else:
                mismatches.append({**{k: row[k] for k in spec["keys"]}, "measure": m,
                                   "legacy": a, "power_bi": b, "issue": "value differs"})

    rows_legacy, rows_pbi, rows_matched = len(legacy), len(pbi), len(matched)
    total_checks = cells_checked + (len(merged) - rows_matched)
    total_passed = cells_matched
    summary = {
        "report": report,
        "legacy_files": legacy_files,
        "power_bi_files": pbi_files,
        "legacy_rows": rows_legacy,
        "power_bi_rows": rows_pbi,
        "rows_matched_on_keys": rows_matched,
        "value_checks": cells_checked,
        "value_checks_passed": cells_matched,
        "total_checks": total_checks,
        "match_rate_pct": round(100 * total_passed / total_checks, 2) if total_checks else 0.0,
    }

    OUT_DIR.mkdir(exist_ok=True)
    (OUT_DIR / f"parity_{report}.json").write_text(json.dumps(summary, indent=2))
    mismatch_path = OUT_DIR / f"parity_{report}_mismatches.csv"
    if mismatches:
        pd.DataFrame(mismatches).to_csv(mismatch_path, index=False)
    elif mismatch_path.exists():
        mismatch_path.unlink()

    print(json.dumps(summary, indent=2))
    if mismatches:
        print(f"\n{len(mismatches)} mismatches written to {mismatch_path}")
        sys.exit(1)
    print("\nPARITY PASS")


if __name__ == "__main__":
    main()
