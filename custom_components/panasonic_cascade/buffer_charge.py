"""Opt-in PV buffer charge with a persisted, compare-before-restore lease."""
import asyncio
import math
import time
from datetime import UTC, datetime, timedelta

import voluptuous as vol
from homeassistant.core import callback
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.dispatcher import async_dispatcher_send
from homeassistant.helpers.event import async_track_state_change_event, async_track_time_interval, async_track_point_in_utc_time
from homeassistant.helpers.service import async_register_admin_service
from homeassistant.helpers.storage import Store

from .const import DOMAIN
from .api import ApiError, AuthError
from .model import bounds, is_buffer_offset, model_key, validate_buffer_offset
from .zinc import value

DEFAULTS = {
    'pv_charge_enabled': False, 'pv_charge_auto': False, 'pv_charge_confirmed': False,
    'pv_charge_test_without_temperature': False,
    'pv_charge_export_positive': True, 'pv_charge_discharge_positive': True,
    'pv_charge_start_w': 1500, 'pv_charge_stop_w': 500, 'pv_charge_dwell_s': 120,
    'pv_charge_offset': 5, 'pv_charge_duration_min': 30, 'pv_charge_max_c': 75,
    'pv_charge_max_age_s': 60,
}
SOURCE_KEYS = ('export', 'battery', 'pv', 'temperature')


def finite(raw):
    if isinstance(raw, bool):
        raise ValueError('Invalid numeric value')
    result = float(raw)
    if not math.isfinite(result):
        raise ValueError('Invalid numeric value')
    return result


def measurements(hass, options, now, *, unmonitored_test=False):
    """Normalize explicit signed sources; unknown/stale data never become zero."""
    result = {}
    for key in SOURCE_KEYS:
        if key == 'temperature' and unmonitored_test:
            continue
        entity_id = options.get(f'pv_charge_{key}_sensor')
        state = hass.states.get(entity_id) if entity_id else None
        if state is None:
            raise ValueError(f'Missing {key} measurement')
        reported = getattr(state, 'last_reported', None) or state.last_updated
        age = now - reported.timestamp()
        if age < -5 or age > options['pv_charge_max_age_s']:
            raise ValueError(f'Stale {key} measurement')
        raw = finite(state.state)
        unit = state.attributes.get('unit_of_measurement')
        if key == 'temperature':
            if unit != '°C' or not 0 <= raw <= 95:
                raise ValueError('Invalid buffer temperature')
        elif unit in ('W', 'kW'):
            raw *= 1000 if unit == 'kW' else 1
        else:
            raise ValueError(f'Unsupported {key} measurement unit')
        result[key] = raw
    result['export'] *= 1 if options['pv_charge_export_positive'] else -1
    result['battery'] *= 1 if options['pv_charge_discharge_positive'] else -1
    if result['pv'] <= 50:
        raise ValueError('No PV production')
    if result['battery'] > 100:
        raise ValueError('Battery is discharging')
    if result['export'] < 0:
        raise ValueError('Grid import')
    if not unmonitored_test and result['temperature'] >= min(75, finite(options['pv_charge_max_c'])):
        raise ValueError('Buffer temperature limit reached')
    return result


