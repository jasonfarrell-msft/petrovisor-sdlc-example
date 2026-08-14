# Validation rules and audit query

Incoming production readings are normalized before they are used to assemble diagnostic context. Validation records every rule result so bad or inconsistent data is flagged for review instead of being silently dropped.

## Canonical units

The diagnostic model stores readings in these canonical units:

| Field | Canonical unit | Accepted source units | Conversion |
| --- | --- | --- | --- |
| `oil_bbl` | barrels (`bbl`) | `bbl`, `m3`, `gal` | `m3 * 6.28981077`; `gal / 42` |
| `water_bbl` | barrels (`bbl`) | `bbl`, `m3`, `gal` | `m3 * 6.28981077`; `gal / 42` |
| `gas_mcf` | thousand cubic feet (`mcf`) | `mcf`, `scf`, `m3` | `scf / 1000`; `m3 * 0.0353147` |
| `pressure_psi` | pounds per square inch (`psi`) | `psi`, `kPa`, `bar` | `kPa * 0.145037738`; `bar * 14.5037738` |
| `flow_rate_bpd` | barrels per day (`bpd`) | `bpd`, `bph`, `m3/day` | `bph * 24`; `m3/day * 6.28981077` |

Validation fails a reading with reason code `UNKNOWN_UNIT` when a source unit is not listed above (including known aliases such as `m^3`, `M³`, `gallons`, `kilopascals`, and `m3d`). Unit labels are case-insensitive and whitespace-tolerant. Normalized values are rounded to two decimal places to match the generated diagnostic context payload.

## Gap handling

Readings are expected every six hours per well. The validator sorts readings by `well_id` and timestamp, then compares each timestamp with the previous reading for the same well.

- Intervals up to 6 hours and 15 minutes are accepted.
- Intervals greater than 6 hours and 15 minutes are flagged with reason code `READING_GAP`.
- Duplicate timestamps for the same well are flagged with reason code `DUPLICATE_TIMESTAMP`.
- Gapped readings remain available to downstream processing; the audit record identifies the missing interval so operators can investigate the source feed.

## Outlier thresholds

Outliers are flagged with a reason code and retained for auditability. The validator compares each normalized reading with the previous accepted reading for the same well.

| Metric | Rule | Reason code |
| --- | --- | --- |
| `oil_bbl` | negative value or change greater than 50% | `OIL_OUTLIER` |
| `gas_mcf` | negative value or change greater than 50% | `GAS_OUTLIER` |
| `water_bbl` | negative value or change greater than 75% | `WATER_OUTLIER` |
| `pressure_psi` | value less than 0 psi, greater than 10,000 psi, or change greater than 25% | `PRESSURE_OUTLIER` |
| `flow_rate_bpd` | negative value or change greater than 50% | `FLOW_OUTLIER` |

A reading with multiple failures emits one audit row per reason code so each validation decision can be queried independently.

## Audit results

Audit rows are written to `reading_validation_audit` with one row per validation rule result.

| Column | Description |
| --- | --- |
| `audit_id` | Unique audit row identifier. |
| `well_id` | Well associated with the reading. |
| `source_reading_id` | Source-system identifier for the reading. |
| `reading_timestamp` | Timestamp from the source reading. |
| `metric_name` | Reading field that was validated, such as `oil_bbl` or `pressure_psi`. |
| `normalized_value` | Value after unit normalization. |
| `status` | `passed` or `failed`. |
| `reason_code` | Failure reason, or `null` when the rule passed. |
| `details` | Human-readable validation detail, including source unit and gap interval when applicable. |
| `validated_at` | UTC timestamp when validation ran. |

Query recent failures for a well with:

```sql
SELECT
    well_id,
    source_reading_id,
    reading_timestamp,
    metric_name,
    normalized_value,
    reason_code,
    details,
    validated_at
FROM reading_validation_audit
WHERE well_id = :well_id
  AND status = 'failed'
ORDER BY reading_timestamp DESC, metric_name, reason_code;
```

Summarize validation failures by reason code with:

```sql
SELECT
    reason_code,
    COUNT(*) AS failure_count,
    MIN(reading_timestamp) AS first_failure_at,
    MAX(reading_timestamp) AS last_failure_at
FROM reading_validation_audit
WHERE status = 'failed'
GROUP BY reason_code
ORDER BY failure_count DESC, reason_code;
```
