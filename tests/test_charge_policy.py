"""Adaptive policy, real protocol envelope and durable retarget recovery."""
import importlib
import unittest
from copy import deepcopy
from unittest.mock import AsyncMock, patch
import test_buffer_charge as fixtures
charge, zinc = fixtures.charge, fixtures.zinc
from test_api import client, Session, Response
from test_protocol import zinc as protocol_zinc
from test_buffer_offset import offset
policy = importlib.import_module('custom_components.panasonic_cascade.charge_policy')


class PolicyTest(unittest.TestCase):
    def test_lowest_affordable_start_and_tested_offset_envelope(self):
        self.assertEqual(policy.initial_target(20000,34,0,65),45)
        self.assertEqual(policy.initial_target(20000,29,0,65),45)
        self.assertEqual(policy.next_target(20000,60,29,0,65),60)  # 65 needs >31 K.
        with self.assertRaises(ValueError): policy.initial_target(2000,34,0,65)
        with self.assertRaises(ValueError): policy.initial_target(20000,34,0,75)

    def test_hysteresis_and_single_step_in_each_direction(self):
        self.assertEqual(policy.next_target(4999,45,34,0,65),45)
        self.assertEqual(policy.next_target(5000,45,34,0,65),50)
        self.assertEqual(policy.next_target(20000,45,34,0,65),50)
        self.assertEqual(policy.next_target(3750,50,34,0,65),50)
        self.assertEqual(policy.next_target(3749,50,34,0,65),45)
        self.assertEqual(policy.next_target(4000,65,34,0,65),60)
        for bad in (True, float('nan'), float('inf'), '34'):
            with self.assertRaises(ValueError):policy.initial_target(20000,bad,0,65)


class AdaptiveProtocolTest(unittest.IsolatedAsyncioTestCase):
    async def test_only_dedicated_buffer_extension_and_bounded_target(self):
        row=offset();row.update(minVal=protocol_zinc.Number(0,'°C'),maxVal=protocol_zinc.Number(10,'°C'))
        session=Session([Response()]);c=client(session)
        await c.set_pv_buffer_offset(row,31,34,65)
        expression=protocol_zinc.parse_grids(session.calls[0][1]['data'].decode())[0][0]['expr']
        self.assertEqual(expression,'pointSetDef(@p:demo:r:a, 31°C)')
        for args in ((32,33,65),(31,35,65),(31,34,75),(float('nan'),34,65),(True,34,65)):
            with self.assertRaises(ValueError):await c.set_pv_buffer_offset(row,*args)
        for change in ({'maxVal':protocol_zinc.Number(5,'°C')},{'heatPumpModelId':'echo'},{'writable':None}):
            modified=dict(row);modified.update(change)
            with self.assertRaises(ValueError):await c.set_pv_buffer_offset(modified,31,34,65)
        with self.assertRaises(ValueError):await c.set_default(row,31)
        self.assertEqual(len(session.calls),1)


