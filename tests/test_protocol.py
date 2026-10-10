"""Protocol tests without a Home Assistant installation."""
import importlib
from pathlib import Path
import sys
import types
import unittest

ROOT = Path(__file__).resolve().parents[1]
PACKAGE = "cascade_test"
pkg = types.ModuleType(PACKAGE)
pkg.__path__ = [str(ROOT / "custom_components/panasonic_cascade")]
sys.modules[PACKAGE] = pkg
zinc = importlib.import_module(PACKAGE + ".zinc")
model = importlib.import_module(PACKAGE + ".model")


class ProtocolTest(unittest.TestCase):
    def test_refs_escaped_strings_and_sparse_rows(self):
        grid = 'ver:"3.0"\nid,curVal,unit,actions\n@p:demo:r:a "Zone, 1",31°C,"°C","pointSetDef(\\$self, \\$val)"\n@p:demo:r:b,N,,""\n'
        rows = zinc.parse_grids(grid)[0]
        self.assertEqual(rows[0]["id"], zinc.Ref("p:demo:r:a", "Zone, 1"))
        self.assertEqual(rows[0]["curVal"], zinc.Number(31, "°C"))
        self.assertEqual(rows[0]["actions"], "pointSetDef($self, $val)")
        self.assertIsNone(rows[1]["curVal"])
        self.assertIsNone(rows[1]["unit"])

    def test_multiple_grids_and_error_grid(self):
        self.assertEqual(len(zinc.parse_grids('ver:"3.0"\nval\nT\n\nver:"3.0"\nval\n2\n')), 2)
        with self.assertRaises(zinc.ZincError):
            zinc.parse_grids('ver:"3.0" err dis:"hidden server details"\nempty\n')

    def test_non_finite_and_timestamps(self):
        for token in ("INF", "-INF", "NaN", "NA"):
            self.assertIsNone(zinc.scalar(token))
        self.assertEqual(zinc.scalar("2026-10-10T12:40:00+02:00 Berlin"), "2026-10-10T12:40:00+02:00 Berlin")
        self.assertEqual(zinc.scalar("10_000kWh"), zinc.Number(10000, "kWh"))
        self.assertEqual(zinc.scalar("1e-3kW"), zinc.Number(.001, "kW"))
        self.assertEqual(zinc.scalar("2026-10-10"), "2026-10-10")
        self.assertIsNone(zinc.scalar("1e999kW"))

    def test_nested_cells_do_not_split_at_inner_commas(self):
        self.assertEqual(zinc.split_cells('[1,2],{a:1,b:2},"x,y"'), ['[1,2]', '{a:1,b:2}', '"x,y"'])
        with self.assertRaises(zinc.ZincError):
            zinc.parse_grids('ver:"3.0"\na,b\n1\n')

    def test_multiline_nested_schedule_grid(self):
        text = 'ver:"3.0"\nid,schedule,curVal\n@a,<<ver:"3.0"\nday,val\n"Mon",T\n>>,F\n\nver:"3.0"\nval\n31°C\n'
        grids = zinc.parse_grids(text)
        self.assertEqual(len(grids), 2)
        self.assertIn('"Mon",T', grids[0][0]["schedule"])
        self.assertIs(grids[0][0]["curVal"], False)

    def test_state_quality(self):
        self.assertEqual(model.state({"curVal": zinc.Number(-78, "°C"), "curStatus": "ok"}), -78)
        self.assertIsNone(model.state({"curVal": zinc.Number(31, "°C"), "curStatus": "fault"}))
        self.assertIsNone(model.state({"curVal": None}))

    def test_control_allowlist_and_bounds(self):
        point = {"writable": zinc.MARKER, "kind": "Number", "unit": "°C", "actions": "pointSetDef($self,$val)", "bufferModelId": "_equip:buffer_point:zone1WaterTemperatureHotSetpoint", "minVal": zinc.Number(25, "°C"), "maxVal": zinc.Number(50, "°C")}
        self.assertEqual(model.control_kind(point), "number")
        self.assertEqual(model.bounds(point), (25, 50))
        point["bacnetServerReadOnly"] = zinc.MARKER
        self.assertIsNone(model.control_kind(point))
        self.assertIsNone(model.control_kind({"writable": zinc.MARKER, "kind": "Bool", "actions": "pointSetDef($self,$val)", "tankModelId": "_equip:tank_point:sterilizationRequest"}))
        self.assertEqual(model.enum_options({"enum": ", Off, On"}), ["Off", "On"])

    def test_quote_roundtrip_and_injection_stays_in_string(self):
        original = 'Heat "zone"; pointEmergencyOverride($self,true)\n'
        self.assertEqual(zinc.unquote(zinc.quote(original)), original)
        self.assertEqual(zinc.split_cells(zinc.quote(original)), [zinc.quote(original)])


if __name__ == "__main__":
    unittest.main()
