"""Concrete daily totals, actual HA template rendering, and narrow automatic dashboard migration."""
from copy import deepcopy
from datetime import datetime, timedelta, UTC
import importlib
import tempfile
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch
import unittest
from zoneinfo import ZoneInfo
import test_controls_dashboard as controls

try:
    runtime=importlib.import_module('custom_components.panasonic_cascade.runtime')
    dashboard=controls.dashboard
    from homeassistant.core import HomeAssistant, State
    from homeassistant.helpers.template import Template
    from homeassistant.components.lovelace.const import LOVELACE_DATA
except ImportError:
    runtime=None

@unittest.skipIf(runtime is None,'Home Assistant required')
class DailyTableTest(unittest.IsolatedAsyncioTestCase):
    def test_five_today_six_yesterday_are_separate_absolute_counts(self):
        old_zone=runtime.dt_util.DEFAULT_TIME_ZONE
        runtime.dt_util.set_default_time_zone(ZoneInfo('UTC'))
        try:
            today=datetime(2026,10,30,tzinfo=UTC)
            samples=[State('binary_sensor.wp','off',last_updated=today-timedelta(days=1,minutes=1))]
            for days,count in [(1,6),(0,5)]:
                for cycle in range(count):
                    t=today-timedelta(days=days)+timedelta(minutes=10+cycle*30)
                    samples.extend([State('binary_sensor.wp','on',last_updated=t),State('binary_sensor.wp','off',last_updated=t+timedelta(minutes=2))])
            result=runtime.daily_counts(samples,today.date())
            self.assertEqual(len(result),7)
            self.assertEqual(result[0],{'date':'2026-10-30','starts':5,'partial':False})
            self.assertEqual(result[1],{'date':'2026-10-29','starts':6,'partial':False})
            self.assertIsNone(result[-1]['starts'])
            self.assertEqual(runtime.daily_counts(samples,today.date()),result)
        finally:runtime.dt_util.set_default_time_zone(old_zone)

    def test_dst_day_and_run_across_midnight_do_not_add_a_start(self):
        old_zone=runtime.dt_util.DEFAULT_TIME_ZONE
        runtime.dt_util.set_default_time_zone(ZoneInfo('Europe/Berlin'))
        try:
            # 25 October 2026 has 25 hours in Berlin. Both 02:20 occurrences belong to it.
            data=[State('binary_sensor.wp','on',last_updated=datetime(2026,10,24,21,55,tzinfo=UTC)),
                  State('binary_sensor.wp','off',last_updated=datetime(2026,10,25,0,20,tzinfo=UTC)),
                  State('binary_sensor.wp','on',last_updated=datetime(2026,10,25,1,20,tzinfo=UTC))]
            result=runtime.daily_counts(data,datetime(2026,10,26).date(),days=2)
            self.assertEqual([r['starts'] for r in result],[0,1])
            self.assertTrue(all(not r['partial'] for r in result))
            self.assertEqual(runtime.count_starts([State('binary_sensor.wp','unavailable',last_updated=datetime(2026,10,25,tzinfo=UTC))],datetime(2026,10,25,tzinfo=UTC)),(None,True))
        finally:runtime.dt_util.set_default_time_zone(old_zone)

    async def test_actual_ha_markdown_template_shows_numbers_not_a_graph_or_blank_rows(self):
        with tempfile.TemporaryDirectory() as directory:
            hass=HomeAssistant(directory)
            today=runtime.dt_util.now().date()
            entities=[{'entity':'sensor.wp1_starts'},{'entity':'sensor.wp2_starts'}]
            hass.states.async_set('sensor.wp1_starts','5',{'friendly_name':'WP 1 · Starts heute','daily_starts':[
                {'date':str(today),'starts':5,'partial':False},
                {'date':str(today-timedelta(days=1)),'starts':6,'partial':False}]})
            hass.states.async_set('sensor.wp2_starts','3',{'friendly_name':'WP 2 · Starts heute','daily_starts':[
                {'date':str(today),'starts':3,'partial':True},
                {'date':str(today-timedelta(days=1)),'starts':None,'partial':True}]})
            card=dashboard.starts_table(entities)
            text=Template(card['content'],hass).async_render(parse_result=False)
            rows=[line for line in text.splitlines() if line.startswith('|')]
            self.assertEqual(rows[0],'| Tag | WP 1 | WP 2 |')
            self.assertEqual(rows[2],'| Heute | 5 | 3* |')
            self.assertEqual(rows[3],'| Gestern | 6 | — |')
            self.assertEqual(len(rows),9)
            self.assertIn('\n'.join(rows),text)  # A Markdown table needs consecutive, nonblank rows.
            await hass.async_stop()

    def fixture(self):
        def entity(ident,unique,domain):
            return SimpleNamespace(entity_id=ident,unique_id=unique,domain=domain,platform='panasonic_cascade',
                                   config_entry_id='one',disabled=False,hidden=False)
        entries=[entity('binary_sensor.renamed_running','site|hp|isRunning','binary_sensor'),
                 entity('sensor.renamed_starts','site|hp|starts_today','sensor')]
        registry=SimpleNamespace(entities={e.entity_id:e for e in entries})
        original={'title':'My dashboard','views':[{'path':'runtime','theme':'my-theme','cards':[
            {'type':'history-graph','title':'Betrieb und Taktung – 24 Stunden','hours_to_show':24,'entities':['binary_sensor.renamed_running']},
            {'type':'markdown','title':'My custom card','content':'Keep me'}]}]}
        target=SimpleNamespace(mode='storage',async_load=AsyncMock(return_value=original),async_save=AsyncMock())
        hass=SimpleNamespace(data={LOVELACE_DATA:SimpleNamespace(dashboards={'cascade':target})})
        return hass,registry,target,original

    async def test_existing_runtime_view_gets_table_automatically_once_with_backup(self):
        hass,registry,target,original=self.fixture()
        with patch.object(dashboard.er,'async_get',return_value=registry),patch.object(dashboard,'save_dashboard_backup',new=AsyncMock()) as backup:
            await dashboard.async_refresh_starts_tables(hass)
            updated=target.async_save.call_args.args[0]
            table=updated['views'][0]['cards'][0]
            self.assertEqual(table['title'],'Einschaltungen pro Tag')
            self.assertIn('sensor.renamed_starts',table['content'])
            self.assertEqual(updated['views'][0]['cards'][1:],original['views'][0]['cards'])
            self.assertEqual(updated['views'][0]['theme'],'my-theme')
            backup.assert_awaited_once_with(hass,'cascade',original)
            target.async_load.return_value=deepcopy(updated)
            target.async_save.reset_mock();backup.reset_mock()
            await dashboard.async_refresh_starts_tables(hass)
            target.async_save.assert_not_awaited();backup.assert_not_awaited()

    async def test_custom_table_and_unrelated_runtime_views_are_not_overwritten(self):
        hass,registry,target,original=self.fixture()
        original['views'][0]['cards'].append({'type':'markdown','title':'Einschaltungen pro Tag','content':'My own numbers'})
        with patch.object(dashboard.er,'async_get',return_value=registry):
            await dashboard.async_refresh_starts_tables(hass)
            target.async_save.assert_not_awaited()
            original['views'][0]['cards'].pop()
            original['views'][0]['cards'][0]['entities']=['binary_sensor.other_integration']
            await dashboard.async_refresh_starts_tables(hass)
            target.async_save.assert_not_awaited()

    async def test_failed_backup_leaves_existing_dashboard_intact(self):
        hass,registry,target,_=self.fixture()
        with patch.object(dashboard.er,'async_get',return_value=registry),patch.object(dashboard,'save_dashboard_backup',new=AsyncMock(side_effect=OSError('disk full'))),self.assertLogs(dashboard.LOGGER,level='WARNING'):
            await dashboard.async_refresh_starts_tables(hass)
        target.async_save.assert_not_awaited()
