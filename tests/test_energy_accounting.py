"""Source provenance is a labelled allocation; integration never fills unknown gaps."""
import math
import unittest
from datetime import datetime
from zoneinfo import ZoneInfo
from copy import deepcopy
from custom_components.panasonic_cascade.energy_accounting import allocate, Ledger, period_keys

TZ = ZoneInfo('Europe/Berlin')

def stamp(text):
    return datetime.fromisoformat(text).replace(tzinfo=TZ).timestamp()


class AllocationTest(unittest.TestCase):
    def test_pv_export_and_battery_charge_are_not_assigned_to_wp(self):
        self.assertEqual(allocate(2000,10000,4000,-2000), {'pv':2000,'grid':0,'battery':0})

    def test_night_grid_only(self):
        self.assertEqual(allocate(2000,0,-5000,0), {'pv':0,'grid':2000,'battery':0})

    def test_battery_provenance_is_not_claimed_as_solar(self):
        self.assertEqual(allocate(2000,0,0,4000), {'pv':0,'grid':0,'battery':2000})

    def test_mixed_household_supply_is_proportional_and_conserves_wp_power(self):
        result = allocate(3000,2000,-3000,1000)
        self.assertEqual(result, {'pv':1000,'grid':1500,'battery':500})
        self.assertEqual(sum(result.values()), 3000)

    def test_grid_charging_battery_is_an_assumption_not_battery_discharge(self):
        self.assertEqual(allocate(2000,0,-5000,-3000), {'pv':0,'grid':2000,'battery':0})

    def test_zero_is_real_zero_but_invalid_measurements_are_not(self):
        self.assertEqual(allocate(0,0,0,0),dict(pv=0,grid=0,battery=0))
        for args in [(1000,0,0,0),(5000,100,0,0),(1,-1,0,0),(1,math.nan,0,0),(True,1000,0,0),(1,0,math.inf,0)]:
            with self.assertRaises(ValueError): allocate(*args)


class PriorityAllocationTest(unittest.TestCase):
    def test_pv_then_battery_then_actual_grid(self):
        self.assertEqual(allocate(3000,1000,-1000,1500,policy='wp_priority'),
                         dict(pv=1000,battery=1500,grid=500))
        self.assertEqual(allocate(1000,2000,-1000,1000,policy='wp_priority'),
                         dict(pv=1000,battery=0,grid=0))

    def test_recorded_discrepancy_never_becomes_invented_grid(self):
        result=allocate(3070,0,-10,2595,policy='wp_priority')
        self.assertEqual(result,dict(pv=0,battery=2595,grid=10))
        self.assertEqual(3070-sum(result.values()),465)
        self.assertEqual(allocate(2969,0,-36,804,policy='wp_priority'),
                         dict(pv=0,battery=804,grid=36))

    def test_battery_cutoff_uses_measured_discharge_not_a_guessed_soc(self):
        self.assertEqual(allocate(3000,500,-2500,0,policy='wp_priority'),
                         dict(pv=500,battery=0,grid=2500))
        self.assertEqual(allocate(3000,0,0,0,policy='wp_priority'),dict(pv=0,battery=0,grid=0))

    def test_export_and_grid_charging_are_not_available_to_wp(self):
        self.assertEqual(allocate(3000,0,1000,4000,policy='wp_priority'),
                         dict(pv=0,battery=3000,grid=0))
        self.assertEqual(allocate(4000,0,-5000,-3000,policy='wp_priority'),
                         dict(pv=0,battery=0,grid=2000))
        with self.assertRaises(ValueError):allocate(1000,0,-1000,0,'cascade','wp_priority')
        with self.assertRaises(ValueError):allocate(1000,0,-1000,0,policy='typo')


