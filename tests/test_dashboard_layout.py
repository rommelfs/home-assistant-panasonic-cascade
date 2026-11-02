"""Compact overview, lossless period navigation, native templates and migrations."""
import unittest
from copy import deepcopy
from types import SimpleNamespace
from unittest.mock import patch
import test_dashboard_polish as fixtures
from custom_components.panasonic_cascade import dashboard
from custom_components.panasonic_cascade.dashboard_layout import organise_dashboard, bind_dashboard_paths, cards, MARKER


class LayoutTest(unittest.IsolatedAsyncioTestCase):
    def fixture(self):
        hass, registry, devices = fixtures.DashboardPolishTest().fixture()
        base=registry.entities['sensor.wp_power']
        def add(ident, suffix, domain='sensor', unit=None):
            registry.entities[ident]=SimpleNamespace(**{**vars(base),'entity_id':ident,'domain':domain,
                'unique_id':'install|'+suffix,'original_name':ident,'unit_of_measurement':unit})
        add('sensor.total_power','summary:consumedPower|curVal',unit='kW')
        add('sensor.charge','pv_buffer_charge')
        add('binary_sensor.charge','pv_buffer_charge_active','binary_sensor')
        add('binary_sensor.wp1','wp1|power_running','binary_sensor')
        add('binary_sensor.wp2','wp2|power_running','binary_sensor')
        add('sensor.alarms','summary:activeAlarms|curVal')
        for source in ('pv','grid','battery'):
            for period in ('power','day','week','month','year','total'):
                add(f'sensor.{source}_{period}',f'energy_source:{source}:{period}',unit='W' if period=='power' else 'kWh')
        entry=hass.config_entries.async_entries.return_value[0]
        entry.title='Reference';entry.unique_id='install';entry.options={'pv_charge_enabled':True}
        entry.runtime_data=SimpleNamespace(data={},buffer_charge=SimpleNamespace(lease=None))
        with patch.object(dashboard.er,'async_get',return_value=registry),patch.object(dashboard.dr,'async_get',return_value=devices):
            generated=dashboard.build_dashboard(hass)
        return registry,generated

    async def test_exactly_four_overview_cards_and_all_energy_periods_reachable(self):
        registry,config=self.fixture()
        first=config['views'][0]
        self.assertEqual(first['path'],'overview');self.assertEqual(first['title'],'At-a-glance')
        self.assertEqual([c['title'] for c in cards(first)],['Momentanes Schalten','Gesamtverbrauch der Kaskade','Pufferfreigabe','Fehler'])
        self.assertNotIn('history-graph',str(first));self.assertNotIn('custom:',str(first))
        self.assertIn('binary_sensor.wp1',str(cards(first)[0]))
        self.assertIn('sensor.alarms',str(cards(first)[3]))
        self.assertNotIn('conditions',cards(first)[3])  # Unknown alarm feedback stays visible.
        bound=bind_dashboard_paths(config,'my-cascade')
        energy=next(v for v in bound['views'] if v['path']=='energy')
        navigation=next(c for c in cards(energy) if c.get('title')=='Energie-Zeiträume')
        paths=[c['tap_action']['navigation_path'] for c in navigation['cards']]
        self.assertEqual(paths,['/my-cascade/energy-'+p for p in ('hour','day','week','month','year')])
        for period in ('hour','day','week','month','year'):
            sub=next(v for v in bound['views'] if v['path']=='energy-'+period)
            self.assertTrue(sub['subview']);self.assertEqual(sub['back_path'],'/my-cascade/energy')
            self.assertTrue(any(c.get('period')==period for c in cards(sub)))
        self.assertIn('Stromherkunft · Bilanz',str(energy))

    async def test_migration_keeps_custom_graphs_settings_and_is_idempotent(self):
        registry,generated=self.fixture()
        personal={'type':'history-graph','title':'Personal solar','entities':['sensor.private_solar'],'hours_to_show':72}
        custom_range={'type':'history-graph','title':'Leistungsverlauf','entities':[{'entity':'sensor.wp_power'}],'hours_to_show':48}
        legacy={'title':'Custom title','views':[{'path':'overview','theme':'my-theme','cards':[
            personal,custom_range,{'type':'entity-filter','title':'Aktuelle Temperaturen','entities':[{'entity':'sensor.outside'}]}]}]}
        custom_period={'type':'statistics-graph','title':'Verbrauch von Elektrizität – Stündlich','period':'hour','days_to_show':99,'stat_types':['change'],'entities':[{'entity':'sensor.energy'}]}
        legacy['views'].append({'path':'energy','cards':[custom_period]})
        merged=dashboard.merge_dashboard(legacy,generated)
        updated=bind_dashboard_paths(organise_dashboard(merged,registry),'my-cascade')
        self.assertEqual(updated['title'],'Custom title');self.assertEqual(updated['views'][0]['theme'],'my-theme')
        self.assertIn(personal,cards(next(v for v in updated['views'] if v['path']=='personal')))
        self.assertIn(custom_range,cards(next(v for v in updated['views'] if v['path']=='runtime')))
        self.assertIn(custom_period,cards(next(v for v in updated['views'] if v['path']=='energy-hour')))
        self.assertEqual(updated,bind_dashboard_paths(organise_dashboard(dashboard.merge_dashboard(updated,generated),registry),'my-cascade'))
        self.assertEqual(legacy['views'][0]['cards'][0],personal)

    async def test_native_markdown_handles_unknown_feedback_and_aggregates_today(self):
        from homeassistant.core import HomeAssistant
        from homeassistant.helpers.template import Template
        registry,config=self.fixture();hass=HomeAssistant('/tmp')
        hass.states.async_set('sensor.total_power','1.234567',{'unit_of_measurement':'kW'})
        hass.states.async_set('sensor.charge','Wartet auf Überschuss',{'phase':None,'reason':'No PV production','buffer_target':36,'effective_offset':0,'adaptive_configured':True,'temperature_limit':65})
        for source,n in [('pv',2),('grid',3),('battery',1)]:
            for period in ('day','week','month','year','total'):hass.states.async_set(f'sensor.{source}_{period}',str(n),{'unit_of_measurement':'kWh'})
        consumption=cards(config['views'][0])[1]
        rendered=Template(consumption['content'],hass).async_render(parse_result=False)
        self.assertIn('1.23',rendered);self.assertIn('6.0',rendered)
        hass.states.async_set('sensor.total_power','unavailable',{'unit_of_measurement':'kW'})
        hass.states.async_set('sensor.pv_day','unknown',{'unit_of_measurement':'kWh'})
        rendered=Template(consumption['content'],hass).async_render(parse_result=False)
        self.assertIn('—',rendered);self.assertNotIn('6.0',rendered)
        for v in config['views']:
            for c in cards(v):
                if MARKER in c.get('content',''):
                    text=Template(c['content'],hass).async_render(parse_result=False)
                    if c.get('title')=='Stromherkunft · Bilanz':
                        import re
                        self.assertRegex(text,r'\| Zeitraum[^\n]*(?:\n\|[^\n]*){6}')

    async def test_panel_and_unowned_dashboard_remain_unchanged(self):
        registry,_=self.fixture()
        panel={'views':[{'path':'overview','type':'panel','cards':[{'type':'custom:personal'}]}]}
        self.assertEqual(organise_dashboard(panel,registry),panel)
        unowned={'views':[{'path':'overview','cards':[{'type':'entities','entities':['sensor.private_solar']}]}]}
        self.assertEqual(organise_dashboard(unowned,registry),unowned)

    async def test_generated_instantaneous_copy_does_not_create_personal_tab(self):
        registry,config=self.fixture()
        energy=next(v for v in config['views'] if v['path']=='energy')
        duplicate=deepcopy(next(c for c in cards(energy) if c.get('title')=='Momentanverbrauch'))
        config['views'].append({'path':'personal','title':'Eigene Karten','cards':[duplicate]})
        cleaned=organise_dashboard(config,registry)
        self.assertNotIn('personal',[v['path'] for v in cleaned['views']])
