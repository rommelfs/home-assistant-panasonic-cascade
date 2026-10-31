"""Durable temporary PV charging, using mocked hardware only."""
import asyncio
from copy import deepcopy
from datetime import UTC, datetime
import importlib
import time
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock, Mock, patch
from test_buffer_offset import live_offset
from test_controls_dashboard import HomeAssistantError
zinc=importlib.import_module('custom_components.panasonic_cascade.zinc')
charge=importlib.import_module('custom_components.panasonic_cascade.buffer_charge')

class Storage:
    def __init__(self): self.data=None; self.fail=False; self.saved=[]
    async def async_load(self): return deepcopy(self.data)
    async def async_save(self,data):
        if self.fail: raise OSError('disk failure')
        self.data=deepcopy(data);self.saved.append(deepcopy(data))

class ChargeTest(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.t=time.time();self.states={};self.store=Storage();self.writes=[]
        self.options={**charge.DEFAULTS,'enable_controls':True,'pv_charge_enabled':True,'pv_charge_confirmed':True}
        for k in charge.SOURCE_KEYS:self.options[f'pv_charge_{k}_sensor']='sensor.'+k
        self.hass=SimpleNamespace(states=SimpleNamespace(get=lambda k:self.states.get(k)))
        self.entry=SimpleNamespace(entry_id='entry',unique_id='installation',title='Test installation',options=self.options,data={'site_id':'site'})
        self.row=live_offset();self.row.update(writeDef=zinc.Number(2,'°C'),curVal=zinc.Number(2,'°C'))
        self.c=SimpleNamespace(hass=self.hass,entry=self.entry,_write_lock=asyncio.Lock(),data={'point':self.row},last_update_success=True,client=SimpleNamespace(),async_add_listener=Mock(return_value=Mock()))
        self.mode={'bufferModelId':'_equip:buffer_point:bufferMode','curStatus':'ok','curVal':'Heat'}
        self.c.data['mode']=self.mode
        self.c.client.read_point=AsyncMock(side_effect=lambda ident,*_:dict(self.mode) if ident=='mode' else deepcopy(self.row,{id(zinc.MARKER):zinc.MARKER}))
        async def write(row,target):
            self.assertIsNotNone(self.store.data['lease'])
            self.writes.append(target)
            override = self.row['curVal'].value != self.row['writeDef'].value
            self.row['writeDef']=zinc.Number(target,'°C')
            if not override:self.row['curVal']=zinc.Number(target,'°C')
        self.c.client.set_default=AsyncMock(side_effect=write)
        self.m=charge.BufferCharge(self.c,self.store,clock=lambda:self.t);self.c.buffer_charge=self.m
        self.refresh()
        for n in ['async_dispatcher_send','async_track_point_in_utc_time','async_track_time_interval','async_track_state_change_event']:
            self.enterContext(patch.object(charge,n,return_value=Mock()))
        self.enterContext(patch('homeassistant.components.persistent_notification.async_create'))

    def refresh(self):
        for k,v,u in [('export',2500,'W'),('battery',0,'W'),('pv',6000,'W'),('temperature',40,'°C')]:
            self.states['sensor.'+k]=SimpleNamespace(state=str(v),attributes={'unit_of_measurement':u},last_reported=datetime.fromtimestamp(self.t,UTC))
    def advance(self,seconds):self.t+=seconds;self.refresh()
    async def begin(self,offset=7,duration=10):
        self.m.stable_since=self.t-120;await self.m.async_start(offset,duration)

    async def test_durable_nonzero_baseline_before_write_and_expiry(self):
        await self.begin();first=self.store.saved[0]['lease']
        self.assertEqual((first['baseline'],first['applied'],first['phase']),(2,7,'applying'))
        self.assertEqual(first['expires'],self.t+600);self.assertEqual(self.writes,[7])
        self.assertTrue(await self.m.async_stop());self.assertEqual(self.writes,[7,2]);self.assertIsNone(self.store.data['lease'])

    async def test_expiry_and_deadline_callback_restore(self):
        await self.begin(duration=1);self.advance(61);await self.m.async_tick()
        self.assertIsNone(self.m.lease);self.assertEqual(self.writes,[7,2])
        await self.begin(duration=1);self.advance(61);await self.m._deadline(None)
        self.assertEqual(self.writes,[7,2,7,2])

    async def test_restart_restores_unexpired_lease_even_with_controls_disabled(self):
        await self.begin();self.options['enable_controls']=False;self.options['pv_charge_enabled']=False
        new=charge.BufferCharge(self.c,self.store,clock=lambda:self.t)
        await new.async_initialize();self.assertIsNone(new.lease);self.assertEqual(self.writes,[7,2])

    async def test_failed_restore_stays_durable_then_retries(self):
        await self.begin();self.c.client.read_point.side_effect=OSError('offline')
        self.assertFalse(await self.m.async_stop());self.assertEqual(self.store.data['lease']['phase'],'restore_pending')
        self.c.client.read_point.side_effect=lambda *_:deepcopy(self.row,{id(zinc.MARKER):zinc.MARKER})
        self.advance(16);await self.m.async_tick();self.assertIsNone(self.m.lease);self.assertEqual(self.writes,[7,2])

    async def test_external_default_is_preserved_and_acknowledgement_does_not_write(self):
        await self.begin();self.row.update(writeDef=zinc.Number(4,'°C'),curVal=zinc.Number(4,'°C'))
        self.assertFalse(await self.m.async_stop());self.assertEqual(self.m.lease['phase'],'conflict')
        await self.m.async_acknowledge();self.assertIsNone(self.m.lease);self.assertEqual(self.writes,[7])

    async def test_original_default_restored_without_overwriting_external_schedule(self):
        await self.begin();self.row['curVal']=zinc.Number(3,'°C')
        self.assertTrue(await self.m.async_stop());self.assertIsNone(self.m.lease);self.assertEqual(self.writes,[7,2])
        self.assertEqual(self.row['curVal'].value,3)

    async def test_already_restored_value_not_written_again(self):
        await self.begin();self.row.update(writeDef=zinc.Number(2,'°C'),curVal=zinc.Number(2,'°C'))
        self.assertTrue(await self.m.async_stop());self.assertEqual(self.writes,[7])

    async def test_overlap_cannot_extend_or_replace_lease(self):
        await self.begin();expiry=self.m.lease['expires']
        with self.assertRaises(HomeAssistantError):await self.m.async_start(9,30)
        self.assertEqual(self.writes,[7]);self.assertEqual(self.m.lease['expires'],expiry)

    async def test_invalid_requests_never_write(self):
        for offset,duration in [(11,10),(0,10),(7,121),(7,0),(float('nan'),10),(True,10)]:
            with self.assertRaises(HomeAssistantError):await self.begin(offset,duration)
        self.assertEqual(self.writes,[])

    async def test_disabled_unverified_or_offline_never_write(self):
        for k in ['enable_controls','pv_charge_enabled','pv_charge_confirmed']:
            self.options[k]=False
            with self.assertRaises(HomeAssistantError):await self.begin()
            self.options[k]=True
        self.c.last_update_success=False
        with self.assertRaises(HomeAssistantError):await self.begin()
        self.assertEqual(self.writes,[])

    async def test_missing_ambiguous_and_readonly_point_never_write(self):
        self.c.data={}
        with self.assertRaises(HomeAssistantError):await self.begin()
        self.c.data={'point':self.row,'other':deepcopy(self.row,{id(zinc.MARKER):zinc.MARKER})}
        with self.assertRaises(HomeAssistantError):await self.begin()
        self.c.data={'point':self.row};self.row['writable']=None
        with self.assertRaises(HomeAssistantError):await self.begin()
        self.assertEqual(self.writes,[])

    async def test_tighter_bounds_and_non_increasing_offset_rejected(self):
        self.row['maxVal']=zinc.Number(4,'°C')
        for offset in (7,2):
            with self.assertRaises(HomeAssistantError):await self.begin(offset)
        self.assertEqual(self.writes,[])

    async def test_initial_storage_failure_prevents_write(self):
        self.store.fail=True
        with self.assertRaises(HomeAssistantError):await self.begin()
        self.assertEqual(self.writes,[]);self.assertIsNone(self.m.lease)

    async def test_ambiguous_raise_write_is_not_replayed(self):
        normal=self.c.client.set_default.side_effect
        async def ambiguous(row,target):
            await normal(row,target)
            if target==7:raise OSError('lost response')
        self.c.client.set_default.side_effect=ambiguous
        with self.assertRaises(HomeAssistantError):await self.begin()
        self.assertEqual(self.writes,[7,2]);self.assertIsNone(self.m.lease)

    async def test_lost_restore_response_is_confirmed_without_second_write(self):
        await self.begin();normal=self.c.client.set_default.side_effect
        async def ambiguous(row,target):await normal(row,target);raise OSError('lost response')
        self.c.client.set_default.side_effect=ambiguous
        self.assertFalse(await self.m.async_stop());self.advance(16);await self.m.async_tick()
        self.assertIsNone(self.m.lease);self.assertEqual(self.writes,[7,2])

    async def test_failed_clear_retains_ownership_and_retries_without_rewriting(self):
        await self.begin();self.store.fail=True
        self.assertFalse(await self.m.async_stop());self.assertIsNotNone(self.m.lease);self.assertEqual(self.writes,[7,2])
        self.store.fail=False;self.advance(16);await self.m.async_tick()
        self.assertIsNone(self.m.lease);self.assertEqual(self.writes,[7,2])

    async def test_stable_start_and_distinct_stop_threshold(self):
        await self.m.async_tick()
        with self.assertRaises(HomeAssistantError):await self.m.async_start(7,10)
        self.advance(120);await self.m.async_start(7,10)
        self.states['sensor.export'].state='700';await self.m.async_tick();self.assertIsNotNone(self.m.lease)
        self.states['sensor.export'].state='400';await self.m.async_tick();self.assertIsNone(self.m.lease)

    async def test_automatic_start_waits_for_full_dwell(self):
        self.options['pv_charge_auto']=True;await self.m.async_tick();self.assertEqual(self.writes,[])
        self.advance(119);await self.m.async_tick();self.assertEqual(self.writes,[])
        self.advance(1);await self.m.async_tick();self.assertEqual(self.writes,[5])

    async def test_lost_start_threshold_resets_stability(self):
        await self.m.async_tick();self.advance(100);self.states['sensor.export'].state='1200'
        await self.m.async_tick();self.assertIsNone(self.m.stable_since)

    async def test_unknown_invalid_stale_and_wrong_units_never_start(self):
        for k,v,u in [('temperature',-78,'°C'),('temperature',75,'°C'),('temperature','unknown','°C'),('temperature',40,'°F'),
                      ('export',2000,'kWh'),('pv',0,'W'),('battery',101,'W'),('export',-1,'W'),('pv','nan','W')]:
            self.refresh();s=self.states['sensor.'+k];s.state=str(v);s.attributes['unit_of_measurement']=u
            with self.assertRaises(HomeAssistantError):await self.begin()
        self.refresh();self.t+=61
        with self.assertRaises(HomeAssistantError):await self.begin()
        self.assertEqual(self.writes,[])

    async def test_guard_failures_and_75c_limit_stop_immediately(self):
        for k,v in [('pv',0),('battery',500),('export',-10),('temperature',75),('temperature',-78)]:
            self.refresh();await self.begin();self.states['sensor.'+k].state=str(v)
            await self.m.async_tick();self.assertIsNone(self.m.lease)
        self.assertEqual(self.writes,[7,2]*5)

    async def test_pv_loss_during_fresh_read_prevents_write(self):
        async def changed(*_):self.states['sensor.pv'].state='0';return deepcopy(self.row,{id(zinc.MARKER):zinc.MARKER})
        self.c.client.read_point.side_effect=changed
        with self.assertRaises(HomeAssistantError):await self.begin()
        self.assertEqual(self.writes,[])

    async def test_signed_kw_sources_block_battery_discharge(self):
        self.options.update(pv_charge_export_positive=False,pv_charge_discharge_positive=False)
        self.states['sensor.export'].state='-2.5';self.states['sensor.export'].attributes['unit_of_measurement']='kW'
        self.states['sensor.battery'].state='0.5';self.states['sensor.battery'].attributes['unit_of_measurement']='kW'
        await self.begin();self.states['sensor.battery'].state='-0.5';await self.m.async_tick()
        self.assertIsNone(self.m.lease);self.assertEqual(self.writes,[7,2])

    async def test_close_restores_and_cancels_deadline(self):
        await self.begin();await self.m.async_close()
        self.assertTrue(self.m.closed);self.assertIsNone(self.m.lease);self.assertEqual(self.writes,[7,2])

    async def test_manual_offset_write_cannot_bypass_lease(self):
        from test_controls_dashboard import coordinator
        c=coordinator();c.data={'point':live_offset()};c.buffer_charge=SimpleNamespace(lease={'phase':'charging'})
        with self.assertRaises(HomeAssistantError):await c.write('point',4)
        c.client.set_default.assert_not_awaited()

    async def test_binary_band_uses_confirmed_lease_and_unknown_during_restore(self):
        from custom_components.panasonic_cascade.charge_entities import BufferChargeActive
        entity=BufferChargeActive(self.c)
        self.assertFalse(entity.is_on)
        await self.begin();self.assertTrue(entity.is_on)
        self.m.lease['phase']='restore_pending';self.assertIsNone(entity.is_on)
        self.m.lease['phase']='charging';self.c.last_update_success=False;self.assertIsNone(entity.is_on)

    async def test_new_override_during_application_does_not_leave_latent_boost(self):
        normal=self.c.client.set_default.side_effect
        async def override_during_write(row,target):
            await normal(row,target)
            if target==7:self.row['curVal']=zinc.Number(3,'°C')
        self.c.client.set_default.side_effect=override_during_write
        with self.assertRaises(HomeAssistantError):await self.begin()
        self.assertEqual(self.writes,[7,2]);self.assertIsNone(self.m.lease)
        self.assertEqual(self.row['curVal'].value,3)

    async def test_hard_75_degree_limit_even_if_options_are_out_of_range(self):
        self.options['pv_charge_max_c']=90
        self.states['sensor.temperature'].state='75'
        with self.assertRaises(HomeAssistantError):await self.begin()
        self.assertEqual(self.writes,[])

    async def test_cooling_or_unknown_mode_blocks_charging(self):
        for mode in ['Cool', 'Auto', 'unknown']:
            self.mode['curVal']=mode
            with self.assertRaises(HomeAssistantError):await self.begin()
        self.assertEqual(self.writes,[])

    async def test_mode_change_during_charge_restores_original_offset(self):
        await self.begin();self.mode['curVal']='Cool';self.advance(16)
        await self.m.async_tick();self.assertIsNone(self.m.lease);self.assertEqual(self.writes,[7,2])

    async def test_source_event_during_controller_read_is_processed_after_read(self):
        await self.begin();self.advance(16)
        gate=asyncio.Event();entered=asyncio.Event()
        original=self.c.client.read_point.side_effect
        async def delayed(ident,*args):
            if ident=='mode':
                entered.set();await gate.wait()
            return original(ident,*args)
        self.c.client.read_point.side_effect=delayed
        self.hass.async_create_task=asyncio.create_task
        self.m.request_tick();await entered.wait()
        self.states['sensor.pv'].state='0';self.m.request_tick()
        gate.set();await asyncio.gather(*self.m.tasks)
        self.assertIsNone(self.m.lease);self.assertEqual(self.writes,[7,2])

class ChargeOptionsAndDashboardTest(unittest.IsolatedAsyncioTestCase):
    async def test_configuration_defaults_sources_confirmation_hysteresis_and_limit(self):
        from custom_components.panasonic_cascade.config_flow import CascadeOptionsFlow
        entry=SimpleNamespace(data={},options={'enable_controls':True})
        f=CascadeOptionsFlow();f.handler='entry';f.hass=Mock()
        f.hass.config_entries.async_get_known_entry.return_value=entry
        f.hass.services.async_services.return_value={'notify':{}}
        result=await f.async_step_init({'enable_controls':True,'configure_pv_charge':True})
        self.assertEqual(result['step_id'],'pv_charge')
        fields=result['data_schema']({})
        self.assertFalse(fields['pv_charge_enabled']);self.assertFalse(fields['pv_charge_auto'])
        self.assertEqual(fields['pv_charge_max_c'],75)
        import voluptuous as vol
        with self.assertRaises(vol.Invalid):result['data_schema']({'pv_charge_max_c':76})
        values={**charge.DEFAULTS,'pv_charge_enabled':True}
        bad=await f.async_step_pv_charge(values)
        self.assertEqual(bad['errors']['base'],'pv_charge_not_confirmed')
        values['pv_charge_confirmed']=True
        bad=await f.async_step_pv_charge(values)
        self.assertEqual(bad['errors']['base'],'pv_charge_missing_sources')
        for k in charge.SOURCE_KEYS:values[f'pv_charge_{k}_sensor']='sensor.'+k
        bad=await f.async_step_pv_charge({**values,'pv_charge_start_w':100,'pv_charge_stop_w':100})
        self.assertEqual(bad['errors']['base'],'pv_charge_thresholds')
        good=await f.async_step_pv_charge(values)
        self.assertEqual(good['type'],'create_entry');self.assertTrue(good['data']['enable_controls'])

    def test_prominent_active_fault_cards_and_24h_7day_history_preserve_existing_graphs(self):
        from test_controls_dashboard import DashboardTest,dashboard
        hass,registry,devices=DashboardTest().fixture()
        entry=SimpleNamespace(entry_id='one',unique_id='install',options={'pv_charge_enabled':True,
          'pv_charge_temperature_sensor':'sensor.buffer','pv_charge_pv_sensor':'sensor.pv'},runtime_data=SimpleNamespace(data={},buffer_charge=SimpleNamespace(lease=None)))
        hass.config_entries.async_entries.return_value=[entry]
        base=registry.entities['sensor.power']
        for ident,domain,suffix in [('sensor.charge','sensor','pv_buffer_charge'),('binary_sensor.charge','binary_sensor','pv_buffer_charge_active'),
                                    ('button.start','button','pv_buffer_charge_start'),('button.stop','button','pv_buffer_charge_stop')]:
            registry.entities[ident]=SimpleNamespace(**{**vars(base),'entity_id':ident,'domain':domain,'unique_id':'install|'+suffix,'original_name':suffix,'unit_of_measurement':None})
        with patch.object(dashboard.er,'async_get',return_value=registry),patch.object(dashboard.dr,'async_get',return_value=devices):
            generated=dashboard.build_dashboard(hass)
        overview=next(v for v in generated['views'] if v['path']=='overview')
        self.assertEqual([c['type'] for c in overview['cards'][:3]],['conditional','conditional','history-graph'])
        self.assertEqual(overview['cards'][2]['hours_to_show'],24)
        history=next(v for v in generated['views'] if v['path']=='pv-buffer')
        self.assertIn('168',str(history));self.assertIn('binary_sensor.charge',str(history))
        custom={'type':'history-graph','title':'My electricity','hours_to_show':72,'entities':['sensor.existing_energy']}
        original={'views':[{'path':'overview','cards':[custom]},{'path':'energy','cards':[custom]}]}
        updated=dashboard.merge_dashboard(original,generated)
        self.assertEqual(updated['views'][0]['cards'][0]['type'],'conditional')
        self.assertEqual(updated['views'][0]['cards'][1]['type'],'conditional')
        self.assertIn(custom,updated['views'][0]['cards'])
        self.assertEqual(updated['views'][1],original['views'][1])
        self.assertEqual(updated,dashboard.merge_dashboard(updated,generated))