class BufferCharge:
    def __init__(self, coordinator, store=None, clock=time.time):
        self.c = coordinator
        self.hass, self.entry = coordinator.hass, coordinator.entry
        self.store = store or Store(self.hass, 1, f'{DOMAIN}.buffer_charge.{self.entry.entry_id}', atomic_writes=True)
        self.clock = clock
        self.lease = None
        self.status, self.reason = 'disabled', ''
        self.stable_since = None
        self.last_restore_attempt = -math.inf
        self.last_verify = -math.inf
        self.unsub, self.tasks = [], set()
        self.deadline_cancel = None
        self.closed = False
        self.tick_pending = False
        # Share the lock with all ordinary Set Default operations.
        self.lock = coordinator._write_lock

    @property
    def options(self):
        return {**DEFAULTS, **self.entry.options}

    @property
    def signal(self):
        return f'{DOMAIN}_buffer_charge_{self.entry.entry_id}'

    @callback
    def changed(self):
        async_dispatcher_send(self.hass, self.signal)

    async def save(self):
        await self.store.async_save({'lease': self.lease, 'reason': self.reason})

    async def async_initialize(self):
        saved = await self.store.async_load() or {}
        self.lease = saved.get('lease')
        self.reason = saved.get('reason', '')
        if self.lease:
            # Never resume or extend a raised offset after restart/reload.
            async with self.lock:
                await self._restore('Home Assistant restarted')
        self.unsub.append(async_track_time_interval(self.hass, self.request_tick, timedelta(seconds=15)))
        sources = [self.options.get(f'pv_charge_{key}_sensor') for key in SOURCE_KEYS]
        self.unsub.append(async_track_state_change_event(self.hass, [s for s in sources if s], self.request_tick))
        self.unsub.append(self.c.async_add_listener(self.request_tick))
        await self.async_tick()

    @callback
    def request_tick(self, _event=None):
        if self.closed:
            return
        self.tick_pending = True
        if self.tasks:
            return
        async def run():
            while self.tick_pending and not self.closed:
                self.tick_pending = False
                await self.async_tick()
        task = self.hass.async_create_task(run())
        self.tasks.add(task)
        task.add_done_callback(self.tasks.discard)

    def configured(self):
        o = self.options
        return o['pv_charge_enabled'] and o['pv_charge_confirmed'] and o.get('enable_controls', False)

    @property
    def unmonitored_test(self):
        return self.options['pv_charge_test_without_temperature'] is True

    def readings(self):
        # A test option may not weaken an existing normal charge's guards.
        testing = self.unmonitored_test and (self.lease is None or self.lease.get('temperature_unmonitored_test') is True)
        return measurements(self.hass, self.options, self.clock(), unmonitored_test=testing)

    def point(self):
        points = [ident for ident, row in (self.c.data or {}).items() if is_buffer_offset(row)]
        if len(points) != 1:
            raise ValueError('Exactly one writable cascade buffer offset is required')
        return points[0]

    async def fresh(self, ident):
        return await self.c.client.read_point(ident, self.entry.data['site_id'])

    async def heating_mode(self):
        points = [ident for ident, row in (self.c.data or {}).items()
                  if row.get('bufferModelId') and model_key(row) == 'bufferMode']
        if len(points) != 1:
            raise ValueError('A verified cascade heating mode is required')
        row = await self.fresh(points[0])
        if row.get('curStatus') != 'ok' or value(row.get('curVal')) != 'Heat':
            raise ValueError('PV buffer charging requires the cascade heating mode')

    async def async_start(self, offset=None, duration=None):
        async with self.lock:
            await self._start(offset, duration)

    async def _start(self, offset=None, duration=None):
        if self.closed or not self.configured():
            raise HomeAssistantError('Configure and enable PV charging, measurement signs and temperature/hydraulic verification first')
        if self.lease:
            raise HomeAssistantError('A charge or unresolved restoration already exists; overlapping charges are not allowed')
        o = self.options
        testing = self.unmonitored_test
        try:
            if testing and o['pv_charge_auto']:
                raise ValueError('Unmonitored charge tests require automatic start to be off')
            offset = finite(o['pv_charge_offset'] if offset is None else offset)
            duration = finite(o['pv_charge_duration_min'] if duration is None else duration)
            if not 1 <= duration <= 120 or not 1 <= offset <= 10:
                raise ValueError('Charge requires 1–120 minutes and an offset of 1–10 °C')
            self.readings()
            if self.stable_since is None or self.clock() - self.stable_since < o['pv_charge_dwell_s']:
                raise ValueError('Wait for stable PV export above the configured start threshold')
            if self.readings()['export'] < o['pv_charge_start_w']:
                raise ValueError('Insufficient PV export to start')
            if not self.c.last_update_success:
                raise ValueError('Controller data is unavailable')
            ident = self.point()
            await self.heating_mode()
            row = await self.fresh(ident)
            validate_buffer_offset(row)
            baseline = value(row['writeDef'])
            if testing:
                # Fixed additional 2 K, never beyond the verified 10 K/live limit.
                # Caller/config values cannot raise or extend this test envelope.
                offset = min(baseline + 2, 10, bounds(row)[1])
                duration = min(duration, 5)
            if not bounds(row)[0] <= offset <= bounds(row)[1] or offset <= baseline:
                raise ValueError('Charge offset must exceed the existing default and respect live controller bounds')
            # Recheck source guards after the network read, immediately before writing.
            if not self.configured() or not self.c.last_update_success or self.readings()['export'] < o['pv_charge_start_w']:
                raise ValueError('PV charging conditions changed')
        except (ApiError, AuthError, ValueError, TypeError) as err:
            raise HomeAssistantError(str(err)) from err
        self.lease = {'point': ident, 'baseline': baseline, 'applied': offset,
                      'expires': self.clock() + duration * 60, 'phase': 'applying',
                      'temperature_unmonitored_test': testing}
        self.reason = ''
        try:
            # Durable recovery intent is mandatory before the first device write.
            await self.save()
        except Exception as err:
            self.lease = None
            raise HomeAssistantError('Could not persist the original buffer offset; no change sent') from err
        self.status = 'charging'
        self.changed()
        try:
            await self.c.client.set_default(row, offset)
            current = await self.fresh(ident)
            validate_buffer_offset(current)
            if value(current['writeDef']) != offset:
                raise ValueError('Controller did not confirm the requested effective offset')
            # A read/write can straddle an outage or the requested expiry.
            if self.clock() >= self.lease['expires'] or not self.configured():
                raise ValueError('Charge expired or was disabled during application')
            self.readings()
            self.last_verify = self.clock()
            self.lease['phase'] = 'charging'
            await self.save()
            self.deadline_cancel = async_track_point_in_utc_time(
                self.hass, self._deadline, datetime.fromtimestamp(self.lease['expires'], UTC))
        except Exception as err:
            self.reason = f'Application could not be confirmed: {type(err).__name__}'
            await self._restore(self.reason)
            raise HomeAssistantError('PV charge could not be confirmed; restoration was requested') from err
        finally:
            self.changed()

    async def _deadline(self, _now):
        self.deadline_cancel = None
        await self.async_stop('Charge duration expired')

    async def _clear(self, reason):
        if self.deadline_cancel:
            self.deadline_cancel()
            self.deadline_cancel = None
        await self.store.async_save({'lease': None, 'reason': reason})
        self.lease = None
        self.reason, self.status, self.stable_since = reason, 'idle', None
        self.changed()
        return True

    async def _conflict(self, reason):
        self.lease['phase'] = 'conflict'
        self.status, self.reason = 'conflict', reason
        await self.save()
        from homeassistant.components import persistent_notification
        persistent_notification.async_create(self.hass, reason, title='Panasonic PV buffer charge: external change',
                                               notification_id=f'{DOMAIN}_buffer_charge_{self.entry.entry_id}')
        self.changed()
        return False

    async def _restore(self, reason):
        if not self.lease:
            return True
        if self.lease['phase'] == 'conflict':
            self.status = 'conflict'
            return False
        self.status, self.reason = 'restore_pending', reason
        self.lease['phase'] = 'restore_pending'
        try:
            try:
                await self.save()
            except Exception:
                # The original applying/charging intent is already durable. A storage
                # failure must not prevent trying to reduce the controller offset.
                pass
            row = await self.fresh(self.lease['point'])
            validate_buffer_offset(row, require_effective_default=False)
            current = value(row['writeDef'])
            if current == self.lease['baseline']:
                return await self._clear(reason)
            if current != self.lease['applied']:
                return await self._conflict('The controller offset was changed independently. No restoration was written; check the controller and acknowledge this conflict.')
            await self.c.client.set_default(row, self.lease['baseline'])
            check = await self.fresh(self.lease['point'])
            validate_buffer_offset(check, require_effective_default=False)
            if value(check['writeDef']) != self.lease['baseline']:
                raise ValueError('Restoration not confirmed by effective feedback')
            return await self._clear(reason)
        except Exception as err:
            # Keep the durable lease until a fresh read confirms the original value.
            self.status = 'restore_pending'
            self.reason = f'{reason}; restoration pending: {type(err).__name__}'
            self.changed()
            return False
        finally:
            self.last_restore_attempt = self.clock()

    async def async_stop(self, reason='Stopped by user'):
        async with self.lock:
            return await self._restore(reason)

    async def async_acknowledge(self):
        async with self.lock:
            if not self.lease or self.lease['phase'] != 'conflict':
                raise HomeAssistantError('There is no external-change conflict to acknowledge')
            await self._clear('External change acknowledged; no controller write')

    async def async_tick(self):
        async with self.lock:
            if self.closed:
                return
            if self.lease:
                if self.lease['phase'] != 'charging':
                    if self.clock() - self.last_restore_attempt >= 15:
                        await self._restore(self.reason or 'Pending restoration')
                    return
                reason = None
                try:
                    if not self.configured():
                        reason = 'PV charging disabled'
                    elif self.lease.get('temperature_unmonitored_test') and (not self.unmonitored_test or self.options['pv_charge_auto']):
                        reason = 'Manual unmonitored test permission removed'
                    elif self.clock() >= self.lease['expires']:
                        reason = 'Charge duration expired'
                    elif not self.c.last_update_success:
                        reason = 'Controller connection lost'
                    elif self.readings()['export'] < self.options['pv_charge_stop_w']:
                        reason = 'PV export below stop threshold'
                    if reason is None and self.clock() - self.last_verify >= 15:
                        await self.heating_mode()
                        row = await self.fresh(self.lease['point'])
                        validate_buffer_offset(row)
                        if value(row['writeDef']) != self.lease['applied']:
                            reason = 'Controller offset changed'
                        self.last_verify = self.clock()
                except Exception as err:
                    reason = str(err)
                if reason:
                    await self._restore(reason)
                return
            if not self.configured():
                self.status, self.reason, self.stable_since = 'disabled', '', None
            else:
                try:
                    if not self.c.last_update_success:
                        raise ValueError('Controller data is unavailable')
                    data = self.readings()
                    if data['export'] < self.options['pv_charge_start_w']:
                        self.status, self.reason, self.stable_since = 'waiting', 'Waiting for PV export', None
                    else:
                        if self.stable_since is None:
                            self.stable_since = self.clock()
                        stable = self.clock() - self.stable_since >= self.options['pv_charge_dwell_s']
                        self.status = 'ready' if stable else 'waiting'
                        self.reason = 'Stable PV export; ready to start' if stable else 'Waiting for stable PV export'
                        if self.options['pv_charge_auto'] and not self.unmonitored_test and self.clock() - self.stable_since >= self.options['pv_charge_dwell_s']:
                            try:
                                await self._start()
                            except Exception as err:
                                self.status, self.reason = 'blocked', str(err)
                                self.stable_since = None
                except (ValueError, TypeError) as err:
                    self.status, self.reason, self.stable_since = 'blocked', str(err), None
            self.changed()

    async def async_close(self):
        self.closed = True
        for unsub in self.unsub:
            unsub()
        self.unsub.clear()
        if self.deadline_cancel:
            self.deadline_cancel()
            self.deadline_cancel = None
        for task in list(self.tasks):
            task.cancel()
        if self.tasks:
            await asyncio.gather(*self.tasks, return_exceptions=True)
        await self.async_stop('Home Assistant stopped or integration unloaded')


