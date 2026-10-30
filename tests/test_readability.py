"""Context labels, display-only precision, and honest compressor status presentation."""
import importlib
import tempfile
import unittest
from unittest.mock import patch
import test_controls_dashboard as controls
from homeassistant.core import HomeAssistant
from homeassistant.helpers.template import Template
from custom_components.panasonic_cascade.labels import display_label
from custom_components.panasonic_cascade.sensor import CascadeSensor
from custom_components.panasonic_cascade.zinc import Ref, Number, MARKER

class ReadabilityTest(unittest.TestCase):
    def test_context_replaces_paths_without_removing_measurement_identity(self):
        self.assertEqual(display_label('HP 02 - Sub Unit – Point Group – Water Temperature - Outlet','WP 2'),'Vorlauf')
        self.assertEqual(display_label('HP 01 - Main – Heizen – Aufgenommene Energie'),'WP 1 Heizen · Strom')
        self.assertEqual(display_label('Zone 1 – Heizkurve – Max. Außentemperatur – Standardwert','Zone 1 · Heizkurve'),'Außen max.')
        self.assertEqual(display_label('a - b - c - d','a · b · c'),'c · d')
        self.assertEqual(display_label('My personal name'),'My personal name')
    def test_precision_affects_display_but_retains_raw_values(self):
        for unit,precision in [('kW',2),('W',0),('kWh',1),('°C',1),('h',0),('',2)]:
            c=controls.coordinator()
            c.data={'p':{'id':Ref('p','Measurement'),'point':MARKER,'kind':'Number',
                         'unit':unit,'curVal':Number(1.234567,unit),'curStatus':'ok'}}
            entity=CascadeSensor(c,'p')
            self.assertEqual(entity.suggested_display_precision,precision)
            self.assertEqual(entity.native_value,1.234567)
    def test_advanced_controls_move_out_of_overview_and_details_are_read_only(self):
        hass,registry,devices=controls.DashboardTest().fixture()
        with patch.object(controls.dashboard.er,'async_get',return_value=registry),patch.object(controls.dashboard.dr,'async_get',return_value=devices):
            config=controls.dashboard.build_dashboard(hass)
        details=next(v for v in config['views'] if v['path']=='details')
        self.assertNotIn('switch.zone_one',str(details))
        self.assertIn('switch.zone_one',str(next(v for v in config['views'] if v['path']=='settings')))

class MissingCompressorTest(unittest.IsolatedAsyncioTestCase):
    async def test_absent_verified_signal_shows_explanation_without_a_fake_zero_table(self):
        with tempfile.TemporaryDirectory() as directory:
            hass=HomeAssistant(directory)
            hass.states.async_set('sensor.starts','unavailable',{'daily_starts':[]})
            config=controls.dashboard.starts_table([{'entity':'sensor.starts'}])
            text=Template(config['content'],hass).async_render(parse_result=False)
            self.assertIn('keinen bestätigten Verdichterstatus',text)
            self.assertIn('Keine Schätzung aus der Leistung',text)
            self.assertNotIn('| Heute |',text)
            await hass.async_stop()
