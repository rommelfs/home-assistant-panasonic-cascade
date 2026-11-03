"""Independent counter consumption and honest source reconciliation."""
import unittest
from datetime import datetime
from zoneinfo import ZoneInfo
from custom_components.panasonic_cascade.consumption import period_start, sum_changes

class ConsumptionTest(unittest.TestCase):
    def test_same_counter_changes_as_daily_chart_not_partial_source_integral(self):
        self.assertEqual(sum_changes({'wp1':[{'change':18}],'wp2':[{'change':20}]},['wp1','wp2']),38)
        # Reset handling is already performed by Recorder's cumulative sum/change.
        self.assertEqual(sum_changes({'wp1':[{'change':1},{'change':2}]},['wp1']),3)
        for data in ({},{'wp1':[]},{'wp1':[{'change':None}]},{'wp1':[{'change':float('nan')}]},{'wp1':[{'change':-1}]}):
            self.assertIsNone(sum_changes(data,['wp1']))
        self.assertIsNone(sum_changes({'wp1':[{'change':1}]},['wp1','wp2']))

    def test_local_day_week_month_year_boundaries(self):
        tz=ZoneInfo('Europe/Berlin');now=datetime(2026,11,3,15,0,tzinfo=tz)
        self.assertEqual(period_start(now,'day').isoformat(),'2026-11-03T00:00:00+01:00')
        self.assertEqual(period_start(now,'week').isoformat(),'2026-11-02T00:00:00+01:00')
        self.assertEqual(period_start(now,'month').isoformat(),'2026-11-01T00:00:00+01:00')
        self.assertEqual(period_start(now,'year').isoformat(),'2026-01-01T00:00:00+01:00')

class ReconciliationTemplateTest(unittest.IsolatedAsyncioTestCase):
    async def test_total_is_independent_and_unassigned_difference_is_explicit(self):
        from homeassistant.core import HomeAssistant
        from homeassistant.helpers.template import Template
        from custom_components.panasonic_cascade.dashboard_layout import energy_table
        hass=HomeAssistant('/tmp');ids={key:'sensor.'+key for key in ('pv','grid','battery')}
        for key,value in [('pv',2.34),('grid',.405),('battery',.027)]:hass.states.async_set(ids[key],str(value))
        hass.states.async_set('sensor.consumption','38')
        content=energy_table({'day':ids},{'day':'sensor.consumption'})['content']
        rendered=Template(content,hass).async_render(parse_result=False)
        self.assertIn('| Heute | 38.0 | 2.34 | 0.41 | 0.03 | 2.77 | 35.23 |',rendered)
        hass.states.async_set('sensor.pv','unavailable')
        rendered=Template(content,hass).async_render(parse_result=False)
        self.assertIn('| Heute | 38.0 | —',rendered)
        self.assertNotIn('35.23',rendered)

class ConsumptionHATest(unittest.IsolatedAsyncioTestCase):
    async def test_sensor_queries_own_electrical_counters_and_ignores_source_gaps(self):
        from unittest.mock import Mock, AsyncMock, patch
        from types import SimpleNamespace
        from homeassistant.core import HomeAssistant
        from homeassistant.helpers.recorder import DATA_INSTANCE
        from custom_components.panasonic_cascade import consumption as module
        hass=HomeAssistant('/tmp')
        c=SimpleNamespace(entry=SimpleNamespace(unique_id='install'),data={
            'electric1':{'heatPumpModelId':'x:heatModeEnergyConsumptionTotalMsb'},
            'electric2':{'heatPumpModelId':'x:heatModeEnergyConsumptionTotalMsb'},
            'thermal':{'heatPumpModelId':'x:heatModeEnergyGenerationTotalMsb'},
            'summary:consumedPower':{},'other':{'heatPumpModelId':'x:heatModeEnergyConsumption'}})
        sensor=module.ConsumptionSensor(c,'day');sensor.hass=hass
        registry=Mock();registry.async_get_entity_id.side_effect=lambda domain,platform,uid:'sensor.'+uid.split('|')[1]
        recorder=SimpleNamespace(async_db_ready=None,entity_filter=None,async_add_executor_job=AsyncMock(return_value={
            'sensor.electric1':[{'change':18,'end':123}], 'sensor.electric2':[{'change':20,'end':123}]}))
        hass.data[DATA_INSTANCE]=recorder
        with patch.object(module.er,'async_get',return_value=registry),patch.object(module,'get_instance',return_value=recorder):
            await sensor.async_update()
            self.assertEqual(sensor.native_value,38)
            job=recorder.async_add_executor_job.call_args.args[0]
            self.assertEqual(job.args[3],{'sensor.electric1','sensor.electric2'})
            self.assertEqual(job.args[4:],('day',{'energy':'kWh'},{'change'}))
            recorder.async_add_executor_job.return_value={'sensor.electric1':[{'change':18}]}
            await sensor.async_update();self.assertFalse(sensor.available)
