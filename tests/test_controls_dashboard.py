"""Zone preservation, real HA entity identity, and dashboard safety checks."""
import asyncio
import importlib
from pathlib import Path
import sys
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock, Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
try:
    model = importlib.import_module('custom_components.panasonic_cascade.model')
    zinc = importlib.import_module('custom_components.panasonic_cascade.zinc')
    switches = importlib.import_module('custom_components.panasonic_cascade.switch')
    dashboard = importlib.import_module('custom_components.panasonic_cascade.dashboard')
    coord = importlib.import_module('custom_components.panasonic_cascade.coordinator')
    from homeassistant.exceptions import HomeAssistantError
except ImportError:
    model = None


def zone(raw='On/On'):
    return {'id': zinc.Ref('p:demo:r:zone', '| Buffer | | Zone1-Zone2 On/Off |'),
            'bufferModelId': '_equip:buffer_point:zone1Zone2OnOffSetpoint',
            'kind': 'Str', 'writable': zinc.MARKER, 'actions': 'pointSetDef($self,$val)',
            'curStatus': 'ok', 'enum': 'Off/Off,On/Off,Off/On,On/On', 'curVal': raw, 'writeDef': raw}


def coordinator(raw='On/On'):
    c = object.__new__(coord.CascadeCoordinator)
    c.hass = Mock()
    c.entry = SimpleNamespace(unique_id='installation', title='Installation', data={'site_id':'site'},
                              entry_id='entry', options={'enable_controls': True}, async_start_reauth=Mock())
    c.client = SimpleNamespace(url='https://controller.invalid', project='demo',
                               read_point=AsyncMock(return_value=zone(raw)), set_default=AsyncMock())
    c.data = {'point': zone(raw)}
    c.last_update_success = True
    c._write_lock = asyncio.Lock()
    c.async_request_refresh = AsyncMock()
    return c


@unittest.skipIf(model is None, 'Home Assistant required')
class ControlsTest(unittest.IsolatedAsyncioTestCase):
    def test_names_and_existing_identity(self):
        c = coordinator()
        entity = switches.CascadeSwitch(c, 'point')
        self.assertEqual(entity.name, 'Buffer – Zone1-Zone2 On/Off – Standardwert')
        self.assertEqual(entity.unique_id, 'installation|point|curVal|control')
        self.assertEqual(model.name({'dis':' | Primary Loop | run | '}), 'Primary Loop – run')
        self.assertEqual(model.name({'dis':'| |'}), 'Cascade point')

    def test_zone_switch_effective_state(self):
        for raw in ('Off/Off', 'On/Off', 'Off/On', 'On/On'):
            c = coordinator(raw)
            entity = switches.CascadeZone1Switch(c, 'point')
            self.assertEqual(entity.is_on, raw.startswith('On/'))
            self.assertEqual(entity.unique_id, 'installation|point|curVal|zone1_control')
        c.data['point']['curVal'] = None
        self.assertIsNone(entity.is_on)

    def test_all_zone_combinations(self):
        for raw in ('Off/Off', 'On/Off', 'Off/On', 'On/On'):
            for enabled in (True, False):
                target = model.zone1_value(zone(raw), enabled)
                self.assertEqual(target.split('/')[1], raw.split('/')[1])
                self.assertEqual(target.split('/')[0], 'On' if enabled else 'Off')

    def test_unknown_status_and_overrides_refused(self):
        for changes in ({'curVal':None}, {'curStatus':'fault'}, {'writeDef':'Off/Off'},
                        {'enum':'On/On'}, {'writable':None}):
            row = zone(); row.update(changes)
            with self.assertRaises(ValueError):
                model.zone1_value(row, False)

    async def test_fresh_read_preserves_zone2(self):
        c = coordinator('On/Off')  # Stale cached Zone 2 is Off.
        c.client.read_point.return_value = zone('On/On')
        await c.write_zone1('point', False)
        c.client.read_point.assert_awaited_once_with('point', 'site')
        self.assertEqual(c.client.set_default.await_args.args[1], 'Off/On')
        c.async_request_refresh.assert_awaited_once()

    async def test_disabled_or_bad_state_never_writes(self):
        for situation in ('disabled', 'offline', 'override', 'unknown'):
            c = coordinator()
            if situation == 'disabled': c.entry.options['enable_controls'] = False
            if situation == 'offline': c.last_update_success = False
            if situation == 'override': c.client.read_point.return_value['writeDef'] = 'Off/On'
            if situation == 'unknown': c.client.read_point.return_value['curVal'] = 'Unexpected'
            with self.assertRaises(HomeAssistantError):
                await c.write_zone1('point', True)
            c.client.set_default.assert_not_awaited()

    async def test_concurrent_writes_are_serialized(self):
        c = coordinator()
        live = zone()
        events = []
        async def read(*args):
            events.append('read'); await asyncio.sleep(0); return live.copy()
        async def write(row, target):
            events.append('write'); await asyncio.sleep(0)
            live.update(curVal=target, writeDef=target)
        c.client.read_point.side_effect = read
        c.client.set_default.side_effect = write
        await asyncio.gather(c.write_zone1('point', False), c.write_zone1('point', True))
        self.assertEqual(events, ['read', 'write', 'read', 'write'])
        self.assertEqual(live['curVal'], 'On/On')

    async def test_setup_options_and_new_switch(self):
        c = coordinator(); added = Mock()
        c.entry.runtime_data = c
        await switches.async_setup_entry(c.hass, c.entry, added)
        self.assertEqual(len(added.call_args.args[0]), 1)
        self.assertIsInstance(added.call_args.args[0][0], switches.CascadeZone1Switch)
        c.entry.options['enable_controls'] = False
        added.reset_mock()
        await switches.async_setup_entry(c.hass, c.entry, added)
        added.assert_not_called()