class LedgerTest(unittest.TestCase):
    def test_watts_to_kwh_and_sum_sources(self):
        ledger=Ledger(TZ);t=stamp('2026-11-01T12:00:00')
        for second in range(0,3601,15):ledger.update(t+second,dict(pv=1000,grid=500,battery=250))
        self.assertAlmostEqual(ledger.total['pv'],1)
        self.assertAlmostEqual(ledger.total['grid'],.5)
        self.assertAlmostEqual(ledger.periods['day']['energy']['battery'],.25)
        self.assertEqual(ledger.periods['day']['observed_seconds'],3600)

    def test_unknown_feedback_and_large_gaps_are_not_integrated(self):
        ledger=Ledger(TZ);t=stamp('2026-11-01T12:00:00');p=dict(pv=3600,grid=0,battery=0)
        ledger.update(t,p);ledger.update(t+15,None);ledger.update(t+30,p)
        self.assertEqual(ledger.total['pv'],0)
        ledger.update(t+45,p);self.assertAlmostEqual(ledger.total['pv'],.015)
        ledger.update(t+1000,p);self.assertAlmostEqual(ledger.total['pv'],.015)

    def test_restart_restores_totals_without_integrating_downtime(self):
        ledger=Ledger(TZ);t=stamp('2026-11-01T12:00:00');p=dict(pv=3600,grid=0,battery=0)
        ledger.update(t,p);ledger.update(t+60,p)
        new=Ledger(TZ,deepcopy(ledger.dump()));new.update(t+3600,p)
        self.assertAlmostEqual(new.total['pv'],.06)
        new.update(t+3615,p);self.assertAlmostEqual(new.total['pv'],.075)

    def test_midnight_month_year_and_week_rollover_preserve_lifetime_energy(self):
        ledger=Ledger(TZ);t=stamp('2026-12-31T23:59:30');p=dict(pv=3600,grid=0,battery=0)
        ledger.update(t,p);ledger.update(t+60,p)
        self.assertAlmostEqual(ledger.total['pv'],.06)
        self.assertAlmostEqual(ledger.periods['day']['energy']['pv'],.03)
        self.assertAlmostEqual(ledger.periods['month']['energy']['pv'],.03)
        self.assertAlmostEqual(ledger.periods['year']['energy']['pv'],.03)
        self.assertAlmostEqual(ledger.periods['week']['energy']['pv'],.06)
        self.assertEqual(ledger.periods['week']['key'],'2026-W53')

    def test_monday_starts_new_week(self):
        ledger=Ledger(TZ);t=stamp('2026-11-01T23:59:30');p=dict(pv=3600,grid=0,battery=0)
        ledger.update(t,p);ledger.update(t+60,p)
        self.assertAlmostEqual(ledger.periods['week']['energy']['pv'],.03)
        self.assertEqual(ledger.periods['week']['key'],'2026-W45')

    def test_dst_days_use_elapsed_seconds_not_assumed_24_hours(self):
        for date,hours in [('2026-03-29',23),('2026-10-25',25)]:
            ledger=Ledger(TZ);t=stamp(date+'T00:00:00');p=dict(pv=1000,grid=0,battery=0)
            for sec in range(0,hours*3600+1,60):ledger.update(t+sec,p)
            self.assertAlmostEqual(ledger.total['pv'],hours,places=7)
            self.assertEqual(ledger.periods['day']['energy']['pv'],0)

    def test_calendar_rollover_even_when_measurements_are_missing(self):
        ledger=Ledger(TZ);t=stamp('2026-11-01T23:59:00');p=dict(pv=3600,grid=0,battery=0)
        ledger.update(t,p);ledger.update(t+30,p);ledger.update(t+120,None)
        self.assertAlmostEqual(ledger.total['pv'],.03)
        self.assertEqual(ledger.periods['day']['energy']['pv'],0)
        self.assertEqual(ledger.periods['day']['observed_seconds'],0)

