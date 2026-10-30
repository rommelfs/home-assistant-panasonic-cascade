"""Optional batch failures, counter semantics, alarm history and DHW isolation."""
import importlib
from pathlib import Path
import sys
import unittest
from unittest.mock import AsyncMock, Mock, patch
from types import SimpleNamespace

from test_api import api, client, Session, Response, zinc, model

diagnostics = importlib.import_module('cascade_test.diagnostics')


def equipment():
    return {'p:demo:r:hp': {'id':zinc.Ref('p:demo:r:hp', 'HP 01'), 'equip':zinc.MARKER,
                          'heatPumpModelId':'_equip:heatPump'}}


class ExtendedProtocolTest(unittest.IsolatedAsyncioTestCase):
    async def test_eval_all_preserves_successes_around_an_error_grid(self):
        session = Session([Response(200, 'ver:"3.0"\nval\n2\n\nver:"3.0" err dis:"private backend error"\nempty\n\nver:"3.0"\nval\nF\n')])
        grids = await client(session).eval_all(['first()', 'second()', 'third()'])
        self.assertEqual(grids, [[{'val':zinc.Number(2)}], None, [{'val':False}]])
        self.assertTrue(session.calls[0][0].endswith('/evalAll'))
        envelope = zinc.parse_grids(session.calls[0][1]['data'].decode())[0]
        self.assertEqual([row['expr'] for row in envelope], ['first()','second()','third()'])
        self.assertFalse(session.calls[0][1]['allow_redirects'])
        with self.assertRaises(zinc.ZincError):
            zinc.parse_grids('ver:"3.0" err\nempty\n')

    async def test_eval_all_wrong_grid_count_refused(self):
        with self.assertRaises(api.ApiError):
            await client(Session([Response()])).eval_all(['one()', 'two()'])
        self.assertEqual(await client(Session()).eval_all([]), [])

    async def test_optional_permission_failure_keeps_existing_points(self):
        c = client(Session([Response(403)]))
        points = equipment()
        await c._enrich(points, 'p:demo:r:site')
        self.assertIn('p:demo:r:hp', points)
        self.assertEqual(points['summary:activeAlarms']['curStatus'], 'fault')
        self.assertIsNone(points['summary:activeAlarms']['curVal'])
        self.assertEqual(points['summary:unit:p:demo:r:hp:parameters:tankConnection']['curStatus'], 'fault')

    async def test_details_cached_but_current_summaries_always_polled(self):
        c = client(Session())
        calls = []
        async def evaluate(expressions):
            calls.append(expressions)
            return [[{'val':zinc.Number(1)}] for _ in expressions]
        c.eval_all = AsyncMock(side_effect=evaluate)
        with patch.object(api.time, 'monotonic', side_effect=[10,20,311]):
            for _ in range(3):
                await c._enrich(equipment(), 'p:demo:r:site')
        self.assertTrue(any('/alarmHistory/' in expr for expr in calls[0]))
        self.assertFalse(any('/control/parameters' in expr for expr in calls[1]))
        self.assertTrue(any('/alarmHistory/' in expr for expr in calls[2]))
        self.assertTrue(all(any('/alarmList/' in expr for expr in group) for group in calls))

    def test_alarm_history_filters_dhw_and_limits_exposed_entries(self):
        rows = equipment()
        rows['tank'] = {'id':zinc.Ref('tank'), 'tankModelId':'_equip:tank'}
        alarms = [{'equipRef':zinc.Ref('p:demo:r:hp'), 'ts':f'2026-01-{day:02d}T01:02:00+01:00 Berlin',
                   'alarmText':'unitOffline','alarmStatus':'normal','ackedBy':zinc.Ref('private-user'),
                   'instructions':'untrusted source instructions'} for day in range(1,26)]
        alarms.append({'equipRef':zinc.Ref('tank'), 'ts':'2026-02-01T00:00:00+01:00 Berlin',
                       'alarmText':'DHW-only','alarmStatus':'alarm'})
        spec = next(spec for spec in diagnostics.queries('site',rows,True) if spec[6]=='history')
        result = diagnostics.convert(spec,alarms,'site',rows,False)
        self.assertEqual(result['summary:alarmHistory']['curVal'], zinc.Number(25))
        self.assertEqual(len(result['summary:alarmHistory']['attributes']['alarms']),20)
        self.assertIn('unitOffline', result['summary:lastAlarm']['curVal'])
        self.assertNotIn('DHW-only', str(result))
        self.assertNotIn('private-user', str(result))
        self.assertNotIn('untrusted source instructions', str(result))
        self.assertNotIn('2026-02-01', str(result))

    def test_empty_vs_failed_alarm_endpoint(self):
        spec = next(s for s in diagnostics.queries('site',{},True) if s[6]=='history')
        empty = diagnostics.convert(spec, [], 'site', {})
        failed = diagnostics.convert(spec, None, 'site', {})
        self.assertEqual(empty['summary:alarmHistory']['curVal'], zinc.Number(0))
        self.assertEqual(empty['summary:lastAlarm']['curVal'], 'Keine')
        self.assertIsNone(failed['summary:alarmHistory']['curVal'])
        self.assertEqual(failed['summary:lastAlarm']['curStatus'], 'fault')

    def test_details_are_read_only_and_have_recoverable_placeholders(self):
        spec = next(s for s in diagnostics.queries('site',equipment(),True) if s[6]=='details')
        points = diagnostics.convert(spec,[{'dis':'tankConnection','curVal':False},
                                          {'dis':'numberZones','curVal':zinc.Number(1)},
                                          {'dis':'arbitraryWriteField','curVal':True}], 'site', equipment())
        self.assertEqual(len(points),9)
        self.assertNotIn('arbitraryWriteField', str(points))
        self.assertTrue(all(model.control_kind(row) is None for row in points.values()))
        filtered = model.visible_data(points,False)
        self.assertEqual(len(filtered),8)
        self.assertFalse(any(key.endswith(':tankConnection') for key in filtered))
        self.assertTrue(any(key.endswith(':bufferTankConnection') for key in filtered))
        self.assertEqual(points['summary:unit:p:demo:r:hp:parameters:zone1MaxSetpointTemperature']['unit'],'°C')

    def test_dhw_unit_energy_does_not_hide_heating_or_buffer(self):
        for key in ('tankModeEnergyConsumptionMsb','tankModeEnergyGeneration','tankWaterSetTemperature'):
            self.assertTrue(model.is_dhw({'heatPumpModelId':'_equip:heatPump_point:'+key}))
        for key in ('heatModeEnergyConsumptionTotalMsb','tBufferTank','coolModeHeatRecoveryModeEnergyGeneration'):
            self.assertFalse(model.is_dhw({'heatPumpModelId':'_equip:heatPump_point:'+key}))
        self.assertTrue(model.is_dhw({}, 'isRunningTank'))

    def test_temperature_sentinel_does_not_rewrite_other_readings(self):
        self.assertIsNone(model.state({'curVal':zinc.Number(-32768,'°C')}))
        self.assertEqual(model.state({'curVal':zinc.Number(-78,'°C')}),-78)
        self.assertEqual(model.state({'curVal':zinc.Number(-32768)}),-32768)


sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
try:
    sensors = importlib.import_module('custom_components.panasonic_cascade.sensor')
    real_zinc = importlib.import_module('custom_components.panasonic_cascade.zinc')
    dashboard = importlib.import_module('custom_components.panasonic_cascade.dashboard')
except ImportError:
    sensors = None


@unittest.skipIf(sensors is None, 'Home Assistant required')
class ExtendedEntityTest(unittest.TestCase):
    def coordinator(self,row):
        return SimpleNamespace(data={'point':row}, entry=SimpleNamespace(unique_id='install',data={'site_id':'site'},title='Test'),
                               client=SimpleNamespace(url='https://controller.invalid',project='demo'), last_update_success=True)

    def test_totalized_energy_only_gets_energy_statistics(self):
        from homeassistant.components.sensor import SensorStateClass
        for unit,total,expected in (('kWh',True,SensorStateClass.TOTAL_INCREASING),
                                    ('kWh',False,None),('W',True,SensorStateClass.MEASUREMENT)):
            row={'id':real_zinc.Ref('point'),'kind':'Number','unit':unit,'curVal':real_zinc.Number(100,unit)}
            if total:row['hisTotalized']=real_zinc.MARKER
            entity=sensors.CascadeSensor(self.coordinator(row),'point')
            self.assertEqual(entity.state_class,expected)
        row['diagnostic']=real_zinc.MARKER
        entity=sensors.CascadeSensor(self.coordinator(row),'point')
        self.assertEqual(entity.entity_category,'diagnostic')
        self.assertIsNone(entity.state_class)

    def test_sentinel_entity_unavailable_and_alarm_attributes_live(self):
        row={'kind':'Number','curVal':real_zinc.Number(-32768,'°C'),'curStatus':'ok'}
        entity=sensors.CascadeSensor(self.coordinator(row),'point')
        self.assertFalse(entity.available)
        row['curVal']=real_zinc.Number(35,'°C')
        self.assertTrue(entity.available)
        row['attributes']={'alarms':[{'text':'unitOffline'}]}
        self.assertEqual(entity.extra_state_attributes['alarms'][0]['text'],'unitOffline')

    def test_dashboard_alarm_templates_use_real_ids_and_only_counter_statistics(self):
        hass = Mock()
        hass.config_entries.async_entries.return_value = [SimpleNamespace(entry_id='entry')]
        def entity(ident,label,unique,unit=None,category=None):
            return SimpleNamespace(entity_id=ident, name=None, original_name=label, domain='sensor', unique_id=unique,
                                   platform='panasonic_cascade', config_entry_id='entry', device_id=None,
                                   unit_of_measurement=unit, disabled=False, hidden=False, entity_category=category)
        items = [entity('sensor.user_alarm','Aktive Alarme','install|summary:activeAlarms|curVal'),
                 entity('sensor.user_history','Alarmverlauf','install|summary:alarmHistory|curVal'),
                 entity('sensor.user_counter','Heizen – Energie','install|random_id|curVal','kWh'),
                 entity('sensor.ambiguous_energy','Unbestätigte Energie','install|other_id|curVal','kWh'),
                 entity('sensor.nominal_power','Nennleistung','install|rank|curVal','kW','diagnostic'),
                 entity('sensor.cop','Heizen – COP','install|random_cop_id|curVal')]
        registry = SimpleNamespace(entities={e.entity_id:e for e in items})
        hass.states.get.side_effect = lambda ident: SimpleNamespace(attributes={'unit_of_measurement':'kWh', 'state_class':'total_increasing'}) if ident=='sensor.user_counter' else None
        with patch.object(dashboard.er,'async_get',return_value=registry), patch.object(dashboard.dr,'async_get',return_value=SimpleNamespace(devices={})):
            config=dashboard.build_dashboard(hass)
        self.assertIn('alarms',[view['path'] for view in config['views']])
        self.assertIn('energy',[view['path'] for view in config['views']])
        alarm_view=next(view for view in config['views'] if view['path']=='alarms')
        self.assertIn("state_attr('sensor.user_alarm', 'alarms')", str(alarm_view))
        energy_view=next(view for view in config['views'] if view['path']=='energy')
        graph=next(card for card in energy_view['cards'] if card['type']=='statistics-graph')
        self.assertEqual([r['entity'] for r in graph['entities']],['sensor.user_counter'])
        self.assertEqual(graph['entities'][0]['name'],'Heizen · Energie')
        overview=config['views'][0]
        self.assertTrue(any(card.get('title')=='COP' for card in overview['cards']))
        self.assertFalse(any(card.get('title')=='Leistung' for card in overview['cards']))
