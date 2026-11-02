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


    async def test_sensorless_test_caps_duration_and_relative_raise_and_restores(self):
        self.options['pv_charge_test_without_temperature']=True
        del self.states['sensor.temperature']
        await self.begin(offset=10,duration=120)
        self.assertEqual(self.writes,[4])
        self.assertEqual(self.m.lease['expires'],self.t+300)
        self.assertTrue(self.store.data['lease']['temperature_unmonitored_test'])
        from custom_components.panasonic_cascade.charge_entities import BufferChargeSensor
        entity=BufferChargeSensor(self.c)
        self.assertEqual(entity.native_value,'Ladetest ohne Temperaturüberwachung')
        self.assertTrue(entity.extra_state_attributes['temperature_unmonitored_test'])
        self.assertIsNone(entity.extra_state_attributes['temperature_limit'])
        self.assertIsNone(entity.extra_state_attributes['buffer_temperature'])
        self.advance(301);del self.states['sensor.temperature']
        await self.m.async_tick()
        self.assertEqual(self.writes,[4,2]);self.assertIsNone(self.m.lease)

    async def test_sensorless_test_never_auto_starts_or_repeats(self):
        self.options.update(pv_charge_test_without_temperature=True,pv_charge_auto=True)
        del self.states['sensor.temperature']
        await self.m.async_tick();self.advance(121);await self.m.async_tick()
        self.assertEqual(self.writes,[])
        with self.assertRaises(HomeAssistantError):await self.begin()
        self.options['pv_charge_auto']=False
        await self.begin();await self.m.async_stop();self.advance(121);await self.m.async_tick()
        self.assertEqual(self.writes,[4,2])

    async def test_sensorless_test_keeps_all_power_and_freshness_guards(self):
        self.options['pv_charge_test_without_temperature']=True
        for key,bad in [('export','-1'),('battery','101'),('pv','0'),('pv','unknown')]:
            self.refresh();del self.states['sensor.temperature']
            self.states['sensor.'+key].state=bad
            with self.assertRaises(HomeAssistantError):await self.begin()
        self.refresh();del self.states['sensor.temperature'];self.t+=61
        with self.assertRaises(HomeAssistantError):await self.begin()
        self.assertEqual(self.writes,[])
        self.refresh();del self.states['sensor.temperature'];await self.begin()
        self.states['sensor.battery'].state='500';await self.m.async_tick()
        self.assertEqual(self.writes,[4,2])

    async def test_sensorless_test_does_not_weaken_existing_normal_charge(self):
        await self.begin();self.options['pv_charge_test_without_temperature']=True
        self.states['sensor.temperature'].state='75'
        await self.m.async_tick();self.assertEqual(self.writes,[7,2])

    async def test_sensorless_test_revocation_and_restart_restore(self):
        self.options['pv_charge_test_without_temperature']=True
        await self.begin();self.options['pv_charge_test_without_temperature']=False
        await self.m.async_tick();self.assertEqual(self.writes,[4,2])
        self.options['pv_charge_test_without_temperature']=True
        await self.begin();del self.states['sensor.temperature']
        new=charge.BufferCharge(self.c,self.store,clock=lambda:self.t)
        await new.async_initialize();self.assertIsNone(new.lease)
        self.assertEqual(self.writes,[4,2,4,2])

    async def test_sensorless_test_respects_live_upper_bound(self):
        self.options['pv_charge_test_without_temperature']=True
        self.row['maxVal']=zinc.Number(3,'°C')
        await self.begin();self.assertEqual(self.writes,[3])
        await self.m.async_stop()
        self.row['maxVal']=zinc.Number(2,'°C')
        with self.assertRaises(HomeAssistantError):await self.begin()
        self.assertEqual(self.writes,[3,2])


    async def test_priority_counts_charge_and_signed_grid_after_1000w_reserve(self):
        self.options.update(pv_charge_heat_pump_priority=True,pv_charge_export_positive=False,
                            pv_charge_discharge_positive=False)
        self.states['sensor.export'].state='7'
        self.states['sensor.battery'].state='7468'
        self.states['sensor.pv'].state='9255'
        data=self.m.readings()
        self.assertEqual(data['export'],-7)
        self.assertEqual(data['battery'],-7468)
        self.assertEqual(data['available'],6461)
        await self.begin();self.assertEqual(self.writes,[7])
        from custom_components.panasonic_cascade.charge_entities import BufferChargeSensor
        attrs=BufferChargeSensor(self.c).extra_state_attributes
        self.assertTrue(attrs['heat_pump_priority']);self.assertEqual(attrs['battery_reserve_w'],1000)
        self.assertEqual(attrs['available_surplus_w'],6461)

    async def test_priority_auto_starts_only_after_stable_available_surplus(self):
        self.options.update(pv_charge_heat_pump_priority=True,pv_charge_auto=True)
        self.states['sensor.export'].state='0';self.states['sensor.battery'].state='-4000'
        await self.m.async_tick();self.assertEqual(self.writes,[])
        self.advance(120);self.states['sensor.export'].state='0';self.states['sensor.battery'].state='-4000'
        await self.m.async_tick();self.assertEqual(self.writes,[5])

    async def test_priority_preserves_reserve_and_restores_when_budget_drops(self):
        self.options['pv_charge_heat_pump_priority']=True
        self.states['sensor.export'].state='0';self.states['sensor.battery'].state='-4000'
        await self.begin()
        self.states['sensor.battery'].state='-1800';await self.m.async_tick()
        self.assertIsNotNone(self.m.lease)
        self.states['sensor.battery'].state='-1200';await self.m.async_tick()
        self.assertEqual(self.writes,[7,2]);self.assertIsNone(self.m.lease)

    async def test_priority_supports_full_battery_via_grid_export(self):
        self.options['pv_charge_heat_pump_priority']=True
        self.states['sensor.export'].state='3000';self.states['sensor.battery'].state='0'
        self.assertEqual(self.m.readings()['available'],2000)
        await self.begin();self.assertEqual(self.writes,[7])

    async def test_priority_keeps_import_discharge_freshness_and_pv_guards(self):
        self.options['pv_charge_heat_pump_priority']=True
        for key,bad in [('export','-101'),('battery','101'),('pv','0'),('battery','unknown')]:
            self.refresh();self.states['sensor.'+key].state=bad
            with self.assertRaises(HomeAssistantError):await self.begin()
        self.refresh();self.t+=61
        with self.assertRaises(HomeAssistantError):await self.begin()
        self.assertEqual(self.writes,[])
        self.refresh();self.states['sensor.battery'].state='-4000'
        await self.begin();self.states['sensor.export'].state='-101'
        await self.m.async_tick();self.assertEqual(self.writes,[7,2])

    async def test_priority_cannot_claim_more_than_measured_pv_or_count_discharge(self):
        self.options['pv_charge_heat_pump_priority']=True
        self.states['sensor.export'].state='0';self.states['sensor.battery'].state='-10000'
        self.states['sensor.pv'].state='2000'
        self.assertEqual(self.m.readings()['available'],1000)
        with self.assertRaises(HomeAssistantError):await self.begin()
        self.states['sensor.export'].state='3000';self.states['sensor.battery'].state='50'
        self.states['sensor.pv'].state='6000'
        self.assertEqual(self.m.readings()['available'],1950)

    async def test_export_only_behavior_is_unchanged_without_priority(self):
        self.states['sensor.export'].state='-1';self.states['sensor.battery'].state='-5000'
        with self.assertRaises(HomeAssistantError):await self.begin()
        self.states['sensor.export'].state='0'
        self.assertEqual(self.m.readings()['available'],0)
        with self.assertRaises(HomeAssistantError):await self.begin()
        self.assertEqual(self.writes,[])

    async def test_priority_rejects_invalid_reserve_and_grid_tolerance(self):
        self.options['pv_charge_heat_pump_priority']=True
        for key,bad in [('pv_charge_battery_reserve_w',0),('pv_charge_battery_reserve_w',float('nan')),
                        ('pv_charge_grid_tolerance_w',101),('pv_charge_grid_tolerance_w',-1)]:
            old=self.options[key];self.options[key]=bad
            with self.assertRaises(HomeAssistantError):await self.begin()
            self.options[key]=old
        self.assertEqual(self.writes,[])

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

    async def test_sensorless_options_allow_only_missing_temperature_and_manual_start(self):
        from custom_components.panasonic_cascade.config_flow import CascadeOptionsFlow
        f=CascadeOptionsFlow();f.handler='entry';f.hass=Mock()
        f.hass.config_entries.async_get_known_entry.return_value=SimpleNamespace(data={},options={'enable_controls':True})
        values={**charge.DEFAULTS,'pv_charge_enabled':True,'pv_charge_confirmed':True,
                'pv_charge_test_without_temperature':True}
        for k in ('export','battery','pv'):values[f'pv_charge_{k}_sensor']='sensor.'+k
        result=await f.async_step_pv_charge(values)
        self.assertEqual(result['type'],'create_entry')
        bad=await f.async_step_pv_charge({**values,'pv_charge_auto':True})
        self.assertEqual(bad['errors']['base'],'pv_charge_test_manual_only')
        bad=await f.async_step_pv_charge({**values,'pv_charge_battery_sensor':''})
        self.assertEqual(bad['errors']['base'],'pv_charge_missing_sources')
        bad=await f.async_step_pv_charge({**values,'pv_charge_test_without_temperature':False})
        self.assertEqual(bad['errors']['base'],'pv_charge_missing_sources')

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


