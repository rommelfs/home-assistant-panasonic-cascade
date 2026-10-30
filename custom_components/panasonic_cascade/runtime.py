"""Read-only daily observed start counts, reconstructed from Recorder across restarts."""
from functools import partial
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


# No compressor-running point has been established in the captured controller API.
# Add a model only after verifying its physical meaning; never infer it from power.
VERIFIED_COMPRESSOR_STATUS_MODELS = frozenset()


def verified_compressor_source(hass, coordinator, ident):
    for point, row in coordinator.data.items():
        if (model_key(row) in VERIFIED_COMPRESSOR_STATUS_MODELS and row.get('kind') == 'Bool'
                and (reference(row.get('heatPumpRef')) or reference(row.get('equipRef'))) == ident):
            return er.async_get(hass).async_get_entity_id('binary_sensor', DOMAIN,
                f'{coordinator.entry.unique_id}|{point}|curVal')
    return None


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
        self._attr_name = compact_label(name(self.row)) + ' · Verdichterstarts heute'
        self._count = None
        self._details = {}

    async def async_added_to_hass(self):
        await super().async_added_to_hass()
        await self.async_update()

    async def async_update(self):
        self._count = None
        today = dt_util.now().date()
        start = dt_util.as_utc(dt_util.start_of_local_day(today - timedelta(days=HISTORY_DAYS - 1)))
        source = verified_compressor_source(self.hass, self.coordinator, self.ident)
        self._details = {'day':str(today), 'source_entity':source, 'partial_day':True,
                         'daily_starts':[], 'history_days':HISTORY_DAYS,
                         'counting':'Confirmed compressor off → on transitions only; no power-based inference.'}
        if not source:
            self._details['reason'] = 'No verified compressor-running status; controller isRunning is operating enable only'
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
                entity_id=source, no_attributes=True, include_start_time_state=True))
        except (HomeAssistantError, SQLAlchemyError, OSError) as err:
            LOGGER.debug('Could not read start-count history: %s', err)
            return
        if dt_util.now().date() != today:
            return
        days = daily_counts(history.get(source, []), today)
        self._details['daily_starts'] = days
        self._count, self._details['partial_day'] = days[0]['starts'], days[0]['partial']
        current = self.hass.states.get(source)
        if not current or current.state not in ('on', 'off'):
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
