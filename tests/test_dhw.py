"""DHW filtering, reversible registry visibility, and existing dashboard updates."""
import importlib
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock, Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
try:
    model = importlib.import_module('custom_components.panasonic_cascade.model')
    visibility = importlib.import_module('custom_components.panasonic_cascade.visibility')
    coordinator_module = importlib.import_module('custom_components.panasonic_cascade.coordinator')
    flow_module = importlib.import_module('custom_components.panasonic_cascade.config_flow')
    zinc = importlib.import_module('custom_components.panasonic_cascade.zinc')
    from homeassistant.core import HomeAssistant
    from homeassistant.helpers import entity_registry as er
    from homeassistant.components.lovelace.const import LOVELACE_DATA
    from homeassistant.components.lovelace.dashboard import LovelaceStorage
except ImportError:
    model = None


def rows():
    return {
        'tank': {'id':zinc.Ref('tank'), 'tankModelId':'_equip:tank', 'equip':zinc.MARKER, 'run':True},
        'dhw': {'id':zinc.Ref('dhw'), 'tankModelId':'_equip:tank_point:stopRun', 'point':zinc.MARKER, 'kind':'Bool'},
        'child': {'id':zinc.Ref('child'), 'equipRef':zinc.Ref('tank'), 'point':zinc.MARKER, 'kind':'Number'},
        'cop': {'id':zinc.Ref('cop'), 'heatPumpModelId':'_equip:heatPump_point:dhwModeCop', 'point':zinc.MARKER, 'kind':'Number'},
        'steril': {'id':zinc.Ref('steril'), 'siteModelId':'_site:sterilizationSchedule', 'point':zinc.MARKER, 'kind':'Str'},
        'buffer': {'id':zinc.Ref('buffer'), 'bufferModelId':'_equip:buffer_point:tBufferTank', 'point':zinc.MARKER, 'kind':'Number'},
        'heat': {'id':zinc.Ref('heat'), 'heatPumpModelId':'_equip:heatPump_point:hotModeCop', 'point':zinc.MARKER, 'kind':'Number'},
        'pump': {'id':zinc.Ref('pump'), 'heatPumpModelId':'_equip:heatPump', 'equip':zinc.MARKER, 'isAvailableTank':True, 'isRunning':True},
    }