class EnergyDashboardTest(unittest.TestCase):
    def test_all_source_periods_and_graphs_are_added_without_losing_existing_cards(self):
        from test_controls_dashboard import DashboardTest, dashboard
        from types import SimpleNamespace
        from unittest.mock import patch
        hass, registry, devices = DashboardTest().fixture()
        hass.config_entries.async_entries.return_value=[SimpleNamespace(entry_id='one',unique_id='install',title='WP',options={},runtime_data=SimpleNamespace(data={}))]
        base=registry.entities['sensor.power']
        for source in ('pv','grid','battery'):
            for period in ('power','total','day','week','month','year'):
                ident=f'sensor.source_{source}_{period}'
                registry.entities[ident]=SimpleNamespace(**{**vars(base),'entity_id':ident,'domain':'sensor',
                    'unique_id':f'install|energy_source:{source}:{period}','original_name':source,
                    'unit_of_measurement':'W' if period=='power' else 'kWh'})
        with patch.object(dashboard.er,'async_get',return_value=registry),patch.object(dashboard.dr,'async_get',return_value=devices):
            config=dashboard.build_dashboard(hass)
        energy=next(v for v in config['views'] if v['path']=='energy')
        cards=[c for v in config['views'] if v['path'].startswith('energy') for c in v.get('cards',[])]
        source_cards=[c for c in cards if c.get('title','').startswith('WP · Stromherkunft')]
        self.assertEqual(len(source_cards),8)
        self.assertTrue(any(c.get('title')=='Stromherkunft · Bilanz' for c in cards))
        self.assertTrue(all(len(c['entities'])==3 for c in source_cards if 'entities' in c))
        self.assertEqual({c['period'] for c in source_cards if c['type']=='statistics-graph'}, {'hour','day','week','month','year'})
        for card in source_cards:
            if card['type']=='statistics-graph':
                self.assertTrue(all(row['entity'].endswith('_total') for row in card['entities']))
        custom={'type':'history-graph','title':'My custom graph','entities':['sensor.custom'],'hours_to_show':48}
        old={'views':[{'path':'energy','cards':[custom]},{'path':'runtime','cards':[custom]}]}
        merged=dashboard.merge_dashboard(old,config)
        self.assertIn(custom,merged['views'][0]['cards'])
        self.assertIn(custom,merged['views'][1]['cards'])
        self.assertEqual(merged,dashboard.merge_dashboard(merged,config))

class SourceMappingAndPowerTest(unittest.TestCase):
    def test_existing_pv_mappings_are_reused_but_energy_overrides_are_independent(self):
        from custom_components.panasonic_cascade.energy_sources import mapping
        options={'pv_charge_export_sensor':'sensor.old','pv_charge_export_positive':False,
                 'energy_battery_sensor':'sensor.battery'}
        self.assertEqual(mapping(options,'export_sensor'),'sensor.old')
        self.assertFalse(mapping(options,'export_positive',True))
        self.assertEqual(mapping(options,'battery_sensor'),'sensor.battery')
        options['energy_export_sensor']='sensor.new'
        self.assertEqual(mapping(options,'export_sensor'),'sensor.new')
        self.assertEqual(options['pv_charge_export_sensor'],'sensor.old')

    def test_no_double_counting_of_plant_and_unit_power_or_partial_unit_fallback(self):
        from custom_components.panasonic_cascade.energy_sources import wp_power
        from custom_components.panasonic_cascade.zinc import Number
        def point(value,unit='kW'):return {'curVal':Number(value,unit),'unit':unit,'curStatus':'ok'}
        rows={'summary:consumedPower':point(3),'a':{'heatPump':True},'b':{'heatPump':True},
              'summary:unit:a:consumedPower':point(1000,'W'),'summary:unit:b:consumedPower':point(2)}
        self.assertEqual(wp_power(rows),3000)
        # Use actual model-key fixture tags rather than silently summing arbitrary registers.
        from unittest.mock import patch
        with patch('custom_components.panasonic_cascade.energy_sources.model_key',side_effect=lambda r:'heatPump' if r.get('heatPump') else ''):
            del rows['summary:consumedPower']
            self.assertEqual(wp_power(rows),3000)
            del rows['summary:unit:b:consumedPower']
            with self.assertRaises(ValueError):wp_power(rows)

    def test_metering_freshness_units_signs_and_missing_values(self):
        from custom_components.panasonic_cascade.energy_sources import SourceAccounting
        from custom_components.panasonic_cascade.zinc import Number
        from types import SimpleNamespace
        from datetime import UTC
        now=stamp('2026-11-01T18:00:00')
        states={}
        for key,raw in [('pv','0'),('export','2'),('battery','0')]:
            states['sensor.'+key]=SimpleNamespace(state=raw,attributes={'unit_of_measurement':'kW'},last_reported=datetime.fromtimestamp(now,UTC))
        m=object.__new__(SourceAccounting)
        m.options={**{f'pv_charge_{key}_sensor':'sensor.'+key for key in ('pv','export','battery')},'pv_charge_export_positive':False,'pv_charge_discharge_positive':False}
        m.reported=now
        m.hass=SimpleNamespace(states=SimpleNamespace(get=states.get))
        m.c=SimpleNamespace(last_update_success=True,data={'summary:consumedPower':{'curVal':Number(1,'kW'),'unit':'kW','curStatus':'ok'}})
        self.assertEqual(m.sample(now),{'pv':0,'grid':1000,'battery':0})
        states['sensor.pv'].last_reported=datetime.fromtimestamp(now-91,UTC)
        with self.assertRaises(ValueError):m.sample(now)
        states['sensor.pv'].last_reported=datetime.fromtimestamp(now,UTC)
        states['sensor.export'].attributes['unit_of_measurement']='kWh'
        with self.assertRaises(ValueError):m.sample(now)
        states['sensor.export'].attributes['unit_of_measurement']='kW'
        states['sensor.export'].state='unknown'
        with self.assertRaises(ValueError):m.sample(now)
        states['sensor.export'].state='2'
        m.reported=now-61
        with self.assertRaises(ValueError):m.sample(now)

