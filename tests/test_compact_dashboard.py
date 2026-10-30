"""Readability and deliberate cleanup of redundant integration rows."""
import importlib
from types import SimpleNamespace
from unittest.mock import patch
import unittest
import test_controls_dashboard as controls

labels=importlib.import_module('cascade_test.labels')

class LabelTest(unittest.TestCase):
    def test_long_labels_are_compact_and_keep_measurement_meaning(self):
        self.assertEqual(labels.compact_label('HP 02 - Sub Unit – Kühlen/Wärmerückgewinnung – Elektrische Leistung'),
                         'WP 2 · Kühlen/WRG · el. Leistung')
        self.assertEqual(labels.compact_label('HP 01 - Main – Point Group – Compressor Total On Time'),'WP 1 · Verdichterstunden')
        self.assertEqual(labels.compact_label('HP 01 - Main – Heizen – Aufgenommene Energie'),'WP 1 · Heizen · Stromzähler')
        self.assertEqual(labels.compact_label('My personal name'),'My personal name')

@unittest.skipIf(controls.model is None,'Home Assistant required')
class CompactDashboardTest(unittest.TestCase):
    def fixture(self):
        hass,registry,devices=controls.DashboardTest().fixture()
        base=registry.entities['sensor.power']
        def add(ident,label,unit='kWh',unique=None):
            registry.entities[ident]=SimpleNamespace(**{**vars(base),'entity_id':ident,'domain':ident.split('.')[0],
                'original_name':label,'unit_of_measurement':unit,'unique_id':unique or ident,'capabilities':{'state_class':'total_increasing'}})
        add('sensor.floor_site_info_energy','Floor – Site Info – Energy Consumption – Heating')
        add('sensor.hp_energy','HP 01 - Main – Heizen – Aufgenommene Energie')
        add('sensor.hp_hours','WP 1 · Verdichterstunden','h')
        add('sensor.hp_starts','HP 01 - Main – Starts heute',None,'install|hp|starts_today')
        return hass,registry,devices
    def test_energy_placeholders_stay_in_details_but_not_energy_overview_and_daily_count_is_visible(self):
        hass,registry,devices=self.fixture()
        with patch.object(controls.dashboard.er,'async_get',return_value=registry),patch.object(controls.dashboard.dr,'async_get',return_value=devices):
            config=controls.dashboard.build_dashboard(hass)
        energy=next(v for v in config['views'] if v['path']=='energy')
        self.assertNotIn('sensor.floor_site_info_energy',str(energy))
        details=next(v for v in config['views'] if v['path']=='details')
        self.assertIn('sensor.floor_site_info_energy',str(details))
        self.assertIn('WP 1 Heizen · Strom',str(energy))
        runtime=next(v for v in config['views'] if v['path']=='runtime')
        self.assertIn('sensor.hp_starts',str(runtime))
        self.assertIn('sensor.hp_hours',str(runtime))
    def test_update_shortens_only_matching_defaults_and_cleanup_keeps_other_controls(self):
        dashboard=controls.dashboard
        old={'views':[{'path':'overview','cards':[{'type':'entities','title':'Steuerung','entities':[
            {'entity':'number.curve','name':'My curve'},{'entity':'switch.zone_one','name':'My switch'}]}]},
            {'path':'energy','cards':[{'type':'entities','title':'Energiezähler','entities':[
                {'entity':'sensor.hp_energy','name':'HP 01 - Main – Heizen – Aufgenommene Energie'},
                {'entity':'sensor.floor_site_info_energy','name':'Floor – Site Info – Energy Consumption'}]}]}]}
        new={'views':[{'path':'overview','cards':[{'type':'custom:panasonic-cascade-heating-curve','entities':{'water_max':'number.curve'}}]},
                     {'path':'energy','cards':[{'type':'entities','title':'Energiezähler','entities':[{'entity':'sensor.hp_energy','name':'WP 1 · Heizen · Stromzähler'}]}]}]}
        merged=dashboard.merge_dashboard(old,new)
        hass,registry,_=self.fixture();base=registry.entities['switch.zone_one']
        registry.entities['number.curve']=SimpleNamespace(**{**vars(base),'entity_id':'number.curve'})
        with patch.object(dashboard.er,'async_get',return_value=registry):dashboard.clean_generated_overview(merged,hass)
        self.assertEqual(merged['views'][0]['cards'][0]['entities'],[{'entity':'switch.zone_one','name':'My switch'}])
        self.assertEqual(merged['views'][1]['cards'][0]['entities'],[{'entity':'sensor.hp_energy','name':'WP 1 · Heizen · Stromzähler'}])