class ActiveStatusTest(unittest.IsolatedAsyncioTestCase):
    setUp = ChargeTest.setUp
    refresh = ChargeTest.refresh
    advance = ChargeTest.advance
    begin = ChargeTest.begin
    async def test_active_charge_refreshes_live_attributes_without_another_write(self):
        await self.begin()
        self.advance(15)
        with patch.object(self.m, 'changed') as changed:
            await self.m.async_tick()
            changed.assert_called_once()
        self.assertEqual(self.writes, [7])
        self.assertEqual(self.m.lease['phase'], 'charging')


class ContinuousAutomaticChargeTest(unittest.IsolatedAsyncioTestCase):
    setUp = ChargeTest.setUp
    refresh = ChargeTest.refresh
    advance = ChargeTest.advance

    async def start_auto(self):
        self.options.update(pv_charge_auto=True, pv_charge_heat_pump_priority=True)
        self.m.stable_since = self.t - 120
        await self.m._start(automatic=True)

    async def test_renew_before_boundary_without_restore_or_second_device_write(self):
        await self.start_auto()
        original_expiry = self.m.lease['expires']
        self.advance(25 * 60)
        await self.m.async_tick()
        self.assertEqual(self.m.lease['expires'], original_expiry + 30 * 60)
        self.assertEqual(self.store.data['lease']['expires'], self.m.lease['expires'])
        self.assertEqual(self.m.lease['extensions'], 1)
        self.assertEqual(self.writes, [5])
        self.advance(5 * 60)
        await self.m._deadline(None)
        self.assertEqual(self.writes, [5])
        self.assertEqual(self.m.lease['phase'], 'charging')

    async def test_successive_extensions_keep_original_baseline_and_no_off_on_pair(self):
        await self.start_auto()
        for seconds in [1500, 1800, 1800]:
            self.advance(seconds)
            await self.m.async_tick()
        self.assertEqual(self.m.lease['extensions'], 3)
        self.assertEqual(self.m.lease['baseline'], 2)
        self.assertEqual(self.writes, [5])
        await self.m.async_stop()
        self.assertEqual(self.writes, [5, 2])

    async def test_low_positive_margin_holds_request_for_30_minutes(self):
        await self.start_auto()
        self.advance(60)
        self.states['sensor.export'].state = '1200'  # 200 W beyond reserve.
        await self.m.async_tick()
        self.advance(28 * 60)
        self.states['sensor.export'].state = '1200'
        await self.m.async_tick()
        self.assertEqual(self.writes, [5])
        self.advance(60)
        self.states['sensor.export'].state = '1200'
        await self.m.async_tick()
        self.assertEqual(self.writes, [5, 2])

    async def test_short_low_margin_recovers_and_timer_resets(self):
        await self.start_auto()
        self.advance(31 * 60)
        await self.m.async_tick()  # Healthy feedback renews the current block.
        for _ in range(2):
            self.states['sensor.export'].state = '1200'
            await self.m.async_tick()
            self.advance(119)
            self.states['sensor.export'].state = '1200'
            await self.m.async_tick()
            self.assertIsNotNone(self.m.lease)
            self.refresh()
            await self.m.async_tick()
            self.assertIsNone(self.m.low_surplus_since)
        self.assertEqual(self.writes, [5])

    async def test_continuous_low_margin_stops_after_debounce_outside_hold(self):
        await self.start_auto()
        self.advance(31 * 60)
        await self.m.async_tick()
        self.states['sensor.export'].state = '1200'
        await self.m.async_tick()
        self.advance(120)
        self.states['sensor.export'].state = '1200'
        await self.m.async_tick()
        self.assertEqual(self.writes, [5, 2])

    async def test_low_margin_at_boundary_does_not_grant_another_full_block(self):
        await self.start_auto()
        self.advance(30 * 60)
        self.states['sensor.export'].state = '1200'
        await self.m._deadline(None)
        self.assertIsNotNone(self.m.lease)
        self.assertEqual(self.m.lease['extensions'], 0)
        self.assertEqual(self.writes, [5])
        self.advance(120)
        self.states['sensor.export'].state = '1200'
        await self.m._deadline(None)
        self.assertIsNone(self.m.lease)
        self.assertEqual(self.writes, [5, 2])

    async def test_all_hard_guards_override_minimum_hold_and_renewal(self):
        for key, raw in [('export', '-501'), ('battery', '101'), ('pv', '0'),
                         ('temperature', '75'), ('temperature', 'unknown'), ('export', '900')]:
            self.advance(720)
            await self.start_auto()
            self.states['sensor.' + key].state = raw
            await self.m.async_tick()
            self.assertIsNone(self.m.lease, (key, raw))
        self.assertEqual(self.writes, [5, 2] * 6)

    async def test_stale_temperature_at_renewal_restores_instead(self):
        await self.start_auto()
        self.advance(25 * 60)
        self.states['sensor.temperature'].last_reported = datetime.fromtimestamp(self.t - 61, UTC)
        await self.m.async_tick()
        self.assertIsNone(self.m.lease)
        self.assertEqual(self.writes, [5, 2])

    async def test_manual_charge_keeps_hard_expiry_even_with_auto_option(self):
        self.options['pv_charge_auto'] = True
        self.m.stable_since = self.t - 120
        await self.m.async_start(7, 1)
        self.advance(61)
        await self.m._deadline(None)
        self.assertIsNone(self.m.lease)
        self.assertEqual(self.writes, [7, 2])

    async def test_renewal_storage_failure_requests_restoration(self):
        await self.start_auto()
        original = self.m.lease['expires']
        self.store.fail = True
        self.advance(25 * 60)
        await self.m.async_tick()
        self.assertEqual(self.m.lease['expires'], original)
        self.assertEqual(self.m.lease['phase'], 'restore_pending')
        self.assertEqual(self.writes, [5, 2])

    async def test_restart_cooldown_is_persisted_and_requires_new_stable_surplus(self):
        await self.start_auto()
        await self.m.async_stop()
        until = self.m.restart_not_before
        self.assertEqual(until, self.t + 600)
        new = charge.BufferCharge(self.c, self.store, clock=lambda: self.t)
        await new.async_initialize()
        self.assertEqual(new.restart_not_before, until)
        self.advance(599)
        await new.async_tick()
        self.assertIsNone(new.stable_since)
        self.assertEqual(self.writes, [5, 2])
        self.advance(1)
        await new.async_tick()
        self.advance(119)
        await new.async_tick()
        self.assertEqual(self.writes, [5, 2])
        self.advance(1)
        await new.async_tick()
        self.assertEqual(self.writes, [5, 2, 5])

    async def test_reload_restores_renewed_lease_and_does_not_restart_immediately(self):
        await self.start_auto()
        self.advance(25 * 60)
        await self.m.async_tick()
        new = charge.BufferCharge(self.c, self.store, clock=lambda: self.t)
        await new.async_initialize()
        self.assertIsNone(new.lease)
        self.assertGreater(new.restart_not_before, self.t)
        self.assertEqual(self.writes, [5, 2])

    async def test_disabling_auto_prevents_any_more_extensions(self):
        await self.start_auto()
        self.options['pv_charge_auto'] = False
        self.advance(25 * 60)
        await self.m.async_tick()
        self.assertEqual(self.m.lease['extensions'], 0)
        self.advance(5 * 60)
        await self.m._deadline(None)
        self.assertIsNone(self.m.lease)
        self.assertEqual(self.writes, [5, 2])

    async def test_manual_stop_overrides_hold_and_status_exposes_request_timers(self):
        await self.start_auto()
        from custom_components.panasonic_cascade.charge_entities import BufferChargeSensor
        attrs = BufferChargeSensor(self.c).extra_state_attributes
        self.assertTrue(attrs['continuous_automatic_charge'])
        self.assertEqual(attrs['minimum_hold_remaining_minutes'], 30)
        self.assertEqual(attrs['extension_count'], 0)
        await self.m.async_stop()
        self.assertEqual(self.writes, [5, 2])
        self.assertEqual(BufferChargeSensor(self.c).extra_state_attributes['restart_cooldown_minutes'], 10)

    async def test_external_offset_at_renewal_is_preserved_as_conflict(self):
        await self.start_auto()
        self.advance(25 * 60)
        self.row.update(writeDef=zinc.Number(4, '°C'), curVal=zinc.Number(4, '°C'))
        await self.m.async_tick()
        self.assertEqual(self.m.lease['phase'], 'conflict')
        self.assertEqual(self.m.lease['extensions'], 0)
        self.assertEqual(self.writes, [5])

    async def test_short_configured_auto_block_does_not_shorten_minimum_hold(self):
        self.options['pv_charge_duration_min'] = 1
        await self.start_auto()
        self.assertEqual(self.m.lease['expires'] - self.t, 30 * 60)
        self.assertEqual(self.m.lease['minimum_until'] - self.t, 30 * 60)


