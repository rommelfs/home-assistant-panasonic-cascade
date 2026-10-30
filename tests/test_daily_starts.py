"""Daily counts come from recorded off/on transitions, not restarts or hour counters."""
from datetime import datetime, timedelta, UTC
import importlib
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch
import unittest
from zoneinfo import ZoneInfo
import test_controls_dashboard as controls

try:
    runtime=importlib.import_module('custom_components.panasonic_cascade.runtime')
    zinc=importlib.import_module('custom_components.panasonic_cascade.zinc')
    from homeassistant.core import State
except ImportError:
    runtime=None

@unittest.skipIf(runtime is None,'Home Assistant required')
class DailyStartsTest(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.start=datetime(2026,10,30,tzinfo=UTC)
    def states(self, entries):
        return [State('binary_sensor.pump', value, last_updated=self.start+timedelta(minutes=minute)) for minute,value in entries]
    def powers(self, entries):
        return [State('sensor.pump', ('350' if value=='on' else '50' if value=='off' else value), {'unit_of_measurement':'W'}, last_updated=self.start+timedelta(minutes=minute)) for minute,value in entries]
    def test_counts_only_confirmed_off_to_on(self):
        states=self.states([(-5,'off'),(10,'on'),(11,'on'),(20,'off'),(30,'on'),(40,'off')])
        self.assertEqual(runtime.count_starts(states,self.start),(2,False))
    def test_power_threshold_units_boundaries_gaps_and_calendar_backfill(self):
        self.assertIs(runtime.power_on('0.2','kW',200),True)
        self.assertIs(runtime.power_on('199.99','W',200),False)
        for raw,unit in [('nan','W'),('inf','kW'),('-5','W'),('200','Wh'),('unavailable','W')]:
            self.assertIsNone(runtime.power_on(raw,unit,200))
        states=self.powers([(-5,'off'),(10,'on'),(20,'off'),(30,'on'),(40,'unavailable'),(50,'on'),(60,'off'),(70,'on')])
        converted=runtime.threshold_states(states,200)
        self.assertEqual(runtime.count_starts(converted,self.start),(3,True))
        self.assertEqual(runtime.daily_counts(converted,self.start.date())[0],{'date':'2026-10-30','starts':3,'partial':True})
        self.assertEqual(runtime.count_starts(runtime.threshold_states(states,400),self.start),(0,True))
    def test_midnight_and_restart_on_samples_do_not_add_a_start(self):
        self.assertEqual(runtime.count_starts(self.states([(-90,'on'),(5,'on')]),self.start),(0,False))
        self.assertEqual(runtime.count_starts(self.states([(30,'on'),(40,'off'),(50,'on')]),self.start),(1,True))
        self.assertEqual(runtime.count_starts(self.states([(-10,'off'),(0,'on')]),self.start),(1,False))
    def test_unknown_gap_and_missing_history_are_not_invented(self):
        self.assertEqual(runtime.count_starts([],self.start),(None,True))
        states=self.states([(-5,'off'),(5,'unavailable'),(10,'on'),(20,'off'),(30,'on')])
        self.assertEqual(runtime.count_starts(states,self.start),(1,True))
    def test_local_midnight_handles_both_dst_offsets(self):
        prior=runtime.dt_util.DEFAULT_TIME_ZONE
        runtime.dt_util.set_default_time_zone(ZoneInfo('Europe/Berlin'))
        try:
            for day,hour in [(datetime(2026,3,29).date(),23),(datetime(2026,10,25).date(),22)]:
                midnight=runtime.dt_util.as_utc(runtime.dt_util.start_of_local_day(day))
                self.assertEqual(midnight.hour,hour)
                self.assertEqual(midnight.date(),day-timedelta(days=1))
        finally:runtime.dt_util.set_default_time_zone(prior)
    def entity(self):
        c=controls.coordinator();c.data={'hp':{'id':zinc.Ref('p:demo:r:hp'),'equip':zinc.MARKER,
            'heatPumpModelId':'_equip:heatPump','dis':'HP 01 - Main','isRunning':True}}
        entity=runtime.CascadeDailyStartsSensor(c,'hp')
        entity.hass=SimpleNamespace(data={runtime.DATA_INSTANCE:object()},states=Mock())
        entity.hass.states.get.return_value=SimpleNamespace(state='350',attributes={'unit_of_measurement':'W'})
        return entity
    async def test_recorder_backfill_and_restart_recompute_same_absolute_count(self):
        entity=self.entity();source='binary_sensor.my_renamed_pump'
        recorder=SimpleNamespace(entity_filter=None,async_add_executor_job=AsyncMock(return_value={source:self.powers([(-5,'off'),(5,'on'),(10,'off'),(15,'on')])}))
        registry=Mock();registry.async_get_entity_id.return_value=source
        with patch.object(runtime,'power_source',return_value=source),patch.object(runtime.er,'async_get',return_value=registry),patch.object(runtime,'get_instance',return_value=recorder), \
             patch.object(runtime.dt_util,'now',return_value=self.start+timedelta(hours=10)), \
             patch.object(runtime.dt_util,'start_of_local_day',side_effect=lambda day:datetime(day.year,day.month,day.day,tzinfo=UTC)):
            await entity.async_update();self.assertEqual(entity.native_value,2)
            await entity.async_update();self.assertEqual(entity.native_value,2)
        self.assertEqual(entity.unique_id,'installation|hp|starts_today')
        self.assertEqual(entity.name,'WP 1 · Starts heute (Leistung)')
        self.assertTrue(entity.should_poll)
        self.assertFalse(entity.extra_state_attributes['partial_day'])
        query=recorder.async_add_executor_job.call_args.args[0]
        self.assertEqual(query.keywords['entity_id'],source)
    async def test_missing_and_excluded_recorder_produce_unavailable_not_zero(self):
        entity=self.entity();entity.hass.data={}
        with patch.object(runtime,'power_source',return_value='binary_sensor.verified'),patch.object(runtime.er,'async_get',return_value=Mock()):await entity.async_update()
        self.assertFalse(entity.available)
        self.assertIsNone(entity.native_value)
        entity.hass.data={runtime.DATA_INSTANCE:object()}
        recorder=SimpleNamespace(entity_filter=lambda source:False,async_add_executor_job=AsyncMock())
        with patch.object(runtime,'power_source',return_value='binary_sensor.verified'),patch.object(runtime.er,'async_get',return_value=Mock()),patch.object(runtime,'get_instance',return_value=recorder):await entity.async_update()
        self.assertFalse(entity.available);recorder.async_add_executor_job.assert_not_awaited()
        recorder.entity_filter=None
        recorder.async_db_ready=Mock()
        recorder.async_db_ready.done.return_value=False
        with patch.object(runtime,'power_source',return_value='binary_sensor.verified'),patch.object(runtime.er,'async_get',return_value=Mock()),patch.object(runtime,'get_instance',return_value=recorder):await entity.async_update()
        self.assertFalse(entity.available)
        self.assertEqual(entity.extra_state_attributes['reason'],'Recorder database not ready')
        recorder.async_add_executor_job.assert_not_awaited()

    async def test_unit_enable_is_never_treated_as_confirmed_compressor_running(self):
        entity=self.entity()
        with patch.object(runtime,'power_source',return_value=None):await entity.async_update()
        self.assertIsNone(entity.native_value)
        self.assertFalse(entity.available)
        self.assertEqual(entity.extra_state_attributes['daily_starts'],[])
        self.assertIn('Per-unit electrical power',entity.extra_state_attributes['reason'])
