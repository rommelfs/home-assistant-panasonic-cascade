"""Regression coverage for lost energy/runtime cards and reversible dashboard updates."""
from copy import deepcopy
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch
import tempfile
import unittest

import test_controls_dashboard as controls
dashboard, model = controls.dashboard, controls.model


@unittest.skipIf(model is None, 'Home Assistant required')
class DashboardUpdateTest(unittest.IsolatedAsyncioTestCase):
    def test_update_preserves_custom_graphs_and_is_idempotent(self):
        existing = {'title':'My plant', 'views':[{'path':'overview','title':'Custom overview','theme':'dark',
            'cards':[{'type':'history-graph','title':'My cycles','hours_to_show':72,'entities':['binary_sensor.pump']},
                     {'type':'entities','title':'Steuerung','entities':[{'entity':'number.old','name':'My setpoint'}]}]},
            {'path':'my-energy','cards':[{'type':'custom:energy-card','entity':'sensor.energy'}]}]}
        generated = {'title':'Panasonic','views':[{'path':'overview','title':'New overview','cards':[
            {'type':'entities','title':'Steuerung','entities':[{'entity':'number.old','name':'Changed'}, {'entity':'number.new'}]},
            {'type':'custom:panasonic-cascade-heating-curve','entities':{'water_max':'number.max'}}]},
            {'path':'energy','cards':[{'type':'history-graph','title':'Energy','entities':['sensor.kwh']}]}]}
        original = deepcopy(existing)
        updated = dashboard.merge_dashboard(existing,generated)
        self.assertEqual(existing,original)
        self.assertEqual(updated['title'],'My plant')
        self.assertEqual(updated['views'][0]['theme'],'dark')
        self.assertEqual(updated['views'][0]['cards'][0],original['views'][0]['cards'][0])
        self.assertEqual(updated['views'][0]['cards'][1]['entities'],[{'entity':'number.old','name':'My setpoint'}, {'entity':'number.new'}])
        self.assertEqual(updated['views'][1],original['views'][1])
        self.assertEqual(dashboard.merge_dashboard(updated,generated),updated)

    def test_sections_and_nested_graphs_are_preserved(self):
        existing={'views':[{'path':'energy','type':'sections','sections':[{'type':'grid','cards':[
            {'type':'vertical-stack','cards':[{'type':'history-graph','title':'Energy','hours_to_show':48,'entities':['sensor.old']}]}]}]}]}
        generated={'views':[{'path':'energy','cards':[{'type':'history-graph','title':'Energy','entities':['sensor.old','sensor.new']},
                                                     {'type':'entities','title':'Counters','entities':['sensor.new']}]}]}
        updated=dashboard.merge_dashboard(existing,generated)
        view=updated['views'][0]
        graph=view['sections'][0]['cards'][0]['cards'][0]
        self.assertEqual(graph['hours_to_show'],48)
        self.assertEqual(graph['entities'],['sensor.old','sensor.new'])
        self.assertEqual(len(view['sections']),2)
        self.assertNotIn('cards',view)
        self.assertEqual(dashboard.merge_dashboard(updated,generated),updated)

    def test_energy_and_runtime_views_survive_temporarily_missing_states(self):
        hass,registry,devices=controls.DashboardTest().fixture()
        base=registry.entities['sensor.power']
        for ident,domain,unit,label,unique,cap in [
            ('sensor.energy','sensor','kWh','Heating energy','install|energy|curVal',{'state_class':'total_increasing'}),
            ('sensor.hours','sensor','h','Compressor Total On Time','install|hours|curVal',{}),
            ('binary_sensor.running','binary_sensor',None,'Heat pump – In Betrieb','install|pump|isRunning',{}),
        ]:
            registry.entities[ident]=SimpleNamespace(**{**vars(base),'entity_id':ident,'domain':domain,
                'unit_of_measurement':unit,'original_name':label,'unique_id':unique,'capabilities':cap})
        hass.states.get.return_value=None
        with patch.object(dashboard.er,'async_get',return_value=registry),patch.object(dashboard.dr,'async_get',return_value=devices):
            config=dashboard.build_dashboard(hass)
        energy=next(v for v in config['views'] if v['path']=='energy')
        self.assertTrue(any(c['type']=='statistics-graph' and any((r if isinstance(r,str) else r['entity'])=='sensor.energy' for r in c['entities']) for c in energy['cards']))
        self.assertTrue(any(c['type']=='history-graph' and 'sensor.power' in str(c['entities']) for c in energy['cards']))
        runtime=next(v for v in config['views'] if v['path']=='runtime')
        self.assertTrue(any(c['type']=='history-graph' and c['hours_to_show']==24 and 'binary_sensor.running' in str(c['entities']) for c in runtime['cards']))
        self.assertIn('sensor.hours',str(runtime))
        # Unavailable states can exist without unit/state_class attributes.
        hass.states.get.return_value=SimpleNamespace(attributes={})
        with patch.object(dashboard.er,'async_get',return_value=registry),patch.object(dashboard.dr,'async_get',return_value=devices):
            unavailable=dashboard.build_dashboard(hass)
        self.assertEqual(unavailable,config)

    def test_electricity_consumption_has_five_periods_without_heat_output(self):
        hass,registry,devices=controls.DashboardTest().fixture()
        base=registry.entities['sensor.power']
        for ident,label in [('sensor.electricity','Heizen – Aufgenommene Energie'),('sensor.thermal','Heizen – Erzeugte Energie')]:
            registry.entities[ident]=SimpleNamespace(**{**vars(base),'entity_id':ident,'unit_of_measurement':'kWh',
                'original_name':label,'capabilities':{'state_class':'total_increasing'}})
        hass.states.get.return_value=None
        with patch.object(dashboard.er,'async_get',return_value=registry),patch.object(dashboard.dr,'async_get',return_value=devices):
            config=dashboard.build_dashboard(hass)
        energy=next(v for v in config['views'] if v['path']=='energy')
        consumption=[c for c in energy['cards'] if c.get('title','').startswith('Verbrauch von Elektrizität')]
        self.assertEqual([c['period'] for c in consumption],['hour','day','week','month','year'])
        for card in consumption:
            self.assertEqual(card['stat_types'],['change'])
            self.assertEqual([r['entity'] for r in card['entities']],['sensor.electricity'])
            self.assertNotIn('sensor.power',str(card))
            self.assertNotIn('sensor.thermal',str(card))

    def test_panel_card_is_not_replaced_or_given_invalid_siblings(self):
        original={'views':[{'path':'overview','type':'panel','cards':[{'type':'custom:my-energy-card'}]}]}
        new={'views':[{'path':'overview','cards':[{'type':'entities','entities':['sensor.test']}]}]}
        merged=dashboard.merge_dashboard(original,new)
        self.assertEqual(merged['views'][0],original['views'][0])
        self.assertEqual(merged['views'][1]['path'],'overview-cascade')
        self.assertEqual(dashboard.merge_dashboard(merged,new),merged)

    async def test_storage_backup_update_restore_and_noop(self):
        from homeassistant.core import HomeAssistant
        from homeassistant.components.lovelace.const import LOVELACE_DATA
        from homeassistant.components.lovelace.dashboard import LovelaceStorage
        from homeassistant.helpers.storage import Store
        with tempfile.TemporaryDirectory() as directory:
            hass=HomeAssistant(directory)
            target=LovelaceStorage(hass,{'id':'cascade','url_path':'cascade'})
            hass.data[LOVELACE_DATA]=SimpleNamespace(dashboards={'cascade':target})
            existing={'views':[{'path':'energy','cards':[{'type':'history-graph','title':'Custom','entities':['sensor.old']}]}]}
            generated={'views':[{'path':'overview','cards':[{'type':'markdown','content':'Curve'}]}]}
            await target.async_save(existing)
            with patch.object(dashboard,'build_dashboard',return_value=generated):
                await dashboard.populate_dashboard(hass,'cascade',update=True)
                updated=await target.async_load(False)
                self.assertIn('sensor.old',str(updated))
                store=Store(hass,1,'panasonic_cascade.dashboard_backups')
                self.assertEqual((await store.async_load())['cascade'][-1]['config'],existing)
                await dashboard.populate_dashboard(hass,'cascade',update=True)
                self.assertEqual(len((await store.async_load())['cascade']),1)
                await dashboard.restore_dashboard(hass,'cascade')
                self.assertEqual(await target.async_load(False),existing)
                self.assertEqual((await store.async_load())['cascade'][-1]['config'],updated)
            await hass.async_stop()

    async def test_backup_failure_prevents_replacement(self):
        from homeassistant.components.lovelace.const import LOVELACE_DATA
        from homeassistant.exceptions import HomeAssistantError
        target=SimpleNamespace(mode='storage',async_load=AsyncMock(return_value={'views':[{'cards':[{'type':'markdown'}]}]}),async_save=AsyncMock())
        hass=SimpleNamespace(data={LOVELACE_DATA:SimpleNamespace(dashboards={'cascade':target})})
        with patch.object(dashboard,'build_dashboard',return_value={'views':[]}),patch.object(dashboard,'save_dashboard_backup',new=AsyncMock(side_effect=OSError('disk full'))):
            with self.assertRaises(OSError):await dashboard.populate_dashboard(hass,'cascade',overwrite=True)
            target.async_save.assert_not_awaited()
            with self.assertRaises(HomeAssistantError):await dashboard.populate_dashboard(hass,'cascade',update=True,overwrite=True)

    def test_strategy_update_is_rejected(self):
        from homeassistant.exceptions import HomeAssistantError
        with self.assertRaises(HomeAssistantError):dashboard.merge_dashboard({'strategy':{'type':'original'}},{'views':[]})
