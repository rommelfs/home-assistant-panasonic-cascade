"""Opt-in bounded temperature setpoints and heating-curve defaults."""
from homeassistant.components.number import NumberDeviceClass, NumberEntity, NumberMode

from .entity import CascadeEntity
from .model import bounds, control_kind
from .zinc import value

PARALLEL_UPDATES = 1


async def async_setup_entry(hass, entry, async_add_entities):
    if entry.options.get("enable_controls", False):
        c = entry.runtime_data
        async_add_entities(CascadeNumber(c, i) for i, r in c.data.items() if control_kind(r) == "number")


class CascadeNumber(CascadeEntity, NumberEntity):
    _attr_native_unit_of_measurement = "°C"
    _attr_native_step = 1
    _attr_device_class = NumberDeviceClass.TEMPERATURE
    _attr_mode = NumberMode.BOX

    def __init__(self, coordinator, ident):
        super().__init__(coordinator, ident)
        self._attr_unique_id += "|control"
        self._attr_name += " · Vorgabe"

    @property
    def native_min_value(self):
        return bounds(self.row)[0]

    @property
    def native_max_value(self):
        return bounds(self.row)[1]

    @property
    def native_value(self):
        raw = value(self.row.get("writeDef"))
        return raw if type(raw) in (int, float) else None

    async def async_set_native_value(self, value):
        await self.coordinator.write(self.ident, value)
