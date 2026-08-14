# Wells and production readings data model

This document defines the schema for well master data and production/SCADA
time-series readings that back the diagnostic context assembled in
`diagnostic_context.py` and validated in `reading_validation.py`. It covers
entities, keys, units, and the indexing strategy used to keep well-scoped
time-series queries efficient as reading volume grows.

## Entity overview

| Entity | Purpose | Cardinality |
| --- | --- | --- |
| `wells` | Well master data (identity, location, operating status). | One row per well. |
| `production_readings` | Normalized production/SCADA time-series readings. | Many rows per well, one per reporting interval. |
| `well_events` | Detected operational events (e.g. underperformance) used to anchor diagnostics. | Many rows per well. |
| `reading_validation_audit` | Validation rule outcomes for incoming readings (see `docs/validation-and-audit.md`). | Many rows per reading. |

```
wells (1) ───< (many) production_readings
wells (1) ───< (many) well_events
production_readings (1) ───< (many) reading_validation_audit
```

## `wells` (well master data)

Maps to `WellMetadata` in `diagnostic_context.py`.

| Column | Type | Description |
| --- | --- | --- |
| `well_id` | `varchar` (PK) | Unique well identifier, e.g. `WELL-101`. Business key used by all related tables. |
| `name` | `varchar` | Human-readable well name. |
| `field_name` | `varchar` | Producing field the well belongs to. |
| `basin` | `varchar` | Geologic basin (e.g. `Permian`, `Midland`, `Delaware`). |
| `asset_type` | `varchar` | Well classification, e.g. `Oil producer`, `Gas lift well`. |
| `operator` | `varchar` | Operating company. |
| `status` | `varchar` | Operating status, e.g. `active`, `monitoring`, `shut_in`. Defaults to `active`. |
| `location` | `varchar` | County/region descriptor. Defaults to `West Texas`. |

**Keys and constraints**

- Primary key: `well_id`.
- `status` should be constrained to a small enumerated set (`active`, `monitoring`, `shut_in`) at the application or check-constraint level.

**Indexing**

- Primary key index on `well_id` supports point lookups and foreign key joins from `production_readings` and `well_events`.
- A secondary index on `(basin, field_name)` supports rollup queries/dashboards grouped by geography without scanning the full table; the table itself is small (one row per well) so no partitioning is required.

## `production_readings` (production/SCADA time series)

Maps to `ProductionReading` in `diagnostic_context.py`. Values are stored in
canonical units after normalization (see `docs/validation-and-audit.md` for
the full unit conversion table).

| Column | Type | Canonical unit | Description |
| --- | --- | --- | --- |
| `well_id` | `varchar` (FK → `wells.well_id`) | — | Well the reading belongs to. |
| `timestamp` | `timestamp` (UTC) | — | Reading interval start time. Readings are expected every 6 hours per well. |
| `oil_bbl` | `numeric` | barrels (`bbl`) | Oil volume for the interval. |
| `gas_mcf` | `numeric` | thousand cubic feet (`mcf`) | Gas volume for the interval. |
| `water_bbl` | `numeric` | barrels (`bbl`) | Water volume for the interval. |
| `pressure_psi` | `numeric` | pounds per square inch (`psi`) | Wellhead/flowing pressure. |
| `flow_rate_bpd` | `numeric` | barrels per day (`bpd`) | Instantaneous flow rate. |

**Keys and constraints**

- Composite primary key: `(well_id, timestamp)`. A well cannot report two readings for the same timestamp; the validator flags such collisions with reason code `DUPLICATE_TIMESTAMP` (see `docs/validation-and-audit.md`).
- Foreign key: `well_id` references `wells.well_id`.
- All numeric measures are stored non-negative in principle; negative values are treated as outliers by the validator rather than rejected at the schema level, so the audit trail is preserved.

**Indexing strategy**

- Clustered/primary index on `(well_id, timestamp)` — the dominant access pattern is "most recent N readings for a well" (used by `ContextAssembler.assemble` for lookback windows) and "readings for a well in a timestamp range," both served directly by this composite key.
- A secondary, non-unique index on `timestamp` alone supports cross-well queries (e.g. "all readings received in the last hour" for ingestion monitoring) without scanning per-well partitions.
- For high-volume SCADA ingestion, partition the table by time (e.g. monthly range partitions on `timestamp`) so old partitions can be archived or dropped independently of the hot, recently-written data, while the `(well_id, timestamp)` index remains local to each partition.

## `well_events` (operational events)

Maps to `WellEvent` in `diagnostic_context.py`. Events anchor the lookback
window used to assemble a `DiagnosticContext`.

| Column | Type | Description |
| --- | --- | --- |
| `event_id` | `varchar` (PK) | Unique event identifier, e.g. `EVT-9001`. |
| `well_id` | `varchar` (FK → `wells.well_id`) | Well the event was raised for. |
| `event_type` | `varchar` | Event classification, e.g. `underperformance`, `normal`. |
| `severity` | `varchar` | Severity level, e.g. `low`, `high`. |
| `occurred_at` | `timestamp` (UTC) | When the event was detected. Anchors the reading lookback window. |
| `description` | `text` | Human-readable event summary. |
| `trigger_metric` | `varchar` | Reading column that triggered the event, e.g. `oil_bbl`. |
| `observed_value` | `numeric` | Value observed at detection time, in the same canonical unit as `trigger_metric`. |
| `threshold_value` | `numeric` | Threshold that was crossed to raise the event. |

**Keys and constraints**

- Primary key: `event_id`.
- Foreign key: `well_id` references `wells.well_id`.

**Indexing**

- Secondary index on `(well_id, occurred_at)` supports `ContextAssembler.assemble`'s pattern of looking up an event and then scanning `production_readings` for the same well within a bounded window ending at `occurred_at`.

## Relationship to validation audit

`reading_validation_audit` (defined in `docs/validation-and-audit.md`) records
one row per validation rule outcome for each incoming reading, keyed by
`(well_id, source_reading_id, metric_name)`-level granularity. It is
conceptually a child of `production_readings`, joined on `well_id` and
`reading_timestamp = production_readings.timestamp`, and shares the same
canonical units described above.
