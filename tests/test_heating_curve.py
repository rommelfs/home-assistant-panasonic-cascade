"""Heating-curve control boundaries, real number entities and installation isolation."""
import importlib
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch
import unittest

from test_api import Session, Response, client, number_point
from test_protocol import zinc, model

MODELS = {
    'water_max': 'compensationCurveHeatZone1MaxTemperature',
    'water_min': 'compensationCurveHeatZone1MinTemperature',
    'outdoor_max': 'compensationCurveHeatZone1OutdoorAirMaxTemperature',
    'outdoor_min': 'compensationCurveHeatZone1OutdoorAirMinTemperature',
}


def point(key):
    row = number_point()
    row['bufferModelId'] = '_equip:buffer_equip:zoneGroup_equip:compCurve_point:' + MODELS[key]
    row.update(minVal=zinc.Number(20 if key.startswith('water') else -20, '°C'),
               maxVal=zinc.Number(75 if key.startswith('water') else 15, '°C'))
    return row


class HeatingCurveProtocolTest(unittest.IsolatedAsyncioTestCase):
    async def test_all_four_controls_send_celsius_and_reject_bad_values(self):
        for key in MODELS:
            with self.subTest(key=key):
                row = point(key)
                low, high = (20, 75) if key.startswith('water') else (-20, 15)
                self.assertEqual(model.control_kind(row), 'number')
                self.assertEqual(model.bounds(row), (low, high))
                s = Session([Response(), Response()]); c = client(s)
                for value in (low, high):
                    await c.set_default(row, value)
                    expr = zinc.parse_grids(s.calls[-1][1]['data'].decode())[0][0]['expr']
                    self.assertEqual(expr, f'pointSetDef(@p:demo:r:a, {value}°C)')
                for value in (low-1, high+1, True, float('nan'), float('inf'), '42'):
                    with self.assertRaises(ValueError): await c.set_default(row, value)
                self.assertEqual(len(s.calls), 2)

    def test_tighter_limits_and_permissions(self):
        for key in MODELS:
            row = point(key)
            row['minVal'] = zinc.Number(25 if key.startswith('water') else -15, '°C')
            row['maxVal'] = zinc.Number(50 if key.startswith('water') else 10, '°C')
            # Water setpoint metadata must not constrain an outdoor axis.
            row['hotSpMin'] = zinc.Number(20, '°C')
            self.assertEqual(model.bounds(row), (25, 50) if key.startswith('water') else (-15, 10))
            row['bacnetServerReadOnly'] = zinc.MARKER
            self.assertIsNone(model.control_kind(row))
            del row['bacnetServerReadOnly']; row['actions'] = 'pointOverride($self,$val,$duration)'
            self.assertIsNone(model.control_kind(row))


try:
    from test_controls_dashboard import coordinator
    numbers = importlib.import_module('custom_components.panasonic_cascade.number')
    dashboard = importlib.import_module('custom_components.panasonic_cascade.dashboard')
    frontend = importlib.import_module('custom_components.panasonic_cascade.frontend')
except ImportError:
    numbers = None


@unittest.skipIf(numbers is None, 'Home Assistant required')
class HeatingCurveHATest(unittest.IsolatedAsyncioTestCase):
    async def test_discovery_opt_in_default_value_and_write(self):
        c = coordinator(); row = point('outdoor_min')
        # Use the real package's Zinc types, rather than the isolated protocol package.
        z = importlib.import_module('custom_components.panasonic_cascade.zinc')
        row.update(id=z.Ref('p:demo:r:a'), writable=z.MARKER,
                   minVal=z.Number(-20,'°C'), maxVal=z.Number(15,'°C'),
                   writeDef=z.Number(-10,'°C'), curVal=z.Number(-5,'°C'))
        c.data = {'point':row}; c.entry.runtime_data = c; c.write = AsyncMock(); add = Mock()
        await numbers.async_setup_entry(c.hass, c.entry, add)
        entity = list(add.call_args[0][0])[0]
        self.assertIn('Zone 1 · Heizkurve · Min. Außentemperatur', entity.name)
        self.assertEqual(entity.native_value, -10)
        self.assertEqual((entity.native_min_value,entity.native_max_value), (-20,15))
        await entity.async_set_native_value(-12)
        c.write.assert_awaited_once_with('point', -12)
        c.entry.options['enable_controls'] = False; add.reset_mock()
        await numbers.async_setup_entry(c.hass, c.entry, add)
        add.assert_not_called()

    def test_curve_uses_actual_ids_and_never_mixes_installations(self):
        entries = []; entities = []
        for index in range(2):
            rows = {key: point(key) for key in MODELS}
            entry = SimpleNamespace(entry_id=str(index),unique_id=f'install{index}',runtime_data=SimpleNamespace(data=rows))
            entries.append(entry)
            for key in MODELS:
                for domain in ('sensor','number'):
                    entities.append(SimpleNamespace(config_entry_id=str(index),domain=domain,
                        entity_id=f'{domain}.renamed_{index}_{key}_2',
                        unique_id=f'install{index}|{key}|curVal'+('|control' if domain=='number' else '')))
        cards = dashboard.heating_curve_cards(entries,entities)
        self.assertEqual(len(cards),2)
        for i, card in enumerate(cards):
            self.assertEqual(card['entities'], {key:f'number.renamed_{i}_{key}_2' for key in MODELS})
        sensors = [e for e in entities if e.domain=='sensor']
        self.assertTrue(all(e.startswith('sensor.') for e in dashboard.heating_curve_cards(entries,sensors)[0]['entities'].values()))
        # Missing one axis in one installation must not borrow another installation's value.
        filtered = [e for e in entities if not (e.config_entry_id=='0' and 'outdoor_min' in e.entity_id)]
        self.assertEqual(len(dashboard.heating_curve_cards(entries,filtered)),1)

    async def test_frontend_registration_is_idempotent_and_yaml_independent(self):
        hass = SimpleNamespace(data={frontend.frontend.DATA_EXTRA_MODULE_URL:Mock()},
                               http=SimpleNamespace(async_register_static_paths=AsyncMock()))
        with patch.object(frontend.frontend,'add_extra_js_url') as add:
            await frontend.async_setup_frontend(hass)
            await frontend.async_setup_frontend(hass)
            hass.http.async_register_static_paths.assert_awaited_once()
            add.assert_called_once_with(hass,frontend.CARD_URL+'?v=0.8.0')
        # Headless installations without the frontend still load core entities.
        await frontend.async_setup_frontend(SimpleNamespace(data={}))
