from __future__ import annotations

from dataclasses import dataclass, field, asdict
from datetime import datetime, timedelta, timezone
from enum import Enum
from typing import Dict, Iterable, List, Tuple, Union


class TelemetryProfile(str, Enum):
    NORMAL = "normal"
    UNDERPERFORMING = "underperforming"
    IMMEDIATE_ACTION = "immediate_action"


@dataclass(frozen=True)
class WellMetadata:
    well_id: str
    name: str
    field_name: str
    basin: str
    asset_type: str
    operator: str
    status: str = "active"
    location: str = "West Texas"

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict) -> "WellMetadata":
        return cls(**data)


@dataclass(frozen=True)
class ProductionReading:
    well_id: str
    timestamp: datetime
    oil_bbl: float
    gas_mcf: float
    water_bbl: float
    pressure_psi: float
    flow_rate_bpd: float

    def to_dict(self) -> dict:
        return {
            "well_id": self.well_id,
            "timestamp": self.timestamp.isoformat(),
            "oil_bbl": self.oil_bbl,
            "gas_mcf": self.gas_mcf,
            "water_bbl": self.water_bbl,
            "pressure_psi": self.pressure_psi,
            "flow_rate_bpd": self.flow_rate_bpd,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "ProductionReading":
        return cls(
            well_id=data["well_id"],
            timestamp=datetime.fromisoformat(data["timestamp"]),
            oil_bbl=float(data["oil_bbl"]),
            gas_mcf=float(data["gas_mcf"]),
            water_bbl=float(data["water_bbl"]),
            pressure_psi=float(data["pressure_psi"]),
            flow_rate_bpd=float(data["flow_rate_bpd"]),
        )


@dataclass(frozen=True)
class WellEvent:
    event_id: str
    well_id: str
    event_type: str
    severity: str
    occurred_at: datetime
    description: str
    trigger_metric: str
    observed_value: float
    threshold_value: float

    def to_dict(self) -> dict:
        return {
            "event_id": self.event_id,
            "well_id": self.well_id,
            "event_type": self.event_type,
            "severity": self.severity,
            "occurred_at": self.occurred_at.isoformat(),
            "description": self.description,
            "trigger_metric": self.trigger_metric,
            "observed_value": self.observed_value,
            "threshold_value": self.threshold_value,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "WellEvent":
        return cls(
            event_id=data["event_id"],
            well_id=data["well_id"],
            event_type=data["event_type"],
            severity=data["severity"],
            occurred_at=datetime.fromisoformat(data["occurred_at"]),
            description=data["description"],
            trigger_metric=data["trigger_metric"],
            observed_value=float(data["observed_value"]),
            threshold_value=float(data["threshold_value"]),
        )


@dataclass(frozen=True)
class DiagnosticContext:
    schema_version: str = "1.0"
    event: WellEvent = field(default_factory=lambda: None)
    well: WellMetadata = field(default_factory=lambda: None)
    readings: List[ProductionReading] = field(default_factory=list)
    telemetry_profile: str = TelemetryProfile.NORMAL.value
    generated_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    def to_dict(self) -> dict:
        return {
            "schema_version": self.schema_version,
            "event": self.event.to_dict(),
            "well": self.well.to_dict(),
            "readings": [item.to_dict() for item in self.readings],
            "telemetry_profile": self.telemetry_profile,
            "generated_at": self.generated_at.isoformat(),
        }

    @classmethod
    def from_dict(cls, data: dict) -> "DiagnosticContext":
        return cls(
            schema_version=data.get("schema_version", "1.0"),
            event=WellEvent.from_dict(data["event"]),
            well=WellMetadata.from_dict(data["well"]),
            readings=[ProductionReading.from_dict(item) for item in data.get("readings", [])],
            telemetry_profile=data.get("telemetry_profile", TelemetryProfile.NORMAL.value),
            generated_at=datetime.fromisoformat(data["generated_at"]),
        )


class MissionControl:
    """Synthetic scenario controls for operational diagnostics."""

    PROFILE_FACTORS = {
        TelemetryProfile.NORMAL: {
            "oil": 1.0,
            "gas": 1.0,
            "water": 1.0,
            "pressure": 1.0,
            "flow": 1.0,
        },
        TelemetryProfile.UNDERPERFORMING: {
            "oil": 0.78,
            "gas": 0.92,
            "water": 1.22,
            "pressure": 0.86,
            "flow": 0.81,
        },
        TelemetryProfile.IMMEDIATE_ACTION: {
            "oil": 0.56,
            "gas": 0.79,
            "water": 1.7,
            "pressure": 0.62,
            "flow": 0.64,
        },
    }

    @staticmethod
    def normalize_profile(profile: Union[str, TelemetryProfile]) -> TelemetryProfile:
        if isinstance(profile, TelemetryProfile):
            return profile
        lookup = {
            "normal": TelemetryProfile.NORMAL,
            "underperforming": TelemetryProfile.UNDERPERFORMING,
            "immediate_action": TelemetryProfile.IMMEDIATE_ACTION,
            "urgent": TelemetryProfile.IMMEDIATE_ACTION,
            "critical": TelemetryProfile.IMMEDIATE_ACTION,
        }
        return lookup.get(str(profile).lower(), TelemetryProfile.NORMAL)

    @staticmethod
    def apply_profile(readings: Iterable[ProductionReading], profile: Union[str, TelemetryProfile]) -> List[ProductionReading]:
        normalized = MissionControl.normalize_profile(profile)
        factors = MissionControl.PROFILE_FACTORS[normalized]
        adjusted: List[ProductionReading] = []
        for reading in readings:
            adjusted.append(
                ProductionReading(
                    well_id=reading.well_id,
                    timestamp=reading.timestamp,
                    oil_bbl=round(reading.oil_bbl * factors["oil"], 2),
                    gas_mcf=round(reading.gas_mcf * factors["gas"], 2),
                    water_bbl=round(reading.water_bbl * factors["water"], 2),
                    pressure_psi=round(reading.pressure_psi * factors["pressure"], 2),
                    flow_rate_bpd=round(reading.flow_rate_bpd * factors["flow"], 2),
                )
            )
        return adjusted

    @staticmethod
    def scenario_summary(profile: Union[str, TelemetryProfile]) -> str:
        normalized = MissionControl.normalize_profile(profile)
        if normalized == TelemetryProfile.NORMAL:
            return "Stable production profile with expected rates and normal operating pressure."
        if normalized == TelemetryProfile.UNDERPERFORMING:
            return "Production is below expected output with elevated water cut and moderate pressure loss."
        return "Urgent profile: output is materially degraded and requires intervention to prevent equipment stress or near-term failure."


class ContextAssembler:
    def __init__(self, wells: Dict[str, WellMetadata], events: Dict[str, WellEvent], readings: Iterable[ProductionReading]):
        self.wells = wells
        self.events = events
        self.readings = list(readings)

    def assemble(
        self,
        event_id: str,
        lookback_days: int = 7,
        telemetry_profile: Union[str, TelemetryProfile, None] = None,
    ) -> DiagnosticContext:
        event = self.events.get(event_id)
        if event is None:
            raise KeyError(f"No event found for {event_id}")

        well = self.wells.get(event.well_id)
        if well is None:
            raise ValueError(f"Well {event.well_id} not found for event {event_id}")

        cutoff = event.occurred_at - timedelta(days=lookback_days)
        recent = [
            reading
            for reading in self.readings
            if reading.well_id == event.well_id and cutoff <= reading.timestamp <= event.occurred_at
        ]
        if not recent:
            raise ValueError(f"No recent readings found for well {event.well_id}")

        profile_name = MissionControl.normalize_profile(telemetry_profile or TelemetryProfile.NORMAL).value
        scoped = MissionControl.apply_profile(recent, profile_name) if telemetry_profile is not None else recent
        return DiagnosticContext(
            event=event,
            well=well,
            readings=sorted(scoped, key=lambda item: item.timestamp),
            telemetry_profile=profile_name,
        )


class SyntheticDataFactory:
    @staticmethod
    def build_wells() -> Dict[str, WellMetadata]:
        return {
            "WELL-101": WellMetadata(
                well_id="WELL-101",
                name="Apex 7",
                field_name="North Traversal",
                basin="Permian",
                asset_type="Oil producer",
                operator="Petrovisor Ops",
                status="active",
                location="Ward County",
            ),
            "WELL-202": WellMetadata(
                well_id="WELL-202",
                name="Cedar 12",
                field_name="Red Mesa",
                basin="Midland",
                asset_type="Oil producer",
                operator="Petrovisor Ops",
                status="active",
                location="Martin County",
            ),
            "WELL-303": WellMetadata(
                well_id="WELL-303",
                name="Summit 5",
                field_name="Basin Crest",
                basin="Delaware",
                asset_type="Gas lift well",
                operator="Petrovisor Ops",
                status="monitoring",
                location="Ector County",
            ),
        }

    @staticmethod
    def build_readings(well_id: str, start_time: datetime, count: int = 6) -> List[ProductionReading]:
        readings: List[ProductionReading] = []
        base_oil = 420.0 if well_id == "WELL-101" else 390.0
        base_gas = 1200.0 if well_id == "WELL-101" else 980.0
        base_water = 140.0 if well_id == "WELL-101" else 180.0
        base_pressure = 2750.0 if well_id == "WELL-101" else 2400.0
        base_flow = 610.0 if well_id == "WELL-101" else 560.0

        for idx in range(count):
            timestamp = start_time + timedelta(hours=idx * 6)
            readings.append(
                ProductionReading(
                    well_id=well_id,
                    timestamp=timestamp,
                    oil_bbl=round(base_oil * (1 - (idx * 0.03)), 2),
                    gas_mcf=round(base_gas * (1 - (idx * 0.02)), 2),
                    water_bbl=round(base_water * (1 + (idx * 0.05)), 2),
                    pressure_psi=round(base_pressure * (1 - (idx * 0.015)), 2),
                    flow_rate_bpd=round(base_flow * (1 - (idx * 0.04)), 2),
                )
            )
        return readings

    @staticmethod
    def build_event_snapshot() -> Tuple[Dict[str, WellEvent], List[ProductionReading], Dict[str, WellMetadata]]:
        wells = SyntheticDataFactory.build_wells()
        event_map = {
            "EVT-9001": WellEvent(
                event_id="EVT-9001",
                well_id="WELL-101",
                event_type="underperformance",
                severity="high",
                occurred_at=datetime(2026, 6, 15, 18, 0, tzinfo=timezone.utc),
                description="Oil output fell below expected range while water cut increased over the last 24 hours.",
                trigger_metric="oil_bbl",
                observed_value=325.0,
                threshold_value=400.0,
            ),
            "EVT-9002": WellEvent(
                event_id="EVT-9002",
                well_id="WELL-202",
                event_type="normal",
                severity="low",
                occurred_at=datetime(2026, 6, 15, 18, 0, tzinfo=timezone.utc),
                description="Well is within expected production envelope.",
                trigger_metric="flow_rate_bpd",
                observed_value=540.0,
                threshold_value=500.0,
            ),
        }

        readings: List[ProductionReading] = []
        for well_id in ["WELL-101", "WELL-202", "WELL-303"]:
            readings.extend(SyntheticDataFactory.build_readings(well_id, datetime(2026, 6, 12, 6, 0, tzinfo=timezone.utc), count=6))

        return event_map, readings, wells


if __name__ == "__main__":
    events, readings, wells = SyntheticDataFactory.build_event_snapshot()
    assembler = ContextAssembler(wells=wells, events=events, readings=readings)
    context = assembler.assemble("EVT-9001", telemetry_profile=TelemetryProfile.UNDERPERFORMING)
    print(context.to_dict())
