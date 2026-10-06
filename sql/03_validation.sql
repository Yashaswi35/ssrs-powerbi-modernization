-- Reconciliation checks across the pipeline: API -> file -> staging -> star schema.
-- Results are appended to dw.validation_results with a new run_id.
SET NOCOUNT ON;

DECLARE @run_id INT = (SELECT ISNULL(MAX(run_id), 0) + 1 FROM dw.validation_results);

INSERT INTO dw.validation_results (run_id, check_name, expected_value, actual_value, status)
SELECT @run_id, check_name, expected_value, actual_value,
       CASE WHEN expected_value IS NULL THEN 'SKIP'
            WHEN expected_value = actual_value THEN 'PASS'
            ELSE 'FAIL' END
FROM (
    SELECT N'API rows = extracted file rows',
           CAST((SELECT SUM(rows_expected) FROM stg.source_manifest) AS DECIMAL(20,2)),
           CAST((SELECT SUM(rows_written)  FROM stg.source_manifest WHERE rows_expected IS NOT NULL) AS DECIMAL(20,2))
    UNION ALL
    SELECT N'File rows = staging rows',
           CAST((SELECT SUM(rows_written) FROM stg.source_manifest) AS DECIMAL(20,2)),
           CAST((SELECT COUNT_BIG(*) FROM stg.partd_prescriber_drug) AS DECIMAL(20,2))
    UNION ALL
    SELECT N'Staging rows = fact rows',
           CAST((SELECT COUNT_BIG(*) FROM stg.partd_prescriber_drug) AS DECIMAL(20,2)),
           CAST((SELECT COUNT_BIG(*) FROM dw.fact_prescribing) AS DECIMAL(20,2))
    UNION ALL
    SELECT N'Total claims: staging = fact',
           CAST((SELECT SUM(CAST(Tot_Clms AS BIGINT)) FROM stg.partd_prescriber_drug) AS DECIMAL(20,2)),
           CAST((SELECT SUM(CAST(total_claims AS BIGINT)) FROM dw.fact_prescribing) AS DECIMAL(20,2))
    UNION ALL
    SELECT N'Total drug cost: staging = fact',
           (SELECT SUM(Tot_Drug_Cst) FROM stg.partd_prescriber_drug),
           (SELECT SUM(total_drug_cost) FROM dw.fact_prescribing)
    UNION ALL
    SELECT N'Distinct NPIs: staging = dim_prescriber',
           CAST((SELECT COUNT(DISTINCT Prscrbr_NPI) FROM stg.partd_prescriber_drug) AS DECIMAL(20,2)),
           CAST((SELECT COUNT(*) FROM dw.dim_prescriber) AS DECIMAL(20,2))
    UNION ALL
    SELECT N'Staging rows with unmapped state (expect 0)',
           CAST(0 AS DECIMAL(20,2)),
           CAST((SELECT COUNT_BIG(*) FROM stg.partd_prescriber_drug s
                 WHERE NOT EXISTS (SELECT 1 FROM stg.territory_map m
                                   WHERE m.state_abbr = s.Prscrbr_State_Abrvtn)) AS DECIMAL(20,2))
    UNION ALL
    SELECT N'Duplicate rows at fact grain (expect 0)',
           CAST(0 AS DECIMAL(20,2)),
           CAST((SELECT COUNT(*) FROM (
                    SELECT data_year, prescriber_key, drug_key
                    FROM dw.fact_prescribing
                    GROUP BY data_year, prescriber_key, drug_key
                    HAVING COUNT(*) > 1) x) AS DECIMAL(20,2))
) AS checks(check_name, expected_value, actual_value);
GO