class CascadeAllocationTest(unittest.TestCase):
    def test_night_wp_is_outside_house_import_boundary(self):
        self.assertEqual(allocate(2504,0,-698,0,'cascade'),dict(pv=0,grid=2504,battery=0))

    def test_recorded_noon_case_only_house_export_supplies_wp(self):
        self.assertEqual(allocate(2508,5454,122,-961,'cascade'),dict(pv=122,grid=2386,battery=0))

    def test_export_above_wp_load_is_not_double_counted(self):
        self.assertEqual(allocate(4000,18000,14000,-1000,'cascade'),dict(pv=4000,grid=0,battery=0))

    def test_battery_and_mixed_export_keep_separate_provenance(self):
        self.assertEqual(allocate(2000,0,3000,4000,'cascade'),dict(pv=0,grid=0,battery=2000))
        result=allocate(2000,1000,1500,2000,'cascade')
        self.assertEqual(result,dict(pv=500,grid=500,battery=1000))
        self.assertEqual(sum(result.values()),2000)
        with self.assertRaises(ValueError):allocate(1000,100,3000,0,'cascade')
        with self.assertRaises(ValueError):allocate(1000,1000,0,0,'typo')

    def test_grid_only_cascade_does_not_require_fresh_inner_pv_or_battery(self):
        from custom_components.panasonic_cascade.energy_sources import SourceAccounting
        from custom_components.panasonic_cascade.zinc import Number
        from types import SimpleNamespace
        from datetime import UTC
        now=stamp('2026-11-03T00:30:00')
        m=object.__new__(SourceAccounting);m.options={'energy_topology':'cascade','energy_export_sensor':'sensor.grid','energy_export_positive':False};m.reported=now
        grid=SimpleNamespace(state='698',attributes={'unit_of_measurement':'W'},last_reported=datetime.fromtimestamp(now,UTC))
        m.hass=SimpleNamespace(states=SimpleNamespace(get=lambda eid:grid if eid=='sensor.grid' else None))
        m.c=SimpleNamespace(last_update_success=True,data={'summary:consumedPower':{'curVal':Number(2.504,'kW'),'curStatus':'ok'}})
        self.assertEqual(m.sample(now),dict(pv=0,grid=2504,battery=0))
        grid.state='-122'
        with self.assertRaises(ValueError):m.sample(now)  # Export needs PV/battery provenance.
        grid.state='698';grid.last_reported=datetime.fromtimestamp(now-100,UTC)
        with self.assertRaises(ValueError):m.sample(now)

    def test_periodic_save_is_not_postponed_forever_by_frequent_ticks(self):
        from custom_components.panasonic_cascade.energy_sources import SourceAccounting
        from unittest.mock import Mock,patch
        m=object.__new__(SourceAccounting);m.closed=False;m.save_pending=False;m.clock=Mock(return_value=1000);m.sample=Mock(return_value=dict(pv=1000,grid=0,battery=0));m.ledger=Ledger(TZ);m.store=Mock();m.hass=Mock();m.signal='test'
        with patch('custom_components.panasonic_cascade.energy_sources.async_dispatcher_send'):
            for t in range(1000,1060,5):m.clock.return_value=t;m.tick()
            self.assertEqual(m.store.async_delay_save.call_count,1)
            first=m.saved_snapshot();self.assertGreater(first['total']['pv'],0)
            m.clock.return_value=1065;m.tick()
            self.assertEqual(m.store.async_delay_save.call_count,2)

