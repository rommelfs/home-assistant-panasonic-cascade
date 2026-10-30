"""Calculation and dashboard regression checks using synthetic equipment values."""
from copy import deepcopy
import importlib
from types import SimpleNamespace
import unittest
from unittest.mock import patch
import test_controls_dashboard as controls

calculated=importlib.import_module('custom_components.panasonic_cascade.calculated')
from custom_components.panasonic_cascade.zinc import Number, Ref, MARKER

class CalculatedCOPTest(unittest.TestCase):
    def fixture(self, generation=6, consumption=2):
        def point(value,unit='kW'):
            return {'curVal':Number(value,unit),'curStatus':'ok','unit':unit}
        return {'hp':{'id':Ref('hp','HP 01 - Main'),'heatPumpModelId':'_equip:heatPump','equip':MARKER},
                'summary:unit:hp:generatedPower':point(generation),
                'summary:unit:hp:consumedPower':point(consumption)}
    def test_snapshot_ratio_units_zero_and_missing(self):
        rows=self.fixture();calculated.add_calculated_cop(rows,'site')
        self.assertEqual(rows['summary:unit:hp:calculatedCop']['curVal'].value,3)
        self.assertIsNone(rows['summary:calculatedCop']['curVal'])
        for consumption in (0,-1,float('nan')):
            rows=self.fixture(consumption=consumption);calculated.add_calculated_cop(rows,'site')
            self.assertIsNone(rows['summary:unit:hp:calculatedCop']['curVal'])
        rows=self.fixture(generation=0);calculated.add_calculated_cop(rows,'site')
        self.assertEqual(rows['summary:unit:hp:calculatedCop']['curVal'].value,0)
        rows=self.fixture();rows['summary:unit:hp:generatedPower']['curStatus']='fault'
        calculated.add_calculated_cop(rows,'site');self.assertIsNone(rows['summary:unit:hp:calculatedCop']['curVal'])
    def test_whole_heating_pair_fallback_does_not_mix_sources(self):
        rows=self.fixture();rows['summary:unit:hp:generatedPower']['curVal']=None
        for key,value,unit in [('heatModeEnergyGeneration',5000,'W'),('heatModeEnergyConsumption',1,'kW')]:
            rows[key]={'heatPumpAquareaModelId':'_point:'+key,'heatPumpRef':Ref('hp'),
                       'curVal':Number(value,unit),'unit':unit,'curStatus':'ok'}
        calculated.add_calculated_cop(rows,'site')
        self.assertEqual(rows['summary:unit:hp:calculatedCop']['curVal'].value,5)
        rows['heatModeEnergyConsumption']['curVal']=None
        calculated.add_calculated_cop(rows,'site')
        self.assertIsNone(rows['summary:unit:hp:calculatedCop']['curVal'])