def async_register_charge_services(hass):
    if hass.services.has_service(DOMAIN, 'start_buffer_charge'):
        return
    schema = vol.Schema({vol.Required('entry_id'): str,
                         vol.Optional('offset'): vol.All(finite, vol.Range(min=1, max=10)),
                         vol.Optional('duration_minutes'): vol.All(finite, vol.Range(min=1, max=120))})

    async def handle(call):
        entry = hass.config_entries.async_get_entry(call.data['entry_id'])
        manager = getattr(getattr(entry, 'runtime_data', None), 'buffer_charge', None) if entry and entry.domain == DOMAIN else None
        if manager is None:
            raise HomeAssistantError('Select a loaded Panasonic Cascade installation')
        if call.service == 'start_buffer_charge':
            await manager.async_start(call.data.get('offset'), call.data.get('duration_minutes'))
        elif call.service == 'stop_buffer_charge':
            if not await manager.async_stop():
                raise HomeAssistantError('Restoration is pending or conflicts with an external change; check the PV charge status')
        else:
            await manager.async_acknowledge()

    for service in ('start_buffer_charge', 'stop_buffer_charge', 'acknowledge_buffer_charge_conflict'):
        async_register_admin_service(hass, DOMAIN, service, handle,
                                    schema=schema if service == 'start_buffer_charge' else vol.Schema({vol.Required('entry_id'): str}))


async def async_setup_charge(coordinator):
    from homeassistant.const import EVENT_HOMEASSISTANT_STOP
    manager = coordinator.buffer_charge = BufferCharge(coordinator)
    await manager.async_initialize()
    async def stopping(_event):
        await manager.async_close()
    coordinator.entry.async_on_unload(coordinator.hass.bus.async_listen_once(EVENT_HOMEASSISTANT_STOP, stopping))
    async_register_charge_services(coordinator.hass)
