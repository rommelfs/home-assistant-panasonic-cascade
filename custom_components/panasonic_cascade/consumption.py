"""WP electricity totals from the same reset-aware statistics as the bar charts."""
from datetime import timedelta
from functools import partial
import logging
import math

from homeassistant.components.recorder.statistics import statistics_during_period
from homeassistant.components.sensor import SensorEntity, SensorDeviceClass
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.recorder import DATA_INSTANCE, get_instance
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.util import dt as dt_util
from homeassistant.exceptions import HomeAssistantError
from sqlalchemy.exc import SQLAlchemyError

from .const import DOMAIN
from .model import model_key

LOGGER = logging.getLogger(__name__)
COUNTERS = {'heatModeEnergyConsumptionTotalMsb', 'coolModeHeatRecoveryModeEnergyConsumptionTotalMsb',
            'tankModeEnergyConsumptionMsb'}
LABELS = {'day':'Heute','week':'Woche','month':'Monat','year':'Jahr'}


def period_start(now, period):
    day = now.replace(hour=0, minute=0, second=0, microsecond=0)
    if period == 'day': return day
    if period == 'week': return day - timedelta(days=day.weekday())
    if period == 'month': return day.replace(day=1)
    return day.replace(month=1, day=1)


def sum_changes(data, sources):
    """Missing sources are missing, never zero or an extrapolated full-day value."""
    if not sources or any(not data.get(source) for source in sources):
        return None
    total = 0.0
    for source in sources:
        for row in data[source]:
            raw = row.get('change')
            if type(raw) not in (int, float) or not math.isfinite(raw) or raw < 0:
                return None
            total += raw
    return total


class ConsumptionSensor(SensorEntity):
    _attr_should_poll = True
    _attr_has_entity_name = False
    _attr_device_class = SensorDeviceClass.ENERGY
    _attr_native_unit_of_measurement = 'kWh'
    _attr_suggested_display_precision = 2

    def __init__(self, coordinator, period):
        self.c, self.period = coordinator, period
        self._attr_unique_id = coordinator.entry.unique_id + '|consumption:' + period
        self._attr_name = 'WP · Stromverbrauch · ' + LABELS[period]
        self._attr_device_info = DeviceInfo(identifiers={(DOMAIN,coordinator.entry.unique_id+'|consumption')},
            name='WP · Stromverbrauch', manufacturer='Panasonic', model='Controller counter statistics')
        self._attr_native_value = None
        self._attr_extra_state_attributes = {}

    async def async_added_to_hass(self):
        await self.async_update()

    async def async_update(self):
        self._attr_native_value = None
        now = dt_util.now()
        start = dt_util.as_utc(period_start(now, self.period))
        registry = er.async_get(self.hass)
        sources = []
        for ident, row in self.c.data.items():
            if model_key(row) not in COUNTERS: continue
            entity_id = registry.async_get_entity_id('sensor', DOMAIN, self.c.entry.unique_id+'|'+ident+'|curVal')
            if entity_id: sources.append(entity_id)
        self._attr_extra_state_attributes = {'method':'Sum of reset-aware controller electricity counter statistics',
            'period_start':start.isoformat(), 'source_entities':sources, 'source_attribution_independent':True,
            'note':'Completed Recorder statistics intervals; controller counters are not a calibrated external meter.'}
        if not sources or DATA_INSTANCE not in self.hass.data: return
        recorder = get_instance(self.hass)
        ready = getattr(recorder,'async_db_ready',None)
        if ready is not None and (not ready.done() or ready.cancelled() or not ready.result()): return
        if recorder.entity_filter is not None and any(not recorder.entity_filter(e) for e in sources): return
        try:
            data = await recorder.async_add_executor_job(partial(statistics_during_period,
                self.hass,start,dt_util.as_utc(now),set(sources),'day',{'energy':'kWh'},{'change'}))
        except (HomeAssistantError, SQLAlchemyError, OSError) as err:
            LOGGER.debug('Could not read WP consumption statistics: %s',err)
            return
        if period_start(dt_util.now(),self.period) != period_start(now,self.period): return
        self._attr_native_value = sum_changes(data,sources)
        self._attr_extra_state_attributes['statistics_as_of'] = max(
            (r['end'] for rows in data.values() for r in rows if 'end' in r),default=None)

    @property
    def available(self):
        return self._attr_native_value is not None