@unittest.skipIf(model is None, 'Home Assistant required')
class DashboardTest(unittest.IsolatedAsyncioTestCase):
    def fixture(self):
        hass = Mock()
        hass.config_entries.async_entries.return_value = [SimpleNamespace(entry_id='one')]
        def entity(ident, domain, label, unit=None, **kwargs):
            return SimpleNamespace(entity_id=ident, domain=domain, name=None, original_name=label,
                                   platform='panasonic_cascade', config_entry_id='one', device_id='device',
                                   unit_of_measurement=unit, unique_id=ident, disabled=False, hidden=False, **kwargs)
        entities = [entity('sensor.user_renamed_2', 'sensor', '| Water Temp - Actual Value', '°C'),
                    entity('switch.zone_one', 'switch', 'Zone 1 – Ein/Aus'),
                    entity('sensor.power', 'sensor', 'Thermal power', 'kW')]
        registry = SimpleNamespace(entities={e.entity_id:e for e in entities})
        devices = SimpleNamespace(devices={'device':SimpleNamespace(name='| Tank |', name_by_user=None)})
        hass.states.get.return_value = None
        return hass, registry, devices

    def test_real_ids_and_clean_labels(self):
        hass, registry, devices = self.fixture()
        with patch.object(dashboard.er, 'async_get', return_value=registry), patch.object(dashboard.dr, 'async_get', return_value=devices):
            config = dashboard.build_dashboard(hass)
        text = str(config)
        self.assertIn('sensor.user_renamed_2', text)
        self.assertIn('switch.zone_one', text)
        self.assertIn('history-graph', text)
        self.assertNotIn('| Tank |', text)
        self.assertNotIn('| Water Temp', text)
        registry.entities['sensor.power'].disabled = True
        with patch.object(dashboard.er, 'async_get', return_value=registry), patch.object(dashboard.dr, 'async_get', return_value=devices):
            self.assertNotIn('sensor.power', str(dashboard.build_dashboard(hass)))
            with self.assertRaises(HomeAssistantError): dashboard.build_dashboard(hass, 'other')

    async def test_empty_dashboard_saved_and_existing_protected(self):
        from homeassistant.components.lovelace.const import LOVELACE_DATA
        from homeassistant.components.lovelace.dashboard import ConfigNotFound
        hass = Mock()
        target = SimpleNamespace(mode='storage', async_load=AsyncMock(side_effect=ConfigNotFound), async_save=AsyncMock())
        hass.data = {LOVELACE_DATA:SimpleNamespace(dashboards={'panasonic-cascade':target})}
        config = {'views':[{'cards':[]}]}
        with patch.object(dashboard, 'build_dashboard', return_value=config), patch.object(dashboard, 'save_dashboard_backup', new=AsyncMock()):
            await dashboard.populate_dashboard(hass, 'panasonic-cascade')
            target.async_save.assert_awaited_once_with(config)
            target.async_load.side_effect = None
            target.async_load.return_value = {'views':[{'cards':[{'type':'markdown'}]}]}
            target.async_save.reset_mock()
            with self.assertRaises(HomeAssistantError): await dashboard.populate_dashboard(hass, 'panasonic-cascade')
            target.async_save.assert_not_awaited()
            await dashboard.populate_dashboard(hass, 'panasonic-cascade', overwrite=True)
            target.async_save.assert_awaited_once_with(config)
            target.mode = 'yaml'
            with self.assertRaises(HomeAssistantError): await dashboard.populate_dashboard(hass, 'panasonic-cascade', overwrite=True)
            with self.assertRaises(HomeAssistantError): await dashboard.populate_dashboard(hass, 'missing')


    async def test_native_lovelace_storage_and_service(self):
        import tempfile
        from homeassistant.core import HomeAssistant
        from homeassistant.components.lovelace.const import LOVELACE_DATA
        from homeassistant.components.lovelace.dashboard import LovelaceStorage
        with tempfile.TemporaryDirectory() as directory:
            hass = HomeAssistant(directory)
            target = LovelaceStorage(hass, {"id":"panasonic-cascade", "url_path":"panasonic-cascade"})
            hass.data[LOVELACE_DATA] = SimpleNamespace(dashboards={"panasonic-cascade":target})
            await target.async_save({"views":[{"title":"Home", "cards":[]}]})
            expected = {"views":[{"title":"Cascade", "cards":[{"type":"entities", "entities":["sensor.actual_id"]}]}]}
            with patch.object(dashboard, 'build_dashboard', return_value=expected):
                dashboard.async_register_dashboard_service(hass)
                dashboard.async_register_dashboard_service(hass)
                await hass.services.async_call('panasonic_cascade', 'populate_dashboard',
                                               {'url_path':'panasonic-cascade'}, blocking=True)
            restored = LovelaceStorage(hass, {"id":"panasonic-cascade", "url_path":"panasonic-cascade"})
            self.assertEqual(await restored.async_load(False), expected)
            await hass.async_stop()
