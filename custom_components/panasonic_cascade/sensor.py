"""Expose numeric and text points plus equipment mode and counters."""
from datetime import timedelta
from homeassistant.helpers.entity import EntityCategory

from homeassistant.components.sensor import SensorDeviceClass, SensorEntity, SensorStateClass

from .const import COUNT_FIELDS, CONFIG_FIELDS
from .entity import CascadeEntity
from .runtime import CascadeDailyStartsSensor

SCAN_INTERVAL = timedelta(seconds=60)
from .model import state, unit, model_key
from .zinc import MARKER, Number, value

UNIT_CLASS = {
    "°C": SensorDeviceClass.TEMPERATURE, "°F": SensorDeviceClass.TEMPERATURE,
    "kW": SensorDeviceClass.POWER, "W": SensorDeviceClass.POWER,
    "kWh": SensorDeviceClass.ENERGY, "Wh": SensorDeviceClass.ENERGY,
    "Hz": SensorDeviceClass.FREQUENCY, "A": SensorDeviceClass.CURRENT,
    "h": SensorDeviceClass.DURATION, "min": SensorDeviceClass.DURATION,
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
            for field in ("mode", *COUNT_FIELDS, *CONFIG_FIELDS):
                if row.get(field) is not None:
                    entities.append(CascadeSensor(coordinator, ident, field))
        if model_key(row) == "heatPump" and "isRunning" in row:
            entities.append(CascadeDailyStartsSensor(coordinator, ident))
    async_add_entities(entities)


class CascadeSensor(CascadeEntity, SensorEntity):
    def __init__(self, coordinator, ident, field="curVal"):
        super().__init__(coordinator, ident, field)
        row = coordinator.data[ident]
        if ident.endswith(':calculatedCop'):
            self._attr_suggested_display_precision = 2
        diagnostic = field in CONFIG_FIELDS or row.get("diagnostic") is MARKER or model_key(row) in ("errorCodeConnected", "errorCode")
        if diagnostic:
            self._attr_entity_category = EntityCategory.DIAGNOSTIC
        if (field == "curVal" and row.get("kind") == "Number") or isinstance(row.get(field), Number):
            u = unit(row) if field == "curVal" else row[field].unit
            self._attr_native_unit_of_measurement = "%" if u == "%RH" else u or None
            self._attr_device_class = UNIT_CLASS.get(u)
            # Do not infer cumulative energy statistics from ambiguous energy tags.
            if self._attr_device_class == SensorDeviceClass.ENERGY:
                if row.get("hisTotalized") is MARKER:
                    self._attr_state_class = SensorStateClass.TOTAL_INCREASING
            elif not diagnostic:
                self._attr_state_class = SensorStateClass.MEASUREMENT

    @property
    def extra_state_attributes(self):
        return self.row.get("attributes") or None

    @property
    def native_value(self):
        if self.field == "curVal":
            return state(self.row)
        raw = value(self.row.get(self.field))
        return raw if isinstance(raw, (int, float, str)) and not isinstance(raw, bool) else None
