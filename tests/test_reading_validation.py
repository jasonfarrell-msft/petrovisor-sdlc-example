import unittest
from datetime import datetime, timedelta, timezone

from diagnostic_context import ProductionReading
from reading_validation import IncomingReading, ReadingValidator


class ReadingValidationTests(unittest.TestCase):
    def setUp(self):
        self.timestamp = datetime(2026, 6, 15, 6, 0, tzinfo=timezone.utc)
        self.units = {
            "oil_bbl": "bbl",
            "gas_mcf": "mcf",
            "water_bbl": "bbl",
            "pressure_psi": "psi",
            "flow_rate_bpd": "bpd",
        }

    def reading(self, source_reading_id, timestamp=None, **values):
        return IncomingReading(
            source_reading_id=source_reading_id,
            reading=ProductionReading(
                well_id="WELL-101",
                timestamp=timestamp or self.timestamp,
                oil_bbl=values.get("oil_bbl", 100.0),
                gas_mcf=values.get("gas_mcf", 200.0),
                water_bbl=values.get("water_bbl", 25.0),
                pressure_psi=values.get("pressure_psi", 2500.0),
                flow_rate_bpd=values.get("flow_rate_bpd", 100.0),
            ),
            units=values.get("units", self.units),
        )

    def test_normalizes_supported_source_units_to_canonical_units(self):
        validator = ReadingValidator()
        converted = validator.validate(
            [
                self.reading(
                    "source-1",
                    oil_bbl=1,
                    gas_mcf=1000,
                    water_bbl=42,
                    pressure_psi=1,
                    flow_rate_bpd=1,
                    units={
                        "oil_bbl": "m3",
                        "gas_mcf": "m3",
                        "water_bbl": "gal",
                        "pressure_psi": "bar",
                        "flow_rate_bpd": "bph",
                    },
                )
            ]
        )[0]

        self.assertEqual(converted.oil_bbl, 6.29)
        self.assertEqual(converted.gas_mcf, 35.31)
        self.assertEqual(converted.water_bbl, 1.0)
        self.assertEqual(converted.pressure_psi, 14.5)
        self.assertEqual(converted.flow_rate_bpd, 24.0)

    def test_flags_gaps_without_dropping_the_reading(self):
        validator = ReadingValidator()
        readings = validator.validate(
            [
                self.reading("source-1"),
                self.reading("source-2", self.timestamp + timedelta(hours=7)),
            ]
        )

        gaps = [
            result
            for result in validator.query_results(status="failed")
            if result.reason_code == "READING_GAP"
        ]
        self.assertEqual(len(readings), 2)
        self.assertEqual(len(gaps), 1)
        self.assertEqual(gaps[0].source_reading_id, "source-2")

    def test_flags_outliers_with_metric_reason_codes(self):
        validator = ReadingValidator()
        validator.validate(
            [
                self.reading("source-1"),
                self.reading(
                    "source-2",
                    self.timestamp + timedelta(hours=6),
                    oil_bbl=200,
                ),
                self.reading(
                    "source-3",
                    self.timestamp + timedelta(hours=12),
                    oil_bbl=200,
                ),
            ]
        )

        failures = validator.query_results(status="failed")
        self.assertEqual(
            [
                failure.reason_code
                for failure in failures
                if failure.reason_code == "OIL_OUTLIER"
            ],
            ["OIL_OUTLIER", "OIL_OUTLIER"],
        )

    def test_validation_results_are_queryable_and_auditable(self):
        validator = ReadingValidator()
        validator.validate(
            [
                self.reading("source-1"),
                self.reading(
                    "source-2",
                    self.timestamp + timedelta(hours=6),
                    oil_bbl=200,
                ),
            ]
        )

        failure = validator.query_results(well_id="WELL-101", status="failed")[0]
        self.assertTrue(failure.audit_id)
        self.assertEqual(failure.source_reading_id, "source-2")
        self.assertEqual(failure.reading_timestamp, self.timestamp + timedelta(hours=6))
        self.assertEqual(failure.metric_name, "oil_bbl")
        self.assertEqual(failure.normalized_value, 200.0)
        self.assertEqual(failure.status, "failed")
        self.assertEqual(failure.reason_code, "OIL_OUTLIER")
        self.assertTrue(failure.details)
        self.assertEqual(failure.validated_at.tzinfo, timezone.utc)


if __name__ == "__main__":
    unittest.main()
