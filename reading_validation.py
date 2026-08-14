from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Dict, Iterable, List, Mapping, Optional, Tuple
from uuid import uuid4

from diagnostic_context import ProductionReading


@dataclass(frozen=True)
class IncomingReading:
    source_reading_id: str
    reading: ProductionReading
    units: Mapping[str, str]


@dataclass(frozen=True)
class ValidationResult:
    audit_id: str
    well_id: str
    source_reading_id: str
    reading_timestamp: datetime
    metric_name: str
    normalized_value: float
    status: str
    reason_code: Optional[str]
    details: str
    validated_at: datetime


class ReadingValidator:
    UNIT_CONVERSIONS = {
        "oil_bbl": {"bbl": 1.0, "m3": 6.28981077, "gal": 1 / 42},
        "gas_mcf": {"mcf": 1.0, "scf": 1 / 1000, "m3": 0.0353147},
        "water_bbl": {"bbl": 1.0, "m3": 6.28981077, "gal": 1 / 42},
        "pressure_psi": {"psi": 1.0, "kpa": 0.145037738, "bar": 14.5037738},
        "flow_rate_bpd": {"bpd": 1.0, "bph": 24.0, "m3/day": 6.28981077},
    }
    UNIT_ALIASES = {
        "oil_bbl": {"barrel": "bbl", "barrels": "bbl", "m^3": "m3"},
        "gas_mcf": {"mscf": "mcf", "m^3": "m3"},
        "water_bbl": {"barrel": "bbl", "barrels": "bbl", "gallon": "gal", "gallons": "gal", "m^3": "m3"},
        "pressure_psi": {"kilopascal": "kpa", "kilopascals": "kpa"},
        "flow_rate_bpd": {"bbl/day": "bpd", "bbl/hr": "bph", "m3d": "m3/day", "m^3/day": "m3/day"},
    }
    OUTLIER_RULES = {
        "oil_bbl": (0.5, "OIL_OUTLIER"),
        "gas_mcf": (0.5, "GAS_OUTLIER"),
        "water_bbl": (0.75, "WATER_OUTLIER"),
        "flow_rate_bpd": (0.5, "FLOW_OUTLIER"),
    }
    EXPECTED_INTERVAL = timedelta(hours=6, minutes=15)

    def __init__(self) -> None:
        self._results: List[ValidationResult] = []

    def validate(self, readings: Iterable[IncomingReading]) -> List[ProductionReading]:
        normalized_readings: List[ProductionReading] = []
        previous_by_well: Dict[str, ProductionReading] = {}

        for incoming in sorted(
            readings, key=lambda item: (item.reading.well_id, item.reading.timestamp)
        ):
            normalized, valid_units = self._normalize(incoming)
            normalized_readings.append(normalized)
            previous = previous_by_well.get(normalized.well_id)

            if previous is not None:
                interval = normalized.timestamp - previous.timestamp
                self._record(
                    incoming,
                    "timestamp",
                    interval.total_seconds() / 3600,
                    interval <= self.EXPECTED_INTERVAL,
                    None if interval <= self.EXPECTED_INTERVAL else "READING_GAP",
                    f"Interval since the previous reading is {interval}.",
                )
                if valid_units:
                    valid_units = self._validate_outliers(incoming, normalized, previous)

            if valid_units:
                previous_by_well[normalized.well_id] = normalized

        return normalized_readings

    def query_results(
        self, well_id: Optional[str] = None, status: Optional[str] = None
    ) -> Tuple[ValidationResult, ...]:
        return tuple(
            result
            for result in self._results
            if (well_id is None or result.well_id == well_id)
            and (status is None or result.status == status)
        )

    def _normalize(self, incoming: IncomingReading) -> Tuple[ProductionReading, bool]:
        values = {}
        valid_units = True
        for metric, conversions in self.UNIT_CONVERSIONS.items():
            value = getattr(incoming.reading, metric)
            unit = self._normalize_unit(metric, incoming.units.get(metric))
            factor = conversions.get(unit)
            if factor is None:
                valid_units = False
                values[metric] = value
                self._record(
                    incoming,
                    metric,
                    value,
                    False,
                    "UNKNOWN_UNIT",
                    f"Unsupported unit {unit or '<missing>'!r}.",
                )
            else:
                values[metric] = round(value * factor, 2)
                self._record(
                    incoming,
                    metric,
                    values[metric],
                    True,
                    None,
                    f"Normalized from {unit}.",
                )
        return (
            ProductionReading(
                well_id=incoming.reading.well_id,
                timestamp=incoming.reading.timestamp,
                **values,
            ),
            valid_units,
        )

    def _normalize_unit(self, metric: str, unit: object) -> str:
        normalized = str(unit).strip().lower().replace(" ", "") if unit is not None else ""
        normalized = normalized.replace("³", "3")
        return self.UNIT_ALIASES.get(metric, {}).get(normalized, normalized)

    def _validate_outliers(
        self,
        incoming: IncomingReading,
        reading: ProductionReading,
        previous: ProductionReading,
    ) -> bool:
        accepted = True
        for metric, (threshold, reason_code) in self.OUTLIER_RULES.items():
            value = getattr(reading, metric)
            previous_value = getattr(previous, metric)
            change = abs(value - previous_value) / previous_value if previous_value else float("inf")
            failed = value < 0 or change > threshold
            accepted = accepted and not failed
            self._record(
                incoming,
                metric,
                value,
                not failed,
                reason_code if failed else None,
                f"Change from previous accepted reading is {change:.0%}.",
            )

        pressure = reading.pressure_psi
        previous_pressure = previous.pressure_psi
        change = (
            abs(pressure - previous_pressure) / previous_pressure
            if previous_pressure
            else float("inf")
        )
        failed = pressure < 0 or pressure > 10000 or change > 0.25
        accepted = accepted and not failed
        self._record(
            incoming,
            "pressure_psi",
            pressure,
            not failed,
            "PRESSURE_OUTLIER" if failed else None,
            f"Change from previous accepted reading is {change:.0%}.",
        )
        return accepted

    def _record(
        self,
        incoming: IncomingReading,
        metric_name: str,
        normalized_value: float,
        passed: bool,
        reason_code: Optional[str],
        details: str,
    ) -> None:
        reading = incoming.reading
        self._results.append(
            ValidationResult(
                audit_id=str(uuid4()),
                well_id=reading.well_id,
                source_reading_id=incoming.source_reading_id,
                reading_timestamp=reading.timestamp,
                metric_name=metric_name,
                normalized_value=normalized_value,
                status="passed" if passed else "failed",
                reason_code=reason_code,
                details=details,
                validated_at=datetime.now(timezone.utc),
            )
        )