class PriorityFeedbackTest(unittest.TestCase):
    def test_live_signs_and_shortfall_are_exposed_with_source_caps(self):
        from custom_components.panasonic_cascade.energy_sources import SourceAccounting,SourceSensor
        from custom_components.panasonic_cascade.zinc import Number
        from types import SimpleNamespace
        from datetime import UTC
        now=stamp('2026-11-03T18:00:00')
        states={key:SimpleNamespace(state=str(value),attributes={'unit_of_measurement':'W'},last_reported=datetime.fromtimestamp(now,UTC)) for key,value in [('pv',0),('grid',10),('battery',-2595)]}
        m=object.__new__(SourceAccounting);m.options={'energy_topology':'shared','energy_allocation':'wp_priority','energy_pv_sensor':'pv','energy_export_sensor':'grid','energy_battery_sensor':'battery','energy_export_positive':False,'energy_discharge_positive':False};m.reported=now
        m.hass=SimpleNamespace(states=SimpleNamespace(get=states.get))
        m.c=SimpleNamespace(last_update_success=True,data={'summary:consumedPower':{'curVal':Number(3.07,'kW'),'curStatus':'ok'}},entry=SimpleNamespace(unique_id='install'))
        m.prefix='test|';m.revision='test';m.reason='';m.ledger=Ledger(TZ)
        result=m.sample(now)
        self.assertEqual(result,dict(pv=0,battery=2595,grid=10))
        self.assertEqual(m.feedback['unassigned_power_w'],465)
        attrs=SourceSensor(m,'grid','power').extra_state_attributes
        self.assertIn('unassigned',attrs['allocation_warning'])
        self.assertEqual(attrs['allocation_policy'],'wp_priority')
        states['battery'].state='unknown'
        with self.assertRaises(ValueError):m.sample(now)

class AccountingRevisionTest(unittest.IsolatedAsyncioTestCase):
    async def test_legacy_totals_are_archived_not_mixed_and_mapping_changes_isolate_series(self):
        import tempfile
        from types import SimpleNamespace
        from unittest.mock import Mock,patch
        from homeassistant.core import HomeAssistant
        from homeassistant.helpers.storage import Store
        from homeassistant.helpers import entity_registry as er
        from custom_components.panasonic_cascade.energy_sources import SourceAccounting
        with tempfile.TemporaryDirectory() as root:
            hass=HomeAssistant(root)
            entry=SimpleNamespace(entry_id='test',unique_id='install',options={
                'energy_topology':'cascade','energy_export_sensor':'sensor.grid','energy_pv_sensor':'sensor.pv','energy_battery_sensor':'sensor.battery'})
            c=SimpleNamespace(hass=hass,entry=entry,data={},last_update_success=True,async_add_listener=Mock(return_value=Mock()))
            old=SimpleNamespace(entity_id='sensor.old',platform='panasonic_cascade',config_entry_id='test',unique_id='install|energy_source:pv:total',hidden_by=None,disabled_by=None)
            other=SimpleNamespace(**{**vars(old),'entity_id':'sensor.other','config_entry_id':'another'})
            registry=SimpleNamespace(entities={e.entity_id:e for e in (old,other)})
            registry.async_update_entity=lambda eid,**kw:[setattr(registry.entities[eid],k,v) for k,v in kw.items()]
            await Store(hass,1,'panasonic_cascade.energy_sources.test').async_save({'total':{'pv':999}})
            manager=SourceAccounting(c)
            with patch('custom_components.panasonic_cascade.energy_sources.er.async_get',return_value=registry):
                await manager.initialize()
                self.assertEqual(manager.ledger.total,dict(pv=0,grid=0,battery=0))
                self.assertEqual(old.disabled_by,er.RegistryEntryDisabler.INTEGRATION)
                self.assertIsNone(other.disabled_by)
                manager.ledger.total['pv']=1
                await manager.close()
                reloaded=SourceAccounting(c);await reloaded.initialize()
                self.assertEqual(reloaded.prefix,manager.prefix)
                self.assertEqual(reloaded.ledger.total['pv'],1)
                await reloaded.close()
                entry.options={**entry.options,'energy_topology':'shared'}
                changed=SourceAccounting(c)
                self.assertNotEqual(changed.prefix,manager.prefix)
                entry.options={**entry.options,'energy_allocation':'wp_priority'}
                priority=SourceAccounting(c)
                self.assertNotEqual(priority.prefix,changed.prefix)
                self.assertNotEqual(priority.prefix,manager.prefix)
            await hass.async_stop()
