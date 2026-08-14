import unittest
from datetime import datetime, timezone

from diagnostic_context import (
    ContextAssembler,
    DiagnosticContext,
    MissionControl,
    SyntheticDataFactory,
    TelemetryProfile,
    WellEvent,
)


class DiagnosticContextTests(unittest.TestCase):
    def setUp(self):
        self.events, self.readings, self.wells = SyntheticDataFactory.build_event_snapshot()
        self.assembler = ContextAssembler(self.wells, self.events, self.readings)

    def test_assemble_context_includes_only_target_well_data(self):
        context = self.assembler.assemble("EVT-9001", lookback_days=7)

        self.assertEqual(context.event.well_id, "WELL-101")
        self.assertEqual(context.well.well_id, "WELL-101")
        self.assertTrue(context.readings)
        self.assertTrue(all(reading.well_id == "WELL-101" for reading in context.readings))
        self.assertNotIn("WELL-202", {reading.well_id for reading in context.readings})
        self.assertNotIn("WELL-303", {reading.well_id for reading in context.readings})

    def test_mission_control_profiles_are_distinct_and_realistic(self):
        base = self.readings[:2]
        normal = MissionControl.apply_profile(base, TelemetryProfile.NORMAL)
        underperforming = MissionControl.apply_profile(base, TelemetryProfile.UNDERPERFORMING)
        urgent = MissionControl.apply_profile(base, TelemetryProfile.IMMEDIATE_ACTION)

        self.assertAlmostEqual(normal[0].oil_bbl, base[0].oil_bbl)
        self.assertLess(underperforming[0].oil_bbl, base[0].oil_bbl)
        self.assertLess(urgent[0].oil_bbl, underperforming[0].oil_bbl)
        self.assertGreater(urgent[0].water_bbl, underperforming[0].water_bbl)
        self.assertIn("Urgent profile", MissionControl.scenario_summary(TelemetryProfile.IMMEDIATE_ACTION))

    def test_context_round_trip_schema(self):
        context = self.assembler.assemble("EVT-9001", telemetry_profile=TelemetryProfile.UNDERPERFORMING)
        payload = context.to_dict()
        restored = DiagnosticContext.from_dict(payload)

        self.assertEqual(restored.schema_version, "1.0")
        self.assertEqual(restored.event.event_id, "EVT-9001")
        self.assertEqual(restored.well.well_id, "WELL-101")
        self.assertEqual(restored.telemetry_profile, "underperforming")
        self.assertEqual(len(restored.readings), len(context.readings))

    def test_assembler_rejects_missing_or_mismatched_data(self):
        with self.assertRaises(KeyError):
            self.assembler.assemble("MISSING")

        bad_events = {
            "EVT-9999": WellEvent(
                event_id="EVT-9999",
                well_id="WELL-999",
                event_type="underperformance",
                severity="high",
                occurred_at=datetime(2026, 6, 15, 18, 0, tzinfo=timezone.utc),
                description="Missing well should fail hard.",
                trigger_metric="oil_bbl",
                observed_value=220.0,
                threshold_value=300.0,
            )
        }
        with self.assertRaises(ValueError):
            ContextAssembler(self.wells, bad_events, self.readings).assemble("EVT-9999")


if __name__ == "__main__":
    unittest.main()
