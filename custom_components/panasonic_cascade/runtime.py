"""Read-only daily observed start counts, reconstructed from Recorder across restarts."""
from functools import partial
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
from .model import name

LOGGER = logging.getLogger(__name__)


def count_starts(states, start):
    """Count confirmed off->on changes; never count an initial/on-after-gap sample."""
    if not states:
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


class CascadeDailyStartsSensor(CascadeEntity, SensorEntity):
    _attr_should_poll = True
    _attr_icon = 'mdi:counter'
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_suggested_display_precision = 0

    def __init__(self, coordinator, ident):
        super().__init__(coordinator, ident, 'starts_today')
        self._attr_name = compact_label(name(self.row)) + ' · Starts heute'
        self._count = None
        self._details = {}

    async def async_added_to_hass(self):
        await super().async_added_to_hass()
        await self.async_update()

    async def async_update(self):
        self._count = None
        today = dt_util.now().date()
        start = dt_util.as_utc(dt_util.start_of_local_day(today))
        source = er.async_get(self.hass).async_get_entity_id(
            'binary_sensor', DOMAIN, f'{self.coordinator.entry.unique_id}|{self.ident}|isRunning')
        self._details = {'day':str(today), 'source_entity':source, 'partial_day':True,
                         'counting':'Recorded off → on transitions since local midnight; gaps are not inferred.'}
        if not source or DATA_INSTANCE not in self.hass.data:
            return
        recorder = get_instance(self.hass)
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
        self._count, self._details['partial_day'] = count_starts(history.get(source, []), start)
        current = self.hass.states.get(source)
        if not current or current.state not in ('on', 'off'):
            self._details['partial_day'] = True

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
