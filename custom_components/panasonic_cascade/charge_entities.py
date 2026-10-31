"""Compact status and start/stop buttons for temporary buffer charging."""
from datetime import UTC, datetime
from homeassistant.components.button import ButtonEntity
from homeassistant.components.binary_sensor import BinarySensorDeviceClass, BinarySensorEntity
from homeassistant.components.sensor import SensorEntity
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.dispatcher import async_dispatcher_connect
from homeassistant.core import callback
from homeassistant.exceptions import HomeAssistantError
from .const import DOMAIN
from .model import model_key, is_buffer_offset
from .zinc import value


class ChargeEntity:
    _attr_should_poll = False
    _attr_has_entity_name = False

    def __init__(self, coordinator):
        self.coordinator = coordinator
        self.manager = coordinator.buffer_charge
        entry = coordinator.entry
        self._attr_device_info = DeviceInfo(identifiers={(DOMAIN, entry.unique_id + '|' + entry.data['site_id'])},
                                           name=entry.title, manufacturer='Panasonic', model='Cascade Control / Smart Edge')

    async def async_added_to_hass(self):
        self.async_on_remove(async_dispatcher_connect(self.hass, self.manager.signal, self.refresh))

    @callback
    def refresh(self):
        self.async_write_ha_state()


class BufferChargeSensor(ChargeEntity, SensorEntity):
    _attr_name = 'PV-Pufferladung'
    _attr_icon = 'mdi:solar-power-variant'

    def __init__(self, coordinator):
        super().__init__(coordinator)
        self._attr_unique_id = coordinator.entry.unique_id + '|pv_buffer_charge'

    @property
    def native_value(self):
        if self.manager.status == 'charging' and (self.manager.lease or {}).get('temperature_unmonitored_test'):
            return 'Ladetest ohne Temperaturüberwachung'
        return {'disabled':'Deaktiviert', 'idle':'Bereit', 'charging':'Lädt', 'restore_pending':'Rückstellung ausstehend',
                'conflict':'Externe Änderung', 'waiting':'Wartet auf Überschuss', 'ready':'Startbereit',
                'blocked':'Gesperrt'}.get(self.manager.status, self.manager.status)

    @property
    def extra_state_attributes(self):
        manager = self.manager
        lease = manager.lease or {}
        try:
            measured = manager.readings()
        except (ValueError, TypeError):
            measured = {}
        def point(key):
            rows = [row for row in (self.coordinator.data or {}).values()
                    if row.get('bufferModelId') and model_key(row) == key and row.get('curStatus') == 'ok']
            return value(rows[0].get('curVal')) if len(rows) == 1 else None
        offsets = [row for row in (self.coordinator.data or {}).values() if is_buffer_offset(row)]
        return {'reason':manager.reason, 'phase':lease.get('phase'),
                'baseline_offset':lease.get('baseline'), 'requested_offset':lease.get('applied'),
                'effective_offset':value(offsets[0].get('curVal')) if len(offsets)==1 and offsets[0].get('curStatus')=='ok' else None,
                'buffer_target':point('bufferSetpoint'), 'zone_target':point('zone1WaterTemperatureSetpoint'),
                'buffer_temperature':measured.get('temperature'),
                'temperature_limit':None if lease.get('temperature_unmonitored_test') else manager.options['pv_charge_max_c'],
                'temperature_unmonitored_test':bool(lease.get('temperature_unmonitored_test')),
                'unmonitored_test_configured':manager.unmonitored_test,
                'remaining_minutes':round(max(0,lease.get('expires',0)-manager.clock())/60,1) if lease else 0,
                'expires_at':datetime.fromtimestamp(lease['expires'],UTC).isoformat() if lease else None,
                'automatic':manager.options['pv_charge_auto'], 'restoration_pending':bool(lease and lease['phase']!='charging')}


class BufferChargeButton(ChargeEntity, ButtonEntity):
    def __init__(self, coordinator, stop=False):
        super().__init__(coordinator)
        self.stop = stop
        self._attr_name = 'PV-Pufferladung beenden' if stop else 'PV-Pufferladung starten'
        self._attr_icon = 'mdi:stop-circle-outline' if stop else 'mdi:solar-power-variant'
        self._attr_unique_id = coordinator.entry.unique_id + ('|pv_buffer_charge_stop' if stop else '|pv_buffer_charge_start')

    @property
    def available(self):
        return bool(self.manager.lease) if self.stop else self.manager.configured() and self.coordinator.last_update_success and not self.manager.lease

    async def async_press(self):
        if self.stop:
            if not await self.manager.async_stop():
                raise HomeAssistantError('Buffer offset restoration is still pending; check the charge status')
        else:
            await self.manager.async_start()


class BufferChargeActive(ChargeEntity, BinarySensorEntity):
    _attr_name = 'PV-Pufferladung · Freigabe'
    _attr_device_class = BinarySensorDeviceClass.RUNNING
    _attr_icon = 'mdi:solar-power-variant'

    def __init__(self, coordinator):
        super().__init__(coordinator)
        self._attr_unique_id = coordinator.entry.unique_id + '|pv_buffer_charge_active'

    @property
    def is_on(self):
        lease = self.manager.lease
        if lease is None:
            return False
        if lease['phase'] != 'charging' or not self.coordinator.last_update_success:
            return None
        return True