class DashboardPolishTest(unittest.TestCase):
    def fixture(self):
        hass,registry,devices=controls.DashboardTest().fixture()
        base=registry.entities['sensor.power']
        def add(ident,label,unit,unique):
            registry.entities[ident]=SimpleNamespace(**{**vars(base),'entity_id':ident,'original_name':label,'unit_of_measurement':unit,'unique_id':'installation|'+unique})
        add('sensor.total_power','Consumed electrical power','kW','summary:consumedPower|curVal')
        add('sensor.wp_power','HP 01 - Main – Elektrische Leistung','kW','summary:unit:hp:consumedPower|curVal')
        add('sensor.mode_power','HP 01 - Main – Heizen – Elektrische Leistung','W','mode|curVal')
        add('sensor.outside','Floor - Site Info – Site Info – Outdoor Air Temperature','°C','outside|curVal')
        add('sensor.starts','WP 1 · Starts heute',None,'hp|starts_today')
        add('sensor.energy','WP 1 · Heizen · Aufgenommene Energie','kWh','energy|curVal')
        add('sensor.cop','WP 1 · COP aktuell',None,'summary:unit:hp:calculatedCop|curVal')
        return hass,registry,devices
    def test_short_filtered_cards_power_dedup_energy_instantaneous_and_outdoor_history(self):
        hass,registry,devices=self.fixture()
        with patch.object(controls.dashboard.er,'async_get',return_value=registry),patch.object(controls.dashboard.dr,'async_get',return_value=devices):
            config=controls.dashboard.build_dashboard(hass)
        overview=config['views'][0]
        power=next(c for c in overview['cards'] if c.get('title')=='Leistung')
        self.assertEqual(power['type'],'entity-filter')
        self.assertEqual(power['conditions'],[{'condition':'state','state_not':['unknown','unavailable']}])
        self.assertFalse(power['show_empty'])
        self.assertNotIn('sensor.mode_power',str(power))
        self.assertIn('Anlage · Strom',str(power))
        energy=next(v for v in config['views'] if v['path']=='energy')
        self.assertEqual(energy['cards'][0]['title'],'Momentanverbrauch')
        runtime=next(v for v in config['views'] if v['path']=='runtime')
        graph=next(c for c in runtime['cards'] if c.get('title')=='Leistung während des Betriebs')
        self.assertIn('sensor.outside',str(graph))
        self.assertNotIn('sensor.mode_power',str(graph))
        self.assertIn('sensor.mode_power',str(next(v for v in config['views'] if v['path']=='details')))
    def test_refresh_preserves_custom_card_and_graph_range(self):
        hass,registry,devices=self.fixture()
        with patch.object(controls.dashboard.er,'async_get',return_value=registry),patch.object(controls.dashboard.dr,'async_get',return_value=devices):
            generated=controls.dashboard.build_dashboard(hass)
        graph={'type':'history-graph','title':'Leistungsverlauf','hours_to_show':48,'entities':[{'entity':'sensor.mode_power'}]}
        custom={'type':'markdown','title':'My note','content':'Keep me'}
        old={'views':[{'path':'overview','theme':'my-theme','cards':[graph,custom]}]}
        result=controls.dashboard.refresh_generated_cards(deepcopy(old),generated,registry)
        self.assertEqual(result['views'][0]['cards'][1],custom)
        self.assertEqual(result['views'][0]['cards'][0]['hours_to_show'],48)
        self.assertNotIn('sensor.mode_power',str(result))
        self.assertEqual(controls.dashboard.refresh_generated_cards(deepcopy(result),generated,registry),result)
        custom_graph={'type':'history-graph','title':'Leistungsverlauf','hours_to_show':72,'entities':['sensor.my_solar_power']}
        mixed={'views':[{'path':'overview','cards':[deepcopy(custom_graph)]}]}
        merged=controls.dashboard.merge_dashboard(mixed,generated)
        self.assertEqual(merged['views'][0]['cards'][0],custom_graph)

class AutomaticPolishTest(unittest.IsolatedAsyncioTestCase):
    async def test_recognized_dashboard_is_backed_up_refreshed_once_and_preserves_custom_content(self):
        from unittest.mock import AsyncMock
        from homeassistant.components.lovelace.const import LOVELACE_DATA
        hass,registry,devices=DashboardPolishTest().fixture()
        base=registry.entities['sensor.starts']
        curve={key:'number.'+key for key in ('water_max','water_min','outdoor_max','outdoor_min')}
        for ident in curve.values():
            registry.entities[ident]=SimpleNamespace(**{**vars(base),'entity_id':ident,'domain':'number','unique_id':ident})
        old={'views':[{'path':'overview','theme':'keep','cards':[
            {'type':'custom:panasonic-cascade-heating-curve','entities':curve},
            {'type':'entities','title':'Leistung','entities':[{'entity':'sensor.mode_power','name':'HP 01 - Main – Heizen – Elektrische Leistung'}]},
            {'type':'markdown','title':'Custom','content':'My note'}]}]}
        target=SimpleNamespace(mode='storage',async_load=AsyncMock(return_value=old),async_save=AsyncMock())
        hass.data={LOVELACE_DATA:SimpleNamespace(dashboards={'cascade':target})}
        with patch.object(controls.dashboard.er,'async_get',return_value=registry),patch.object(controls.dashboard.dr,'async_get',return_value=devices),patch.object(controls.dashboard,'save_dashboard_backup',new=AsyncMock()) as backup:
            await controls.dashboard.async_refresh_starts_tables(hass)
            backup.assert_awaited_once_with(hass,'cascade',old)
            result=target.async_save.call_args.args[0]
            view=result['views'][0]
            self.assertEqual(view['theme'],'keep')
            self.assertEqual(view['cards'][2],old['views'][0]['cards'][2])
            self.assertEqual(view['cards'][1]['type'],'entity-filter')
            self.assertNotIn('sensor.mode_power',str(view['cards'][1]))
            target.async_load.return_value=deepcopy(result)
            target.async_save.reset_mock();backup.reset_mock()
            await controls.dashboard.async_refresh_starts_tables(hass)
            target.async_save.assert_not_awaited();backup.assert_not_awaited()
