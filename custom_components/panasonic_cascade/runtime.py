"""Power-based run phases and daily threshold crossings reconstructed from Recorder."""
from functools import partial
from math import isfinite
from types import SimpleNamespace
from datetime import timedelta
import logging

from homeassistant.components.recorder.history import state_changes_during_period
from homeassistant.components.sensor import SensorEntity, SensorStateClass
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.recorder import DATA_INSTANCE, get_instance
from homeassistant.exceptions import HomeAssistantError
from homeassistant.util import dt as dt_util
from sqlalchemy.exc import SQLAlchemyError

from .const import DOMAIN
from .entity import CascadeEntity
from .labels import compact_label
from .model import name, model_key
from .zinc import reference

LOGGER = logging.getLogger(__name__)
HISTORY_DAYS = 7


DEFAULT_POWER_THRESHOLD_W = 200


def power_threshold(coordinator):
    return float(coordinator.entry.options.get('power_threshold_w', DEFAULT_POWER_THRESHOLD_W))


def power_source(hass, coordinator, ident):
    """Use only the explicit per-unit total, never a site total or mixed modes."""
    return er.async_get(hass).async_get_entity_id('sensor', DOMAIN,
        f'{coordinator.entry.unique_id}|summary:unit:{ident}:consumedPower|curVal')


def power_on(raw, unit, threshold):
    try:
        watts = float(raw) * {'W': 1, 'kW': 1000}[unit]
    except (ValueError, TypeError, KeyError):
        return None
    return watts >= threshold if isfinite(watts) and watts >= 0 else None


def threshold_states(states, threshold):
    """Preserve timestamps and gaps; units are read per recorded sample."""
    converted = []
    for sample in states:
        active = power_on(sample.state, sample.attributes.get('unit_of_measurement'), threshold)
        converted.append(SimpleNamespace(state='on' if active is True else 'off' if active is False else 'unavailable',
                                        last_updated=sample.last_updated))
    return converted


def count_starts(states, start):
    """Count confirmed off->on changes; never count an initial/on-after-gap sample."""
    if not states or not any(s.state in ("on", "off") for s in states):
        return None, True
    previous = None
    partial_day = states[0].last_updated > start
    count = 0
    for state in states:
        if state.state not in ('on', 'off'):
            previous = None
            partial_day = True
            continue
        if previous == 'off' and state.state == 'on' and state.last_updated >= start:
            count += 1
        previous = state.state
    return count, partial_day


def daily_counts(states, today, days=HISTORY_DAYS):
    """Partition one Recorder query into local calendar days, carrying only the prior state."""
    ordered = sorted(states, key=lambda state: state.last_updated)
    cursor, baseline, result = 0, None, []
    for offset in reversed(range(days)):
        day = today - timedelta(days=offset)
        start = dt_util.as_utc(dt_util.start_of_local_day(day))
        end = dt_util.as_utc(dt_util.start_of_local_day(day + timedelta(days=1)))
        while cursor < len(ordered) and ordered[cursor].last_updated < start:
            baseline = ordered[cursor]
            cursor += 1
        samples = [baseline] if baseline is not None else []
        while cursor < len(ordered) and ordered[cursor].last_updated < end:
            baseline = ordered[cursor]
            samples.append(baseline)
            cursor += 1
        count, incomplete = count_starts(samples, start)
        result.append({'date':str(day), 'starts':count, 'partial':incomplete})
    return list(reversed(result))


class CascadeDailyStartsSensor(CascadeEntity, SensorEntity):
    _attr_should_poll = True
    _attr_icon = 'mdi:counter'
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_suggested_display_precision = 0

    def __init__(self, coordinator, ident):
        super().__init__(coordinator, ident, 'starts_today')
        self._attr_name = compact_label(name(self.row)) + ' · Starts heute (Leistung)'
        self._count = None
        self._details = {}
        self._history_cache = None
        self._history_cache_key = None

    async def async_added_to_hass(self):
        await super().async_added_to_hass()
        await self.async_update()

    async def async_update(self):
        self._count = None
        today = dt_util.now().date()
        start = dt_util.as_utc(dt_util.start_of_local_day(today - timedelta(days=HISTORY_DAYS - 1)))
        source = power_source(self.hass, self.coordinator, self.ident)
        threshold = power_threshold(self.coordinator)
        cache_key = (today, source, threshold)
        if self._history_cache_key == cache_key:
            # Closed days do not change during normal polling. Backfill the
            # week once per day/reload; otherwise query only today's samples.
            start = dt_util.as_utc(dt_util.start_of_local_day(today))
        self._details = {'day':str(today), 'source_entity':source, 'partial_day':True,
                         'daily_starts':[], 'history_days':HISTORY_DAYS,
                         'threshold_w':threshold, 'counting_method':'power_threshold',
                         'counting':'Observed electrical power crossings below → at/above threshold; estimated compressor starts.'}
        if not source:
            self._details['reason'] = 'Per-unit electrical power sensor unavailable'
            return
        if DATA_INSTANCE not in self.hass.data:
            return
        recorder = get_instance(self.hass)
        ready = getattr(recorder, 'async_db_ready', None)
        if ready is not None and (not ready.done() or ready.cancelled() or not ready.result()):
            self._details['reason'] = 'Recorder database not ready'
            return
        if recorder.entity_filter is not None and not recorder.entity_filter(source):
            self._details['reason'] = 'Source excluded from Recorder'
            return
        try:
            history = await recorder.async_add_executor_job(partial(
                state_changes_during_period, self.hass, start, dt_util.utcnow(),
                entity_id=source, no_attributes=False, include_start_time_state=True))
        except (HomeAssistantError, SQLAlchemyError, OSError) as err:
            LOGGER.debug('Could not read start-count history: %s', err)
            return
        if dt_util.now().date() != today:
            return
        days = daily_counts(threshold_states(history.get(source, []), threshold), today,
                            days=1 if self._history_cache_key == cache_key else HISTORY_DAYS)
        if self._history_cache_key == cache_key:
            days += self._history_cache
        else:
            self._history_cache = days[1:]
            self._history_cache_key = cache_key
        self._details['daily_starts'] = days
        self._count, self._details['partial_day'] = days[0]['starts'], days[0]['partial']
        current = self.hass.states.get(source)
        if not current or power_on(current.state, current.attributes.get('unit_of_measurement'), threshold) is None:
            self._details['partial_day'] = True
            days[0]['partial'] = True

    @property
    def should_poll(self):
        return True

    @property
    def native_value(self):
        return self._count

    @property
    def available(self):
        return self._count is not None

    @property
    def extra_state_attributes(self):
        return self._details
