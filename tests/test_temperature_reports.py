"""Real ESPHome packets keep unchanged temperatures fresh; silence does not."""
import sys
from types import ModuleType, SimpleNamespace
import unittest
from unittest.mock import Mock, patch
import test_buffer_charge as fixtures
charge = fixtures.charge
from custom_components.panasonic_cascade.temperature_reports import TemperatureReports


class EspSensor:
    __module__ = 'homeassistant.components.esphome.sensor'


class Connection:
    is_connected = True
    def __init__(self): self.handlers = []
    def add_message_callback(self, callback, types):
        self.handlers.append(callback)
        return lambda: self.handlers.remove(callback)
    def send(self, value=40, key=12, device_id=0, missing=False):
        for handler in list(self.handlers):
            handler(SimpleNamespace(state=value, key=key, device_id=device_id, missing_state=missing))


class ReportTest(unittest.TestCase):
    def setUp(self):
        self.now = 1000
        self.changed = Mock()
        self.connection = Connection()
        self.entity = EspSensor()
        self.entity._entry_data = SimpleNamespace(available=True, client=SimpleNamespace(_connection=self.connection))
        self.entity._static_info = SimpleNamespace(unit_of_measurement='°C', key=12, device_id=0)
        self.hass = SimpleNamespace(data={'sensor': SimpleNamespace(get_entity=lambda _: self.entity)})
        proto = ModuleType('aioesphomeapi.api_pb2'); proto.SensorStateResponse = object
        self.enterContext(patch.dict(sys.modules, {'aioesphomeapi.api_pb2': proto}))
        self.reports = TemperatureReports(self.hass, self.changed, lambda: self.now)
        self.addCleanup(self.reports.shutdown)

    def sample(self): return self.reports.sample('sensor.temperature')

    def test_identical_packets_refresh_but_reads_never_do(self):
        self.assertIsNone(self.sample())
        self.connection.send()  # Possible cached first snapshot is ignored.
        self.assertIsNone(self.sample())
        self.now += 15; self.connection.send()
        self.assertEqual(self.sample(), (40, 1015, '°C'))
        self.now += 15; self.connection.send()
        self.assertEqual(self.sample(), (40, 1030, '°C'))
        self.now += 100
        self.assertEqual(self.sample(), (40, 1030, '°C'))
        self.assertEqual(len(self.connection.handlers), 1)

    def test_unrelated_keys_and_subdevices_do_not_refresh(self):
        self.sample(); self.connection.send(); self.connection.send()
        self.now += 100
        self.connection.send(key=13); self.connection.send(device_id=1)
        self.assertEqual(self.sample()[1], 1000)

    def test_disconnect_and_reconnect_clear_old_measurement(self):
        self.sample(); self.connection.send(); self.connection.send()
        self.connection.is_connected = False
        with self.assertRaisesRegex(ValueError, 'disconnected'): self.sample()
        self.assertEqual(self.connection.handlers, [])
        self.entity._entry_data.client._connection = Connection()
        self.assertIsNone(self.sample())
        self.assertEqual(len(self.entity._entry_data.client._connection.handlers), 1)

    def test_missing_nan_packet_is_not_last_good_value(self):
        self.sample(); self.connection.send(); self.connection.send()
        self.connection.send(missing=True)
        with self.assertRaises(ValueError): charge.finite(self.sample()[0])

    def test_entity_replaced_or_source_changed_unsubscribes(self):
        self.sample(); self.connection.send(); self.connection.send()
        self.entity = None
        self.assertIsNone(self.sample()); self.assertEqual(self.connection.handlers, [])

    def test_unsupported_shape_fails_closed_and_shutdown_removes_observer(self):
        self.sample(); self.reports.shutdown()
        self.assertEqual(self.connection.handlers, [])
        self.assertIsNone(self.sample())


class GuardReportTest(unittest.IsolatedAsyncioTestCase):
    setUp = fixtures.ChargeTest.setUp
    refresh = fixtures.ChargeTest.refresh
    advance = fixtures.ChargeTest.advance
    begin = fixtures.ChargeTest.begin
    async def test_real_sample_permits_unchanged_state_but_silence_restores(self):
        self.advance(100)
        self.states['sensor.temperature'].last_reported = self.states['sensor.temperature'].last_reported.replace(year=2020)
        self.m.temperature_reports.sample = Mock(return_value=(40, self.t, '°C'))
        await self.begin()
        self.advance(61)
        await self.m.async_tick()
        self.assertEqual(self.writes, [7,2])
        self.assertIsNone(self.m.lease)
        self.assertIn('Stale temperature', self.m.reason)

    async def test_native_hot_or_invalid_packet_restores(self):
        for raw in [75, float('nan')]:
            self.refresh(); self.m.temperature_reports.sample = Mock(return_value=None)
            await self.begin()
            self.m.temperature_reports.sample.return_value = (raw, self.t, '°C')
            await self.m.async_tick()
            self.assertIsNone(self.m.lease)