@unittest.skipIf(model is None, 'Home Assistant required')
class DhwTest(unittest.IsolatedAsyncioTestCase):
    def test_classification_keeps_heating_buffer_and_shared_heat_pump(self):
        raw = rows()
        filtered = model.visible_data(raw, False)
        self.assertEqual(set(filtered), {'buffer','heat','pump'})
        self.assertNotIn('isAvailableTank', filtered['pump'])
        self.assertTrue(filtered['pump']['isRunning'])
        self.assertTrue(raw['pump']['isAvailableTank'])
        self.assertIs(model.visible_data(raw), raw)
        self.assertFalse(model.is_dhw({"heatPumpModelId":"_equip:heatPump_point:heatDhwMode"}))
        self.assertFalse(model.is_dhw({'id':zinc.Ref('one'), 'equipRef':zinc.Ref('one')}, rows={'one':{'equipRef':zinc.Ref('one')}}))

    async def test_coordinator_filters_before_all_platforms_and_never_writes(self):
        c = object.__new__(coordinator_module.CascadeCoordinator)
        c.entry = SimpleNamespace(data={'site_id':'site'}, options={'use_dhw':False})
        c.client = Mock(snapshot=AsyncMock(return_value=rows()), set_default=AsyncMock())
        filtered = await c._async_update_data()
        self.assertEqual(set(filtered), {'buffer','heat','pump'})
        self.assertIn('dhw', c.all_data)
        c.client.set_default.assert_not_awaited()
        for domain in ('sensor','binary_sensor','switch','number','select'):
            module = importlib.import_module('custom_components.panasonic_cascade.'+domain)
            c.data = filtered
            entry = SimpleNamespace(options={'enable_controls':True}, runtime_data=c)
            added = Mock()
            with patch.object(module, 'Cascade'+{'sensor':'Sensor','binary_sensor':'BinarySensor','switch':'Switch','number':'Number','select':'Select'}[domain], side_effect=lambda *args: args):
                await module.async_setup_entry(Mock(), entry, added)
            if added.called:
                for args in added.call_args.args[0]:
                    self.assertNotIn(args[1], {'tank','dhw','child','cop','steril'})
                    self.assertNotIn('isAvailableTank', args[2:])

    def test_native_cards_and_custom_controls_are_preserved(self):
        config = {'views':[{'title':'Heating','cards':[
            {'type':'entities','entities':['sensor.dhw',{'entity':'switch.dhw'},'sensor.buffer']},
            {'type':'history-graph','entities':[{'entity':'sensor.dhw'}]},
            {'type':'grid','cards':[{'type':'tile','entity':'switch.dhw'},{'type':'gauge','entity':'sensor.buffer'}]},
            {'type':'markdown','content':'My own notes'},
            {'type':'conditional','conditions':[], 'card':{'type':'tile','entity':'switch.dhw'}}], 'badges':['sensor.dhw','sensor.buffer']} ]}
        hidden = {'sensor.dhw','switch.dhw'}
        filtered = visibility.without_dhw(config, hidden)
        self.assertNotIn('sensor.dhw', str(filtered))
        self.assertNotIn('switch.dhw', str(filtered))
        self.assertIn('sensor.buffer', str(filtered))
        self.assertIn('My own notes', str(filtered))
        self.assertIn('sensor.dhw', str(config))
        self.assertEqual(len(filtered['views'][0]['cards']), 3)

    async def fixture(self, directory, default_dashboard=False):
        hass = HomeAssistant(directory)
        entry = SimpleNamespace(entry_id='test-entry', unique_id='url|project|site', options={'use_dhw':False})
        def entity(ident, field='curVal', **kwargs):
            return SimpleNamespace(entity_id='sensor.'+ident+'_'+field, unique_id=entry.unique_id+'|'+ident+'|'+field,
                                   platform='panasonic_cascade', config_entry_id=entry.entry_id,
                                   disabled_by=kwargs.get('disabled_by'), hidden_by=kwargs.get('hidden_by'))
        items = [entity('dhw'), entity('buffer'), entity('pump','isAvailableTank'), entity('cop', disabled_by=er.RegistryEntryDisabler.USER)]
        registry = SimpleNamespace(entities={e.entity_id:e for e in items})
        def update(ident, **changes):
            e = registry.entities[ident]
            for key, val in changes.items():setattr(e, key, val)
            return e
        registry.async_update_entity = Mock(side_effect=update)
        target = LovelaceStorage(hass, None if default_dashboard else {'id':'cascade-test', 'url_path':'cascade-test'})
        path = None if default_dashboard else 'cascade-test'
        hass.data[LOVELACE_DATA] = SimpleNamespace(dashboards={path:target})
        original = {'views':[{'cards':[{'type':'entities', 'entities':['sensor.dhw_curVal','sensor.buffer_curVal']}]}]}
        await target.async_save(original)
        return hass, entry, registry, target, original

    async def test_disable_restore_persisted_state_and_keep_user_disabler(self):
        with tempfile.TemporaryDirectory() as directory:
            hass, entry, registry, target, original = await self.fixture(directory)
            with patch.object(visibility.er,'async_get',return_value=registry):
                await visibility.async_apply_dhw_visibility(hass, entry, rows())
                self.assertEqual(registry.entities['sensor.dhw_curVal'].disabled_by, er.RegistryEntryDisabler.INTEGRATION)
                self.assertEqual(registry.entities['sensor.cop_curVal'].disabled_by, er.RegistryEntryDisabler.USER)
                self.assertEqual(registry.entities['sensor.pump_isAvailableTank'].hidden_by, er.RegistryEntryHider.INTEGRATION)
                self.assertIsNone(registry.entities['sensor.buffer_curVal'].disabled_by)
                self.assertNotIn('sensor.dhw_curVal', str(await target.async_load(False)))
                # Repeat from persisted storage, including controller point disappearing.
                await visibility.async_apply_dhw_visibility(hass, entry, {'buffer':rows()['buffer']})
                entry.options['use_dhw'] = True
                await visibility.async_apply_dhw_visibility(hass, entry, rows())
                self.assertIsNone(registry.entities['sensor.dhw_curVal'].disabled_by)
                self.assertIsNone(registry.entities['sensor.dhw_curVal'].hidden_by)
                self.assertEqual(registry.entities['sensor.cop_curVal'].disabled_by, er.RegistryEntryDisabler.USER)
                self.assertEqual(await target.async_load(False), original)
            await hass.async_stop()

    async def test_default_dashboard_backup_roundtrip(self):
        with tempfile.TemporaryDirectory() as directory:
            hass, entry, registry, target, original = await self.fixture(directory, True)
            with patch.object(visibility.er,'async_get',return_value=registry):
                await visibility.async_apply_dhw_visibility(hass, entry, rows())
                entry.options['use_dhw'] = True
                await visibility.async_apply_dhw_visibility(hass, entry, rows())
                self.assertEqual(await target.async_load(False), original)
            await hass.async_stop()

    async def test_dashboard_edits_and_user_disable_are_not_overwritten(self):
        with tempfile.TemporaryDirectory() as directory:
            hass, entry, registry, target, original = await self.fixture(directory)
            with patch.object(visibility.er,'async_get',return_value=registry):
                await visibility.async_apply_dhw_visibility(hass, entry, rows())
                custom = {'views':[{'cards':[{'type':'markdown', 'content':'New personal dashboard'}]}]}
                await target.async_save(custom)
                registry.entities['sensor.dhw_curVal'].disabled_by = er.RegistryEntryDisabler.USER
                entry.options['use_dhw'] = True
                await visibility.async_apply_dhw_visibility(hass, entry, rows())
                self.assertEqual(await target.async_load(False), custom)
                self.assertEqual(registry.entities['sensor.dhw_curVal'].disabled_by, er.RegistryEntryDisabler.USER)
            await hass.async_stop()

    async def test_options_default_enabled_and_persistence(self):
        f = flow_module.CascadeOptionsFlow()
        f.handler = 'test-entry'
        f.hass = Mock()
        f.hass.config_entries.async_get_known_entry.return_value = SimpleNamespace(data={}, options={'scan_interval':45,'internal':'keep'})
        form = await f.async_step_init()
        self.assertTrue(form['data_schema']({'scan_interval':45,'enable_controls':False,'verify_ssl':True})['use_dhw'])
        result = await f.async_step_init({'use_dhw':False, 'scan_interval':45, 'enable_controls':True, 'verify_ssl':True})
        self.assertFalse(result['data']['use_dhw'])
        self.assertEqual(result['data']['internal'], 'keep')