class AdaptiveChargeTest(unittest.IsolatedAsyncioTestCase):
    refresh=fixtures.ChargeTest.refresh
    def setUp(self):
        fixtures.ChargeTest.setUp(self)
        self.options.update(pv_charge_adaptive=True,pv_charge_auto=True,pv_charge_max_c=65)
        self.zone=34;self.target_fault=None
        for ident,key in [('zone','zone1WaterTemperatureSetpoint'),('target','bufferSetpoint')]:
            self.c.data[ident]={'bufferModelId':'_equip:buffer_point:'+key}
        self.c.data['summary:consumedPower']={'curVal':zinc.Number(2,'kW'),'unit':'kW','curStatus':'ok'}
        async def read(ident,*_):
            if ident=='mode':return dict(self.mode)
            if ident in ('zone','target'):
                n=self.zone if ident=='zone' else self.target_fault if self.target_fault is not None else self.zone+self.row['curVal'].value
                return {'curStatus':'ok','curVal':zinc.Number(n,'°C')}
            return deepcopy(self.row,{id(zinc.MARKER):zinc.MARKER})
        self.c.client.read_point=AsyncMock(side_effect=read)
        async def write_adaptive(row,offset,*_):await self.c.client.set_default(row,offset)
        self.c.client.set_pv_buffer_offset=AsyncMock(side_effect=write_adaptive)
        self.enterContext(patch.object(charge.asyncio,'sleep',new=AsyncMock()))
        self.supply(14000)

    def supply(self,budget):
        self.refresh()
        self.states['sensor.pv'].state='20000'
        self.states['sensor.export'].state=str(budget-2000)
        self.m.controller_at=self.t

    def advance(self,seconds,budget=14000):
        self.t+=seconds;self.supply(budget)

    async def start(self):
        self.m.stable_since=self.t-121
        await self.m._start(automatic=True)

    async def test_slow_ramp_65_no_self_consumption_oscillation_and_restore(self):
        await self.start();self.assertEqual(self.writes,[11]);self.assertEqual(self.m.lease['target'],45)
        for target in (50,55,60,65):
            await self.m.async_tick()  # Candidate starts now, not at eligibility time.
            self.advance(299);await self.m.async_tick()
            self.assertNotEqual(self.m.lease['target'],target)
            self.advance(301);await self.m.async_tick()
            self.assertEqual(self.m.lease['target'],target)
        self.assertEqual(self.writes,[11,16,21,26,31])
        self.supply(10000);self.assertEqual(self.m.adaptive_budget(self.m.readings()),10000)
        await self.m.async_stop();self.assertEqual(self.writes[-1],2)

    async def test_cloud_fluctuations_do_not_retarget_and_low_budget_downgrades_slowly(self):
        await self.start();await self.m.async_tick();self.advance(601);await self.m.async_tick()
        self.assertEqual(self.m.lease['target'],50)
        self.advance(1,4000);await self.m.async_tick()  # Above 3750 hysteresis boundary.
        self.advance(700,4000);await self.m.async_tick();self.assertEqual(self.m.lease['target'],50)
        self.supply(3500);await self.m.async_tick()
        self.advance(119,3500);await self.m.async_tick();self.assertEqual(self.m.lease['target'],50)
        self.advance(1,3500);await self.m.async_tick();self.assertEqual(self.m.lease['target'],45)

    async def test_zone_shift_preserves_absolute_target_without_stage_reset(self):
        await self.start();changed=self.m.lease['stage_changed'];self.zone=35
        await self.m.async_tick()
        self.assertEqual(self.writes,[11,10]);self.assertEqual(self.m.lease['target'],45)
        self.assertEqual(self.m.lease['stage_changed'],changed)

    async def test_lost_retarget_response_restores_from_pending_value(self):
        await self.start();await self.m.async_tick();self.advance(601)
        normal=self.c.client.set_pv_buffer_offset.side_effect
        async def ambiguous(*args):await normal(*args);raise OSError('lost reply')
        self.c.client.set_pv_buffer_offset.side_effect=ambiguous
        await self.m.async_tick()
        self.assertIsNone(self.m.lease);self.assertEqual(self.writes,[11,16,2])

    async def test_restart_during_adjusting_restores_new_or_old_offset(self):
        await self.start()
        self.m.lease.update(phase='adjusting',pending_offset=16)
        await self.m.save()
        self.row.update(curVal=zinc.Number(16,'°C'),writeDef=zinc.Number(16,'°C'))
        new=charge.BufferCharge(self.c,self.store,clock=lambda:self.t)
        await new.async_initialize();self.assertIsNone(new.lease);self.assertEqual(self.writes,[11,2])

    async def test_temperature_battery_grid_stale_power_and_disable_restore(self):
        for situation in ('temperature','battery','grid','stale_power','disabled','target_overshoot'):
            with self.subTest(situation=situation):
                self.supply(14000);self.options['pv_charge_adaptive']=True;self.target_fault=None
                self.m.restart_not_before=0
                await self.start()
                if situation=='temperature':self.states['sensor.temperature'].state='65'
                if situation=='battery':self.states['sensor.battery'].state='101'
                if situation=='grid':self.states['sensor.export'].state='-501'
                if situation=='stale_power':self.m.controller_at=self.t-61
                if situation=='disabled':self.options['pv_charge_adaptive']=False
                if situation=='target_overshoot':self.target_fault=66
                await self.m.async_tick();self.assertIsNone(self.m.lease)
                self.assertEqual(self.writes[-1],2)

    async def test_unknown_power_and_changed_normal_target_never_start(self):
        self.c.data['summary:consumedPower']['curVal']=None
        with self.assertRaises(Exception):await self.start()
        self.assertEqual(self.writes,[])
        self.c.data['summary:consumedPower']['curVal']=zinc.Number(2,'kW');self.target_fault=40
        with self.assertRaises(Exception):await self.start()
        self.assertEqual(self.writes,[])

    async def test_target_unconfirmed_restores_without_further_increases(self):
        normal=self.c.client.set_pv_buffer_offset.side_effect
        async def no_target(*args):
            await normal(*args);self.target_fault=36
        self.c.client.set_pv_buffer_offset.side_effect=no_target
        with self.assertRaises(Exception):await self.start()
        self.assertIsNone(self.m.lease);self.assertEqual(self.writes,[11,2])

    async def test_pending_adjustment_storage_failure_does_not_write_new_target(self):
        await self.start();await self.m.async_tick();self.advance(601)
        self.store.fail=True
        await self.m.async_tick()
        self.assertEqual(self.writes,[11,2])  # Restore is attempted despite storage failure.
        self.store.fail=False;self.advance(16);await self.m.async_tick()
        self.assertIsNone(self.m.lease)

    async def test_external_offset_is_preserved_and_corrupt_ceiling_cannot_raise_limit(self):
        await self.start()
        self.row.update(writeDef=zinc.Number(15,'°C'),curVal=zinc.Number(15,'°C'))
        await self.m.async_tick();self.assertEqual(self.m.lease['phase'],'conflict')
        self.assertEqual(self.writes,[11])
        await self.m.async_acknowledge()
        self.options['pv_charge_max_c']=75
        self.states['sensor.temperature'].state='65'
        with self.assertRaises(ValueError):self.m.readings()

    async def test_grid_confirmation_does_not_increase_target(self):
        self.options.update(pv_charge_heat_pump_priority=True)
        await self.start();await self.m.async_tick();self.advance(601)
        self.states['sensor.export'].state='-405'
        self.states['sensor.battery'].state='-12000'
        await self.m.async_tick()
        self.assertEqual(self.writes,[11]);self.assertEqual(self.m.lease['target'],45)
        self.assertIsNotNone(self.m.grid_import_since)
        self.assertIsNone(self.m.stage_candidate)
