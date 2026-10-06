# SSRS to Power BI Modernization: CMS Medicare Part D

Migrates legacy SSRS paginated reports to Power BI on a validated Azure SQL star schema built from CMS Medicare Part D prescriber data (2024 release), with territory-level row-level security.

> Work in progress. See BUILD_GUIDE.md for the report build, RLS, and parity steps.

## Architecture

```
data.cms.gov API ──► src/01_extract_cms.py ──► data/raw/*.csv + manifest.json
                                                    │
                                                    ▼
                          src/02_load_and_build.py (Azure SQL Database)
                          stg.partd_prescriber_drug ──► dw star schema ──► dw.validation_results
                                                                │
                                         ┌──────────────────────┴───────────────────┐
                                         ▼                                          ▼
                          Legacy paginated reports (.rdl)            Power BI reports + territory RLS
```

**Scope:** 2024 Part D Prescribers by Provider and Drug, for 4 states (TX, OK, AR, LA) grouped into a demo "South Central" region. Each state is treated as one territory. Territories are defined in `config/territory_map.csv`, not taken from CMS.

**Star schema**
- `dw.fact_prescribing`: one row per prescriber, drug, and year (claims, 30-day fills, day supply, drug cost, beneficiaries, 65+ measures)
- `dw.dim_prescriber`: NPI, name, city, specialty, territory
- `dw.dim_drug`: brand and generic name
- `dw.dim_territory`: state, territory, region

## Phase 1 setup (macOS)

**1. ODBC driver and Python environment**
```bash
brew tap microsoft/mssql-release https://github.com/Microsoft/homebrew-mssql-release
brew update
HOMEBREW_ACCEPT_EULA=Y brew install msodbcsql18 mssql-tools18
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
```

**2. Azure SQL Database (free offer)** in the Azure portal:
- Create a SQL Database and apply the free offer when the portal shows it.
- Set the behavior when the free limit is reached to **Auto-pause** so it never bills.
- Choose **SQL authentication** and note the admin user and password.
- Under Networking, enable the public endpoint and **add your current client IP**.

**3. Credentials**
```bash
cp .env.example .env   # then fill in server, database, user, password
```

## Run

```bash
python src/01_extract_cms.py      # ~10–20 min, writes data/raw/
python src/02_load_and_build.py   # loads staging, builds star schema, runs checks, creates report views + RLS table
# Already loaded? Rebuild only the reporting layer:
python src/02_load_and_build.py --reporting-only
```

## Validation

`sql/03_validation.sql` reconciles every hop and logs results to `dw.validation_results`:

| Check | Rule |
|---|---|
| API rows = extracted file rows | Row count reported by the CMS API matches rows written |
| File rows = staging rows | Nothing dropped on load |
| Staging rows = fact rows | Nothing dropped by dimension joins |
| Total claims, total drug cost | Sums match between staging and fact |
| Distinct NPIs = dim_prescriber rows | One dimension row per prescriber |
| Unmapped states, duplicate fact grain | Both must be 0 |

**Data notes:** CMS excludes rows with fewer than 11 claims and suppresses beneficiary counts below 11, so `total_beneficiaries` is NULL for those rows and should not be summed as a complete count.
