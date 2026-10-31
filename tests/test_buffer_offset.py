"""Buffer offset isolation, bounded wire format, and fresh permission checks."""
import importlib
import unittest
from unittest.mock import AsyncMock, Mock

from test_api import Session, Response, client, number_point
from test_protocol import model, zinc


def offset():
    row = number_point()
    row.update(bufferModelId='_equip:buffer_point:tBufferTank', curStatus='ok',
               curVal=zinc.Number(0, '°C'), writeDef=zinc.Number(0, '°C'))
    return row


class BufferOffsetProtocolTest(unittest.IsolatedAsyncioTestCase):
    async def test_only_offset_is_written_in_celsius(self):
        session = Session([Response(), Response()])
        for target in (0, 10):
            await client(session).set_default(offset(), target)
            expression = zinc.parse_grids(session.calls[-1][1]['data'].decode())[0][0]['expr']
            self.assertEqual(expression, f'pointSetDef(@p:demo:r:a, {target}°C)')
        for target in (-1, 11, True, '5', float('nan'), float('inf')):
            with self.assertRaises(ValueError):
                await client(session).set_default(offset(), target)
        self.assertEqual(len(session.calls), 2)

    def test_heat_pump_echo_and_unadvertised_controls_are_not_editable(self):
        row = offset()
        row['heatPumpModelId'] = row.pop('bufferModelId')
        self.assertIsNone(model.control_kind(row))
        for change in ({'writable': None}, {'actions': 'pointOverride($self,$val,$duration)'},
                       {'bacnetServerReadOnly': zinc.MARKER}, {'unit': 'K'}):
            row = offset(); row.update(change)
            self.assertIsNone(model.control_kind(row))

    def test_difference_does_not_inherit_absolute_water_bounds(self):
        row = offset()
        row.update(hotSpMin=zinc.Number(20, '°C'), hotSpMax=zinc.Number(55, '°C'))
        self.assertEqual(model.bounds(row), (0, 10))
        row.update(minVal=zinc.Number(2, '°C'), maxVal=zinc.Number(7, '°C'))
        self.assertEqual(model.bounds(row), (2, 7))

    def test_feedback_and_default_must_be_valid_and_equal(self):
        model.validate_buffer_offset(offset())
        for change in ({'curStatus':'fault'}, {'curVal':None}, {'writeDef':None},
                       {'curVal':zinc.Number(5, '°C')}, {'curVal':float('nan')},
                       {'writeDef':True}):
            row = offset(); row.update(change)
            with self.assertRaises(ValueError): model.validate_buffer_offset(row)


try:
    from test_controls_dashboard import coordinator, HomeAssistantError
    numbers = importlib.import_module('custom_components.panasonic_cascade.number')
    hz = importlib.import_module('custom_components.panasonic_cascade.zinc')
except ImportError:
    numbers = None


def live_offset():
    row = offset()
    row.update(id=hz.Ref('p:demo:r:a'), writable=hz.MARKER,
               curVal=hz.Number(0, '°C'), writeDef=hz.Number(0, '°C'))
    return row


@unittest.skipIf(numbers is None, 'Home Assistant required')
class BufferOffsetHATest(unittest.IsolatedAsyncioTestCase):
    async def test_number_discovery_and_opt_in(self):
        c = coordinator(); c.data = {'point':live_offset()}; c.entry.runtime_data = c
        add = Mock(); c.write = AsyncMock()
        await numbers.async_setup_entry(c.hass, c.entry, add)
        entity = list(add.call_args[0][0])[0]
        self.assertEqual(entity.name, 'Puffer · Zonenversatz (dauerhaft)')
        self.assertEqual(entity.unique_id, 'installation|point|curVal|control')
        self.assertIsNone(entity.device_class)
        self.assertEqual(entity.native_value, 0)
        self.assertEqual((entity.native_min_value, entity.native_max_value), (0, 10))
        await entity.async_set_native_value(5)
        c.write.assert_awaited_once_with('point', 5)
        c.entry.options['enable_controls'] = False; add.reset_mock()
        await numbers.async_setup_entry(c.hass, c.entry, add)
        add.assert_not_called()

    async def test_fresh_read_and_tighter_bounds_reach_transport(self):
        c = coordinator(); c.data = {'point':live_offset()}
        fresh = live_offset(); fresh['maxVal'] = hz.Number(4, '°C')
        c.client.read_point.return_value = fresh
        await c.write('point', 3)
        c.client.read_point.assert_awaited_once_with('point', 'site')
        c.client.set_default.assert_awaited_once_with(fresh, 3)
        c.async_request_refresh.assert_awaited_once()

    async def test_changed_permission_or_active_override_never_writes(self):
        for change in ({'writable':None}, {'curVal':hz.Number(2, '°C')},
                       {'curStatus':'fault'}, {'actions':''}, {'writeDef':None}):
            c = coordinator(); c.data = {'point':live_offset()}
            row = live_offset(); row.update(change); c.client.read_point.return_value = row
            with self.assertRaises(HomeAssistantError): await c.write('point', 5)
            c.client.set_default.assert_not_awaited()

    async def test_offline_and_disabled_never_read_or_write(self):
        for situation in ('offline', 'disabled'):
            c = coordinator(); c.data = {'point':live_offset()}
            if situation == 'offline': c.last_update_success = False
            else: c.entry.options['enable_controls'] = False
            with self.assertRaises(HomeAssistantError): await c.write('point', 5)
            c.client.read_point.assert_not_awaited()
            c.client.set_default.assert_not_awaited()

class BufferOffsetMetadataTest(unittest.TestCase):
    def test_mixed_scope_and_malformed_live_bounds_are_refused(self):
        for update in ({'heatPumpModelId':'_equip:heatPump_point:tBufferTank'},
                       {'minVal':zinc.Number(float('nan'),'°C')},
                       {'maxVal':zinc.Number(10,'°F')}):
            row=offset();row.update(update)
            self.assertIsNone(model.control_kind(row))

    def test_feedback_unit_mismatch_is_refused(self):
        row=offset();row['curVal']=zinc.Number(0,'°F')
        with self.assertRaises(ValueError):model.validate_buffer_offset(row)
