# Build guide (one-day plan)

## Timeline

| Time | Mac (Terminal) | Windows (Parallels) |
|---|---|---|
| 0:00 | `01_extract_cms.py`, then `02_load_and_build.py` | Install Parallels trial and Windows 11, run Windows Update until clean |
| 1:00 | Push to GitHub | Install Power BI Desktop and Power BI Report Builder |
| 1:15 | | **Part A**: 2 legacy paginated reports and CSV exports |
| 2:30 | | **Part B**: Power BI model, measures, 2 report pages |
| 3:45 | | **Part C**: RLS and testing with View as |
| 4:15 | `03_compare_parity.py`, fix any mismatches | **Part D**: Power BI exports |
| 4:45 | Screenshots, README results, final push | |

Do the extract and Windows setup in parallel. They are the two slowest steps.

Folder layout to create in the repo:
```
reports/legacy/        top_prescribers.rdl, top_drugs.rdl
reports/powerbi/       Part D Modernization (.pbip or .pbix)
exports/               legacy_top_prescribers.csv, legacy_top_drugs.csv
exports/powerbi_prescribers/   one CSV per territory
exports/powerbi_drugs/         one CSV per territory
validation/            parity results (written by the script)
screenshots/
```

---

## Part A: Legacy paginated reports (Power BI Report Builder)

These play the role of the existing SSRS reports. Report Builder saves the same `.rdl` format SSRS uses.

**Data source** (both reports)
- New, then Blank Report. In Report Data, add a Data Source with the type **Microsoft Azure SQL Database**.
- Connection string: `Data Source=YOURSERVER.database.windows.net;Initial Catalog=YOURDATABASE`
- Under Credentials, choose "Use this user name and password" and enter your SQL login.

**Territory parameter** (both reports)
- Dataset `dsTerritories`: `SELECT territory_name FROM dw.dim_territory ORDER BY territory_name;`
- Add a parameter `Territory`, check **Allow multiple values**, set available values and default values to `dsTerritories`.

**Report 1: Top Prescribers by Drug Cost**
- Dataset `dsTopPrescribers`:
  ```sql
  SELECT territory_name, cost_rank, npi, prescriber_name, specialty, city,
         total_claims, total_drug_cost, cost_per_claim, drug_count
  FROM dw.vw_rpt_top_prescribers
  WHERE territory_name IN (@Territory)
  ORDER BY territory_name, cost_rank;
  ```
- Insert a Table and **drag each field into its own column**. Dragging names each textbox after its field, and the CSV export uses those names as headers, which is what the parity check needs.
- Page break per territory: in Row Groups, on Details, choose Add Group, then Parent Group, grouped by `territory_name`. Then delete the new group column with "Delete columns only" and keep the group. Under Group Properties, then Page Breaks, set "Between each instance of a group".
- Put the title in the **page header**, not the body, so it stays out of the CSV export. Example: "Top 50 Prescribers by Drug Cost, 2024".
- Formats: `C2` for cost columns, `N0` for counts.
- Save as `reports/legacy/top_prescribers.rdl`. Run it with all territories, then Export, then **CSV (comma delimited)**, saving to `exports/legacy_top_prescribers.csv`.

**Report 2: Top Drugs by Territory**
- Dataset `dsTopDrugs`:
  ```sql
  SELECT territory_name, cost_rank, brand_name, generic_name, total_claims,
         total_30day_fills, total_drug_cost, cost_per_claim, prescriber_count,
         pct_of_territory_cost
  FROM dw.vw_rpt_top_drugs
  WHERE territory_name IN (@Territory)
  ORDER BY territory_name, cost_rank;
  ```
- Same table, group, and header steps as Report 1. Format `pct_of_territory_cost` as `P2`.
- Save as `reports/legacy/top_drugs.rdl` and export to `exports/legacy_top_drugs.csv`.

Take a screenshot of each report in preview.

---

## Part B: Power BI model and report

**Load**
- Get Data, then **Azure SQL database**, enter the server and database, choose **Import**, and use **Database** credentials with your SQL login.
- Select `dw.fact_prescribing`, `dw.dim_prescriber`, `dw.dim_drug`, `dw.dim_territory`, and `dw.security_territory_access`.
- **Do not load the `vw_rpt_` views.** Power BI has to compute the numbers independently, or the parity check proves nothing.
- Rename each table to drop the `dw ` prefix, so `dw fact_prescribing` becomes `fact_prescribing`.