class GridImportConfirmationTest(unittest.IsolatedAsyncioTestCase):
    setUp = ChargeTest.setUp
    refresh = ChargeTest.refresh
    advance = ChargeTest.advance
    start_auto = ContinuousAutomaticChargeTest.start_auto

    def importing(self, watts):
        self.states['sensor.export'].state = str(-watts)
        self.states['sensor.battery'].state = '-4000'

    async def test_replay_observed_53_to_67w_spikes_never_restores_offset(self):
        await self.start_auto()
        for watts in [65,62,64,67,53,57,61,60]:
            self.advance(30)
            self.importing(watts)
            await self.m.async_tick()
            self.assertIsNone(self.m.grid_import_since)
            self.assertEqual(self.m.lease['phase'],'charging')
        self.assertEqual(self.writes,[5])

    async def test_short_405w_spike_recovers_without_stop_or_counter_accumulation(self):
        await self.start_auto()
        for _ in range(2):
            self.importing(405)
            await self.m.async_tick()
            self.advance(59)
            self.importing(405)
            await self.m.async_tick()
            self.assertEqual(self.writes,[5])
            self.importing(0)
            await self.m.async_tick()
            self.assertIsNone(self.m.grid_import_since)
        from custom_components.panasonic_cascade.charge_entities import BufferChargeSensor
        self.assertEqual(BufferChargeSensor(self.c).extra_state_attributes['grid_import_confirmation_remaining_s'],0)

    async def test_sustained_import_stops_at_60_seconds_and_enforces_cooldown(self):
        await self.start_auto()
        self.importing(150)
        await self.m.async_tick()
        self.advance(59)
        self.importing(150)
        await self.m.async_tick()
        self.assertEqual(self.writes,[5])
        self.advance(1)
        self.importing(150)
        await self.m.async_tick()
        self.assertEqual(self.writes,[5,2])
        self.assertIsNone(self.m.lease)
        self.assertEqual(self.m.reason,'Sustained grid import confirmed')
        self.assertEqual(self.m.restart_not_before,self.t+600)

    async def test_more_than_500w_stops_immediately(self):
        await self.start_auto()
        self.importing(501)
        await self.m.async_tick()
        self.assertEqual(self.writes,[5,2])
        self.assertIsNone(self.m.lease)

    async def test_exact_100w_is_tolerated_500w_only_receives_confirmation(self):
        await self.start_auto()
        self.importing(100)
        await self.m.async_tick()
        self.assertIsNone(self.m.grid_import_since)
        self.importing(500)
        await self.m.async_tick()
        self.assertIsNotNone(self.m.grid_import_since)
        self.assertEqual(self.writes,[5])

    async def test_confirmation_never_permits_a_new_start_or_manual_test(self):
        self.options.update(pv_charge_auto=True,pv_charge_heat_pump_priority=True)
        self.m.stable_since=self.t-120
        self.importing(101)
        with self.assertRaises(HomeAssistantError):await self.m._start(automatic=True)
        self.assertEqual(self.writes,[])
        self.importing(0)
        await self.m.async_start(7,10)  # Explicit manual action, despite auto option.
        self.importing(101)
        await self.m.async_tick()
        self.assertEqual(self.writes,[7,2])
        self.options['pv_charge_test_without_temperature']=True
        self.options['pv_charge_auto']=False
        self.importing(101)
        with self.assertRaises(HomeAssistantError):await self.m.async_start()

    async def test_other_guards_override_confirmation_and_hold(self):
        for key,raw in [('temperature','75'),('temperature','unknown'),('battery','101'),('pv','0'),('battery','-1200')]:
            self.advance(720)
            await self.start_auto()
            self.importing(405)
            await self.m.async_tick()
            self.states['sensor.'+key].state=raw
            await self.m.async_tick()
            self.assertIsNone(self.m.lease,(key,raw))
        self.assertEqual(self.writes,[5,2]*5)

    async def test_stale_feedback_overrides_pending_confirmation(self):
        await self.start_auto()
        self.importing(405)
        await self.m.async_tick()
        self.states['sensor.temperature'].last_reported=datetime.fromtimestamp(self.t-61,UTC)
        await self.m.async_tick()
        self.assertEqual(self.writes,[5,2])

    async def test_pending_confirmation_never_renews_a_30_minute_block(self):
        await self.start_auto()
        original=self.m.lease['expires']
        self.advance(25*60)
        self.importing(405)
        await self.m.async_tick()
        self.assertEqual(self.m.lease['expires'],original)
        self.assertEqual(self.m.lease['extensions'],0)
        self.importing(0)
        await self.m.async_tick()
        self.assertEqual(self.m.lease['expires'],original+1800)
        self.assertEqual(self.writes,[5])

    async def test_at_block_boundary_only_remaining_confirmation_is_granted(self):
        await self.start_auto()
        self.advance(30*60)
        self.importing(405)
        await self.m._deadline(None)
        self.assertEqual(self.m.lease['expires'],self.t+60)
        self.assertEqual(self.m.lease['extensions'],0)
        self.advance(60)
        self.importing(405)
        await self.m._deadline(None)
        self.assertEqual(self.writes,[5,2])

    async def test_reload_restores_offset_without_resuming_grace(self):
        await self.start_auto()
        self.importing(405)
        await self.m.async_tick()
        new=charge.BufferCharge(self.c,self.store,clock=lambda:self.t)
        await new.async_initialize()
        self.assertIsNone(new.grid_import_since)
        self.assertIsNone(new.lease)
        self.assertEqual(self.writes,[5,2])

    async def test_invalid_confirmation_limits_rejected_before_write(self):
        self.options['pv_charge_heat_pump_priority']=True
        for key,raw in [('pv_charge_grid_confirm_s',0),('pv_charge_grid_confirm_s',121),
                        ('pv_charge_grid_hard_limit_w',501),('pv_charge_grid_hard_limit_w',99)]:
            old=self.options[key]
            self.options[key]=raw
            self.m.stable_since=self.t-120
            with self.assertRaises(HomeAssistantError):await self.m._start(automatic=True)
            self.options[key]=old
        self.assertEqual(self.writes,[])
