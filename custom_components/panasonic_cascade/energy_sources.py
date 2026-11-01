"""Read-only source attribution, using independent metering mappings."""
import time
from datetime import timedelta
from homeassistant.components.sensor import SensorEntity, SensorDeviceClass, SensorStateClass
from homeassistant.core import callback
from homeassistant.helpers.dispatcher import async_dispatcher_connect, async_dispatcher_send
from homeassistant.helpers.event import async_track_state_change_event, async_track_time_interval
from homeassistant.helpers.storage import Store
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.util import dt as dt_util
from .const import DOMAIN
from .calculated import watts
from .model import model_key
from .energy_accounting import Ledger, SOURCES, PERIODS, allocate

LABELS = {'pv':'PV', 'grid':'Netz', 'battery':'Batterie'}
PERIOD_LABELS = {'power':'Aktuell', 'total':'Gesamt', 'day':'Heute', 'week':'Woche', 'month':'Monat', 'year':'Jahr'}


def mapping(options, key, default=None):
    return options.get('energy_' + key, options.get('pv_charge_' + key, default))


def wp_power(rows):
    total = watts(rows.get('summary:consumedPower'))
    if total is not None:
        return total
    units = [ident for ident, row in rows.items() if model_key(row) == 'heatPump']
    values = [watts(rows.get(f'summary:unit:{ident}:consumedPower')) for ident in units]
    if values and all(v is not None for v in values):
        return sum(values)
    raise ValueError('Missing total electrical WP power')


class SourceAccounting:
    def __init__(self, coordinator):
        self.c, self.hass = coordinator, coordinator.hass
        self.options = coordinator.entry.options
        self.store = Store(self.hass, 1, f'{DOMAIN}.energy_sources.{coordinator.entry.entry_id}', atomic_writes=True)
        self.signal = f'{DOMAIN}_energy_sources_{coordinator.entry.entry_id}'
        self.unsub = []
        self.power = None
        self.reason = 'Waiting for measurements'
        self.clock = time.time
        self.reported = self.clock()
        self.closed = False

    async def initialize(self):
        self.ledger = Ledger(dt_util.DEFAULT_TIME_ZONE, await self.store.async_load())
        self.unsub.append(self.c.async_add_listener(self.controller_updated))
        self.unsub.append(async_track_state_change_event(self.hass,
            [mapping(self.options, key+'_sensor') for key in ('pv','export','battery')], self.tick))
        self.unsub.append(async_track_time_interval(self.hass, self.tick, timedelta(seconds=15)))
        from homeassistant.const import EVENT_HOMEASSISTANT_STOP
        self.unsub.append(self.hass.bus.async_listen_once(EVENT_HOMEASSISTANT_STOP, self.close))
        self.tick()

    @callback
    def controller_updated(self):
        if self.c.last_update_success:
            self.reported = self.clock()
        self.tick()

    def sample(self, now):
        if not self.c.last_update_success or now-self.reported > max(60, self.options.get('scan_interval',30)*2):
            raise ValueError('WP power feedback unavailable or stale')
        data = {}
        for key in ('pv','export','battery'):
            state = self.hass.states.get(mapping(self.options, key+'_sensor'))
            if state is None:
                raise ValueError('Missing '+key+' measurement')
            age = now - (getattr(state, 'last_reported', None) or state.last_updated).timestamp()
            if not -5 <= age <= self.options.get('energy_max_age_s',90):
                raise ValueError('Stale '+key+' measurement')
            scale = {'W':1,'kW':1000}.get(state.attributes.get('unit_of_measurement'))
            if scale is None:
                raise ValueError('Power sources require W/kW')
            data[key] = float(state.state) * scale
        data['export'] *= 1 if mapping(self.options,'export_positive',True) else -1
        data['battery'] *= 1 if mapping(self.options,'discharge_positive',True) else -1
        return allocate(wp_power(self.c.data), **data)

    @callback
    def tick(self, _event=None):
        if self.closed:
            return
        now = self.clock()
        try:
            self.power = self.sample(now)
            self.reason = ''
        except (ValueError, TypeError, OverflowError) as err:
            self.power, self.reason = None, str(err)
        self.ledger.update(now, self.power)
        self.store.async_delay_save(self.ledger.dump, 30)
        async_dispatcher_send(self.hass, self.signal)

    async def close(self, _event=None):
        if self.closed:
            return
        self.tick()  # Flush only a valid bounded interval; never integrate downtime.
        self.closed = True
        for remove in self.unsub:
            remove()
        self.unsub.clear()
        await self.store.async_save(self.ledger.dump())


class SourceSensor(SensorEntity):
    _attr_should_poll = False
    _attr_has_entity_name = False

    def __init__(self, manager, source, period):
        self.manager, self.source, self.period = manager, source, period
        entry = manager.c.entry
        self._attr_unique_id = f'{entry.unique_id}|energy_source:{source}:{period}'
        self._attr_name = f'WP · {LABELS[source]} · {PERIOD_LABELS[period]} (zugeordnet)'
        self._attr_device_info = DeviceInfo(identifiers={(DOMAIN,entry.unique_id+'|energy_sources')},
            name='WP · Stromherkunft (Zuordnung)', manufacturer='Panasonic', model='Calculated household power mix')
        self._attr_native_unit_of_measurement = 'W' if period=='power' else 'kWh'
        self._attr_device_class = SensorDeviceClass.POWER if period=='power' else SensorDeviceClass.ENERGY
        self._attr_suggested_display_precision = 0 if period=='power' else 2
        if period in ('power','total'):
            self._attr_state_class = SensorStateClass.MEASUREMENT if period=='power' else SensorStateClass.TOTAL_INCREASING

    async def async_added_to_hass(self):
        self.async_on_remove(async_dispatcher_connect(self.hass,self.manager.signal,self.async_write_ha_state))

    @property
    def available(self):
        if self.period=='power':
            return self.manager.power is not None
        if self.period in PERIODS:
            return self.manager.ledger.periods[self.period]['observed_seconds'] > 0
        return self.manager.ledger.started is not None

    @property
    def native_value(self):
        if self.period=='power':
            return self.manager.power[self.source] if self.manager.power is not None else None
        if self.period=='total':
            return self.manager.ledger.total[self.source]
        return self.manager.ledger.periods[self.period]['energy'][self.source]

    @property
    def extra_state_attributes(self):
        result = {'estimated':True,'method':'PV-first household balance; proportional attribution to all heat pumps',
                  'battery_origin':'not inferred', 'measurement_issue':self.manager.reason or None,
                  'recording_started':self.manager.ledger.started, 'scope':'all heat pumps',
                  'source_entities':{key:mapping(self.manager.options,key+'_sensor') for key in ('pv','export','battery')}}
        if self.period in PERIODS:
            record = self.manager.ledger.periods[self.period]
            result.update(period=record['key'],observed_seconds=round(record['observed_seconds']))
        return result


async def setup_sources(coordinator, entry):
    options = entry.options
    coordinator.energy_sources = None
    if not options.get('energy_sources_enabled',True) or not all(mapping(options,key+'_sensor') for key in ('pv','export','battery')):
        return
    manager = coordinator.energy_sources = SourceAccounting(coordinator)
    await manager.initialize()