**Relationships** (Model view): many-to-one, single direction
- `fact_prescribing[prescriber_key]` to `dim_prescriber[prescriber_key]`
- `fact_prescribing[drug_key]` to `dim_drug[drug_key]`
- `fact_prescribing[territory_key]` to `dim_territory[territory_key]`
- Delete any auto-detected relationship between `dim_prescriber` and `dim_territory`, and any relationship touching `security_territory_access`.
- Hide all `_key` columns and the `security_territory_access` table.

**Measures** (put them on `fact_prescribing`)
```dax
Total Claims = SUM ( fact_prescribing[total_claims] )

Total 30day Fills = SUM ( fact_prescribing[total_30day_fills] )

Total Drug Cost = SUM ( fact_prescribing[total_drug_cost] )

Cost per Claim = ROUND ( DIVIDE ( [Total Drug Cost], [Total Claims] ), 2 )

Drug Count = DISTINCTCOUNT ( fact_prescribing[drug_key] )

Prescriber Count = DISTINCTCOUNT ( fact_prescribing[prescriber_key] )

Pct of Territory Cost =
ROUND (
    DIVIDE ( [Total Drug Cost], CALCULATE ( [Total Drug Cost], REMOVEFILTERS ( dim_drug ) ) ),
    4
)
```

**Page 1: Top Prescribers**
- Territory slicer (`dim_territory[territory_name]`), set to single select.
- Cards: Total Drug Cost, Total Claims, Prescriber Count.
- Table with `territory_name`, `npi`, `prescriber_name`, `specialty`, `city`, Total Claims, Total Drug Cost, Cost per Claim, Drug Count.
- Visual filter on `npi`: **Top N, Show items: Top 50, By value: Total Drug Cost**.
- Bar chart: Total Drug Cost by `specialty` (top 10).

**Page 2: Top Drugs**
- The same territory slicer. In View, then Sync slicers, sync it across both pages.
- Table with `territory_name`, `brand_name`, `generic_name`, Total Claims, Total 30day Fills, Total Drug Cost, Cost per Claim, Prescriber Count, Pct of Territory Cost.
- Visual filter on `generic_name`: **Top N 25 by Total Drug Cost**.
- Bar chart: top 10 drugs by Total Drug Cost.

The interactive pages, KPI cards, and charts are the "modernization" story. The paginated originals are static tables.

---

## Part C: Dynamic row-level security

Modeling, then **Manage roles**, then create a role named `Territory Access` with these table filters:

| Table | DAX filter |
|---|---|
| `dim_territory` | `[territory_key] IN CALCULATETABLE ( VALUES ( security_territory_access[territory_key] ), security_territory_access[user_principal] = USERPRINCIPALNAME () )` |
| `dim_prescriber` | the same expression as above |
| `security_territory_access` | `[user_principal] = USERPRINCIPALNAME ()` |

**Test** with Modeling, then **View as**: check **Other user**, enter `texas.rep@demo.local`, and check `Territory Access`.
- Only Texas should appear. Screenshot it.
- Repeat with `oklahoma.rep@demo.local`, then `region.manager@demo.local`, who should see all 4 territories. Screenshot both.
- Stop viewing as the role before exporting.

Demo users follow the pattern `<territory>.rep@demo.local`. The access table is `dw.security_territory_access`.

---

## Part D: Power BI exports and parity check

For **each territory**, select it in the slicer, then on the table visual click **More options**, then **Export data** (summarized, CSV):
- Page 1 exports go to `exports/powerbi_prescribers/<territory>.csv`
- Page 2 exports go to `exports/powerbi_drugs/<territory>.csv`

Then, on the Mac:
```bash
python src/03_compare_parity.py prescribers exports/legacy_top_prescribers.csv exports/powerbi_prescribers/
python src/03_compare_parity.py drugs exports/legacy_top_drugs.csv exports/powerbi_drugs/
```
The script accepts formatted values (`$1,234.50`, `4.12%`) and column names with spaces or different capitalization. If a column is missing, it prints the columns it found. Rename that field in the visual and export again. Mismatches go to `validation/parity_<report>_mismatches.csv`.

**Save the Power BI file** as a Power BI Project (`.pbip`) if your version offers it, since it's text-based and diffs cleanly on GitHub. Otherwise save a `.pbix`, but GitHub rejects files over 100 MB.
