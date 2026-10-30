"""Expose boolean points and equipment status."""
from homeassistant.components.binary_sensor import BinarySensorDeviceClass, BinarySensorEntity

from .const import STATUS_FIELDS
from .entity import CascadeEntity
from .model import state, model_key, name, unit
from .labels import compact_label
from .runtime import power_on, power_threshold
from .zinc import MARKER


async def async_setup_entry(hass, entry, async_add_entities):
    coordinator = entry.runtime_data
    entities = []
    for ident, row in coordinator.data.items():
        if row.get("point") is MARKER and row.get("kind") == "Bool":
            entities.append(CascadeBinarySensor(coordinator, ident))
        if row.get("equip") is MARKER:
            entities.extend(CascadeBinarySensor(coordinator, ident, field) for field in STATUS_FIELDS if type(row.get(field)) is bool)
            if model_key(row) == 'heatPump':
                entities.append(CascadePowerRunningSensor(coordinator, ident))
    async_add_entities(entities)


class CascadeBinarySensor(CascadeEntity, BinarySensorEntity):
    def __init__(self, coordinator, ident, field="curVal"):
        super().__init__(coordinator, ident, field)
        row = self.row
        if field == "isInAlarm" or (field == "curVal" and model_key(row) == "errorStatus"):
            self._attr_device_class = BinarySensorDeviceClass.PROBLEM
        elif field == "isConnected":
            self._attr_device_class = BinarySensorDeviceClass.CONNECTIVITY
        elif field == "isRunning":
            self._attr_icon = 'mdi:check-circle-outline'

    @property
    def is_on(self):
        raw = state(self.row) if self.field == "curVal" else self.row.get(self.field)
        return raw if type(raw) is bool else None


class CascadePowerRunningSensor(CascadeEntity, BinarySensorEntity):
    """Electrical activity estimate; explicitly separate from controller enable."""
    _attr_device_class = BinarySensorDeviceClass.RUNNING

    def __init__(self, coordinator, ident):
        super().__init__(coordinator, ident, 'power_running')
        self._attr_name = compact_label(name(self.row)) + ' · Betrieb (Leistung)'

    @property
    def power_row(self):
        return self.coordinator.data.get(f'summary:unit:{self.ident}:consumedPower', {})

    @property
    def is_on(self):
        row = self.power_row
        if row.get('curStatus') not in (None, 'ok'):
            return None
        return power_on(state(row), unit(row), power_threshold(self.coordinator))

    @property
    def available(self):
        return super().available and self.is_on is not None

    @property
    def extra_state_attributes(self):
        return {'threshold_w':power_threshold(self.coordinator), 'counting_method':'power_threshold',
                'source':'Per-unit total electrical power; estimated compressor activity'}
