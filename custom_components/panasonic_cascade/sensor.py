"""Expose numeric and text points plus equipment mode and counters."""
from homeassistant.components.sensor import SensorDeviceClass, SensorEntity, SensorStateClass

from .const import COUNT_FIELDS
from .entity import CascadeEntity
from .model import state, unit
from .zinc import MARKER, value

UNIT_CLASS = {
    "°C": SensorDeviceClass.TEMPERATURE, "°F": SensorDeviceClass.TEMPERATURE,
    "kW": SensorDeviceClass.POWER, "W": SensorDeviceClass.POWER,
    "kWh": SensorDeviceClass.ENERGY, "Wh": SensorDeviceClass.ENERGY,
    "Hz": SensorDeviceClass.FREQUENCY, "A": SensorDeviceClass.CURRENT,
    "V": SensorDeviceClass.VOLTAGE, "bar": SensorDeviceClass.PRESSURE,
    "%RH": SensorDeviceClass.HUMIDITY,
}


async def async_setup_entry(hass, entry, async_add_entities):
    coordinator = entry.runtime_data
    entities = []
    for ident, row in coordinator.data.items():
        if row.get("point") is MARKER and row.get("kind") in ("Number", "Str"):
            entities.append(CascadeSensor(coordinator, ident))
        if row.get("equip") is MARKER:
            for field in ("mode", *COUNT_FIELDS):
                if row.get(field) is not None:
                    entities.append(CascadeSensor(coordinator, ident, field))
    async_add_entities(entities)


class CascadeSensor(CascadeEntity, SensorEntity):
    def __init__(self, coordinator, ident, field="curVal"):
        super().__init__(coordinator, ident, field)
        row = coordinator.data[ident]
        if field == "curVal" and row.get("kind") == "Number":
            u = unit(row)
            self._attr_native_unit_of_measurement = "%" if u == "%RH" else u or None
            self._attr_device_class = UNIT_CLASS.get(u)
            # Do not infer cumulative energy statistics from ambiguous energy tags.
            if self._attr_device_class != SensorDeviceClass.ENERGY:
                self._attr_state_class = SensorStateClass.MEASUREMENT

    @property
    def native_value(self):
        if self.field == "curVal":
            return state(self.row)
        raw = value(self.row.get(self.field))
        return raw if isinstance(raw, (int, float, str)) and not isinstance(raw, bool) else None
