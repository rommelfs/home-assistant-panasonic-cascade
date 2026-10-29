"""Phone routing, active episodes, persistence, failure handling, and cleanup."""
import asyncio
import importlib
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock, Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
try:
    n = importlib.import_module('custom_components.panasonic_cascade.notifications')
    flow = importlib.import_module('custom_components.panasonic_cascade.config_flow')
    buttons = importlib.import_module('custom_components.panasonic_cascade.button')
    z = importlib.import_module('custom_components.panasonic_cascade.zinc')
    from homeassistant.core import HomeAssistant
    from homeassistant.exceptions import HomeAssistantError
except ImportError:
    n = None


def alarm(when='2026-10-21T12:00:00+02:00 Berlin', source='p:demo:r:hp', status='alarm'):
    return {'id':z.Ref('alarm:example'), 'equipRef':z.Ref(source), 'alarmStatus':status,
            'alarmText':'unitOffline', 'lastTimeOn':when, 'ackedBy':None}


@unittest.skipIf(n is None, 'Home Assistant required')
class NotificationsTest(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.hass = HomeAssistant(self.directory.name)
        self.messages = []
        async def receive(call):
            self.messages.append(dict(call.data))
        self.receive = receive
        self.hass.services.async_register('notify','mobile_app_iphone',receive)
        self.entry = SimpleNamespace(entry_id='entry', unique_id='installation', title='Heizung',
                                     data={'site_id':'site'}, options={'alarm_notify_service':'mobile_app_iphone'})
        rows = {'p:demo:r:hp':{'id':z.Ref('p:demo:r:hp','HP 01'), 'heatPumpModelId':'_equip:heatPump'},
                'tank':{'id':z.Ref('tank','Warmwasser'), 'tankModelId':'_equip:tank'}}
        self.coordinator = SimpleNamespace(entry=self.entry, all_data=rows,
                                           client=SimpleNamespace(active_alarms=AsyncMock(return_value=[alarm()])))
        self.monitor = n.AlarmMonitor(self.hass,self.entry,self.coordinator)

    async def asyncTearDown(self):
        self.monitor.async_stop()
        await self.hass.async_stop()
        self.directory.cleanup()

    async def test_one_push_per_episode_and_does_not_repeat_on_acknowledge(self):
        await self.monitor.async_check()
        await self.monitor.async_check()
        self.coordinator.client.active_alarms.return_value[0]['ackedBy']=z.Ref('private-user')
        await self.monitor.async_check()
        self.assertEqual(len(self.messages),1)
        self.assertIn('HP 01',self.messages[0]['message'])
        self.assertIn('unitOffline',self.messages[0]['message'])
        self.assertNotIn('private-user',str(self.messages))
        payload = self.messages[0]['data']
        self.assertEqual(payload['push']['interruption-level'],'time-sensitive')
        self.assertEqual(payload['priority'],'high')
        self.assertEqual(payload['ttl'],0)
        self.coordinator.client.active_alarms.return_value=[alarm('2026-10-21T12:30:00+02:00 Berlin')]
        await self.monitor.async_check()
        self.assertEqual(len(self.messages),2)
        self.assertNotEqual(self.messages[0]['data']['tag'],self.messages[1]['data']['tag'])

    async def test_clearing_rearms_even_without_a_new_timestamp(self):
        await self.monitor.async_check()
        self.coordinator.client.active_alarms.return_value=[alarm(status='normal')]
        await self.monitor.async_check()
        self.assertFalse(self.monitor.notified)
        self.coordinator.client.active_alarms.return_value=[alarm()]
        await self.monitor.async_check()
        self.assertEqual(len(self.messages),2)

    async def test_restart_restores_dedup_and_stops_timer(self):
        await self.monitor.async_check()
        restored = n.AlarmMonitor(self.hass,self.entry,self.coordinator)
        cancel = Mock()
        with patch.object(n,'async_track_time_interval',return_value=cancel) as schedule:
            await restored.async_start()
            await self.hass.async_block_till_done()
        self.assertEqual(schedule.call_args.args[2].total_seconds(),5)
        self.assertEqual(len(self.messages),1)
        restored.async_stop()
        cancel.assert_called_once()
        self.assertTrue(restored._stopped)

    async def test_new_phone_receives_existing_alarm(self):
        await self.monitor.async_check()
        self.hass.services.async_register('notify','mobile_app_new_iphone',self.receive)
        self.entry.options['alarm_notify_service']='mobile_app_new_iphone'
        changed = n.AlarmMonitor(self.hass,self.entry,self.coordinator)
        with patch.object(n,'async_track_time_interval',return_value=Mock()):
            await changed.async_start()
            await self.hass.async_block_till_done()
        changed.async_stop()
        self.assertEqual(len(self.messages),2)

    async def test_normal_and_dhw_alarms_not_sent(self):
        self.entry.options['use_dhw']=False
        self.coordinator.client.active_alarms.return_value=[alarm(source='tank'),alarm(status='normal')]
        await self.monitor.async_check()
        self.assertEqual(self.messages,[])
        self.assertFalse(self.monitor.notified)

    async def test_failed_read_does_not_rearm_or_repeat(self):
        await self.monitor.async_check()
        self.coordinator.client.active_alarms.side_effect=n.ApiError('connection failed')
        with self.assertLogs(n.LOGGER, level='WARNING'):
            await self.monitor.async_check()
        remembered=self.monitor.notified.copy()
        reads=self.coordinator.client.active_alarms.await_count
        await self.monitor.async_check()
        self.assertEqual(self.coordinator.client.active_alarms.await_count,reads)
        self.assertEqual(self.monitor.notified,remembered)
        self.coordinator.client.active_alarms.side_effect=None
        self.monitor._read_retry_at=0
        await self.monitor.async_check()
        self.assertEqual(len(self.messages),1)

    async def test_invalid_status_never_sends_and_preserves_prior_episode(self):
        await self.monitor.async_check()
        prior=self.monitor.notified.copy()
        self.coordinator.client.active_alarms.return_value=[alarm(status='unexpected')]
        with self.assertLogs(n.LOGGER,level='WARNING'):
            await self.monitor.async_check()
        self.assertEqual(self.monitor.notified,prior)
        self.assertEqual(len(self.messages),1)

    async def test_failed_notify_is_not_marked_sent_and_has_retry_backoff(self):
        self.hass.services.async_remove('notify','mobile_app_iphone')
        with self.assertLogs(n.LOGGER,level='WARNING'):
            await self.monitor.async_check()
        self.assertFalse(self.monitor.notified)
        self.hass.services.async_register('notify','mobile_app_iphone',self.receive)
        await self.monitor.async_check()
        self.assertFalse(self.messages)
        self.monitor._send_retry_at=0
        await self.monitor.async_check()
        self.assertEqual(len(self.messages),1)

    async def test_concurrent_checks_do_not_overlap_or_duplicate(self):
        entered, release = asyncio.Event(), asyncio.Event()
        async def read(site):
            entered.set()
            await release.wait()
            return [alarm()]
        self.coordinator.client.active_alarms.side_effect=read
        task=asyncio.create_task(self.monitor.async_check())
        await entered.wait()
        await self.monitor.async_check()
        release.set()
        await task
        self.assertEqual(self.coordinator.client.active_alarms.await_count,1)
        self.assertEqual(len(self.messages),1)

    async def test_unload_cancels_pending_check(self):
        entered=asyncio.Event()
        async def wait_forever(site):
            entered.set()
            await asyncio.Event().wait()
        self.coordinator.client.active_alarms.side_effect=wait_forever
        task=asyncio.create_task(self.monitor.async_check())
        await entered.wait()
        self.monitor.async_stop()
        with self.assertRaises(asyncio.CancelledError):
            await task
        self.assertIsNone(self.monitor._active_task)
        self.assertFalse(self.monitor._lock.locked())
        self.assertFalse(self.messages)

    async def test_test_button_is_clear_and_optional_time_sensitive_can_be_disabled(self):
        self.entry.options['alarm_time_sensitive']=False
        button=buttons.CascadePushTestButton(self.coordinator)
        button.hass=self.hass
        self.assertTrue(button.available)
        await button.async_press()
        self.assertEqual(len(self.messages),1)
        self.assertIn('kein Anlagenalarm',self.messages[0]['message'])
        self.assertNotIn('push',self.messages[0]['data'])
        self.coordinator.client.active_alarms.assert_not_awaited()
        self.entry.options['alarm_notify_service']=''
        added=Mock()
        await buttons.async_setup_entry(self.hass,SimpleNamespace(options={}),added)
        added.assert_not_called()
        with self.assertRaises(HomeAssistantError):
            await n.async_test_push(self.hass,self.entry)

    async def test_mobile_options_and_missing_target_error(self):
        self.hass.services.async_register('notify','telegram',self.receive)
        self.assertEqual(n.mobile_targets(self.hass),{'mobile_app_iphone':'iphone'})
        entry=SimpleNamespace(data={},options={})
        f=flow.CascadeOptionsFlow()
        f.handler='entry'
        f.hass=Mock()
        f.hass.services=self.hass.services
        f.hass.config_entries.async_get_known_entry.return_value=entry
        result=await f.async_step_init()
        values=result['data_schema']({'scan_interval':30,'enable_controls':False,'use_dhw':True,'verify_ssl':True})
        self.assertEqual(values['alarm_notify_service'],'')
        self.assertTrue(values['alarm_time_sensitive'])
        bad=await f.async_step_init({**values,'alarm_notify_service':'telegram'})
        self.assertEqual(bad['errors']['base'],'notification_target_unavailable')
        good=await f.async_step_init({**values,'alarm_notify_service':'mobile_app_iphone'})
        self.assertEqual(good['data']['alarm_notify_service'],'mobile_app_iphone')


    async def test_setup_starts_monitor_only_when_a_phone_is_selected(self):
        integration=importlib.import_module('custom_components.panasonic_cascade')
        hass=Mock()
        hass.config_entries.async_forward_entry_setups=AsyncMock()
        entry=SimpleNamespace(data={},options={},async_on_unload=Mock(),add_update_listener=Mock(return_value=Mock()))
        coordinator=SimpleNamespace(all_data={},async_config_entry_first_refresh=AsyncMock())
        monitor=SimpleNamespace(async_start=AsyncMock(),async_stop=Mock())
        with patch.object(integration,'async_get_clientsession',return_value=object()), \
             patch.object(integration,'CascadeClient'), \
             patch.object(integration,'CascadeCoordinator',return_value=coordinator), \
             patch.object(integration,'async_apply_dhw_visibility',new=AsyncMock()), \
             patch.object(integration,'async_setup_frontend',new=AsyncMock()), \
             patch.object(integration,'async_register_dashboard_service'), \
             patch.object(integration,'AlarmMonitor',return_value=monitor) as factory:
            self.assertTrue(await integration.async_setup_entry(hass,entry))
            factory.assert_not_called()
            entry.options['alarm_notify_service']='mobile_app_iphone'
            self.assertTrue(await integration.async_setup_entry(hass,entry))
            factory.assert_called_once_with(hass,entry,coordinator)
            monitor.async_start.assert_awaited_once()
            self.assertIn(((monitor.async_stop,),{}),entry.async_on_unload.call_args_list)
