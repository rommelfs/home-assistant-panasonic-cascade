"""Fast alarm checks and persistent deduplication for Companion App push."""
import asyncio
from datetime import timedelta
import hashlib
import json
import logging
import re
import time
from collections.abc import Mapping

from homeassistant.core import callback
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.event import async_track_time_interval
from homeassistant.helpers.storage import Store

from .api import ApiError, AuthError
from .const import DOMAIN
from .diagnostics import timestamp
from .model import is_dhw, name
from .zinc import reference

LOGGER = logging.getLogger(__name__)
POLL_SECONDS = 5
TARGET = re.compile(r'mobile_app_[a-z0-9_]+$')


def mobile_targets(hass):
    services = hass.services.async_services().get('notify', {})
    if not isinstance(services, Mapping):
        return {}
    return {key: key.removeprefix('mobile_app_').replace('_', ' ')
            for key in sorted(services) if TARGET.fullmatch(key)}


def alarm_events(grid, rows, use_dhw=True):
    events = {}
    for row in grid:
        status = row.get('alarmStatus')
        if status == 'normal':
            continue
        # The recorded UI counts alarmStatus == "alarm". Never infer alarms from
        # historical error codes or acknowledgements.
        if status != 'alarm':
            raise ApiError('Unexpected active-alarm status')
        target = reference(row.get('equipRef')) or reference(row.get('targetRef'))
        if not use_dhw and is_dhw(rows.get(target, {}), rows=rows):
            continue
        text = row.get('alarmText')
        source = reference(row.get('id')) or reference(row.get('alarmSourceRef')) or target
        if not source or not isinstance(text, str):
            raise ApiError('Incomplete active-alarm record')
        when = timestamp(row.get('lastTimeOn') or row.get('ts'))
        # Timestamps distinguish recurrences even if the alarm never disappears
        # from the UI between checks. Acknowledging does not change this key.
        fingerprint = hashlib.sha256(json.dumps([source, when, text], ensure_ascii=False).encode()).hexdigest()
        events[fingerprint] = {'equipment': name(rows[target]) if target in rows else 'Anlage',
                               'text': text[:500], 'time': when}
    return events


async def async_send_push(hass, entry, title, message, tag):
    service = entry.options.get('alarm_notify_service', '')
    if not TARGET.fullmatch(service) or not hass.services.has_service('notify', service):
        raise HomeAssistantError('Kein verfügbares Handy für Alarm-Push ausgewählt. Companion App und Integrationsoptionen prüfen.')
    data = {'tag':f'{DOMAIN}-{entry.entry_id}-{tag}', 'group':f'{DOMAIN}-{entry.entry_id}',
            'priority':'high', 'ttl':0}
    if entry.options.get('alarm_time_sensitive', True):
        data['push'] = {'interruption-level':'time-sensitive'}
    # Delivery and operating-system permissions remain the Companion App's job.
    await hass.services.async_call('notify', service, {'title':title, 'message':message, 'data':data}, blocking=True)


async def async_test_push(hass, entry):
    await async_send_push(hass, entry, 'Wärmepumpe – Push-Test',
                          f'{entry.title}: Die Alarmbenachrichtigung ist eingerichtet. Dies ist eine Testnachricht, kein Anlagenalarm.', 'test')


class AlarmMonitor:
    def __init__(self, hass, entry, coordinator):
        self.hass, self.entry, self.coordinator = hass, entry, coordinator
        self.store = Store(hass, 1, f'{DOMAIN}.alarm_notifications.{entry.entry_id}')
        self.notified = set()
        self._lock = asyncio.Lock()
        self._cancel_timer = None
        self._active_task = None
        self._stopped = False
        self._read_retry_at = self._send_retry_at = 0
        self._read_failures = self._send_failures = 0

    async def async_start(self):
        saved = await self.store.async_load() or {}
        if saved.get('target') == self.entry.options.get('alarm_notify_service'):
            self.notified = set(saved.get('notified', []))
        self._cancel_timer = async_track_time_interval(self.hass, self.async_check, timedelta(seconds=POLL_SECONDS))
        # Check immediately, without delaying integration setup on network/push.
        self._active_task = self.hass.async_create_task(self.async_check(), name='Panasonic Cascade alarm check')

    @callback
    def async_stop(self):
        self._stopped = True
        if self._cancel_timer:
            self._cancel_timer()
            self._cancel_timer = None
        if self._active_task and not self._active_task.done():
            self._active_task.cancel()

    async def _save(self):
        await self.store.async_save({'target':self.entry.options.get('alarm_notify_service'), 'notified':sorted(self.notified)})

    async def async_check(self, _now=None):
        if self._stopped or self._lock.locked() or time.monotonic() < self._read_retry_at:
            return
        async with self._lock:
            self._active_task = asyncio.current_task()
            try:
                await self._async_read_and_notify()
            finally:
                self._active_task = None

    async def _async_read_and_notify(self):
        try:
            grid = await self.coordinator.client.active_alarms(self.entry.data['site_id'])
            events = alarm_events(grid, self.coordinator.all_data, self.entry.options.get('use_dhw', True))
        except (ApiError, AuthError):
            if not self._read_failures:
                LOGGER.warning('Alarm-Push: Alarmabfrage fehlgeschlagen; Wiederholung folgt')
            self._read_failures += 1
            self._read_retry_at = time.monotonic() + min(60, POLL_SECONDS * 2 ** min(self._read_failures - 1, 4))
            return
        self._read_failures = 0
        self._read_retry_at = 0
        retained = self.notified.intersection(events)
        if retained != self.notified:
            self.notified = retained
            await self._save()
        if time.monotonic() < self._send_retry_at:
            return
        for key, event in events.items():
            if key in self.notified:
                continue
            message = f"{self.entry.title}\n{event['equipment']}: {event['text']}"
            if event['time']:
                message += '\n' + event['time']
            try:
                await async_send_push(self.hass, self.entry, 'WP-Alarm – ' + event['equipment'], message, key)
            except HomeAssistantError:
                if not self._send_failures:
                    LOGGER.warning('Alarm-Push: Benachrichtigung konnte nicht übergeben werden; Handy-Auswahl und Companion App prüfen')
                self._send_failures += 1
                self._send_retry_at = time.monotonic() + min(300, 15 * 2 ** min(self._send_failures - 1, 5))
                return
            self._send_failures = 0
            self._send_retry_at = 0
            self.notified.add(key)
            await self._save()
