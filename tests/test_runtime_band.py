"""Actual binary platform setup must succeed before the native on/off timeline can work."""
import importlib
from types import SimpleNamespace
from unittest.mock import Mock, patch
import unittest

import test_controls_dashboard as controls

try:
    binary = importlib.import_module('custom_components.panasonic_cascade.binary_sensor')
    zinc = importlib.import_module('custom_components.panasonic_cascade.zinc')
    from homeassistant.components.binary_sensor import BinarySensorDeviceClass
except ImportError:
    binary = None


@unittest.skipIf(binary is None, 'Home Assistant required')
class RuntimeBandTest(unittest.IsolatedAsyncioTestCase):
    async def test_real_binary_setup_with_boolean_points_and_two_heat_pumps(self):
        c = controls.coordinator(); c.entry.runtime_data = c
        # A normal Bool point previously raised NameError before any entities were added.
        c.data = {
            'command': {'id':zinc.Ref('p:demo:r:command'), 'point':zinc.MARKER, 'kind':'Bool',
                        'curVal':True, 'curStatus':'ok', 'heatPumpModelId':'_equip:heatPump_point:operation'},
            'fault': {'id':zinc.Ref('p:demo:r:fault'), 'point':zinc.MARKER, 'kind':'Bool',
                      'curVal':False, 'curStatus':'ok', 'heatPumpModelId':'_equip:heatPump_point:errorStatus'},
            'pump1': {'id':zinc.Ref('p:demo:r:hp1'), 'equip':zinc.MARKER, 'isRunning':True, 'isOn':True},
            'pump2': {'id':zinc.Ref('p:demo:r:hp2'), 'equip':zinc.MARKER, 'isRunning':False, 'isOn':True},
        }
        add = Mock()
        await binary.async_setup_entry(c.hass, c.entry, add)
        entities = {e.unique_id:e for e in add.call_args[0][0]}
        self.assertEqual(len(entities),6)
        first = entities['installation|pump1|isRunning']
        second = entities['installation|pump2|isRunning']
        self.assertIsNone(first.device_class)
        self.assertIs(first.is_on,True)
        self.assertIs(second.is_on,False)
        self.assertIs(entities['installation|fault|curVal'].device_class,BinarySensorDeviceClass.PROBLEM)
        c.data['pump1']['isRunning'] = False
        self.assertIs(first.is_on,False)
        c.data['pump2']['isRunning'] = None
        self.assertIsNone(second.is_on)

    def test_band_is_a_binary_only_native_history_timeline_using_actual_ids(self):
        hass, registry, devices = controls.DashboardTest().fixture()
        base = registry.entities['switch.zone_one']
        for index in (1,2):
            ident = f'binary_sensor.renamed_pump_{index}_running'
            registry.entities[ident] = SimpleNamespace(**{**vars(base),'entity_id':ident,'domain':'binary_sensor',
                'unique_id':f'install|hp{index}|isRunning','original_name':f'HP {index} – In Betrieb'})
        with patch.object(controls.dashboard.er,'async_get',return_value=registry),patch.object(controls.dashboard.dr,'async_get',return_value=devices):
            config = controls.dashboard.build_dashboard(hass)
        runtime = next(v for v in config['views'] if v['path']=='runtime')
        band = next(c for c in runtime['cards'] if c.get('title')=='Betriebsfreigabe – 24 Stunden')
        self.assertEqual(band['type'],'history-graph')
        self.assertEqual(band['hours_to_show'],24)
        self.assertEqual([r['entity'] for r in band['entities']],
                         ['binary_sensor.renamed_pump_1_running','binary_sensor.renamed_pump_2_running'])
        self.assertNotIn('sensor.power',str(band))
