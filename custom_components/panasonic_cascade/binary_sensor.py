"""Expose boolean points and equipment status."""
from homeassistant.components.binary_sensor import BinarySensorDeviceClass, BinarySensorEntity

from .const import STATUS_FIELDS
from .entity import CascadeEntity
from .model import state, model_key
from .zinc import MARKER


async def async_setup_entry(hass, entry, async_add_entities):
    coordinator = entry.runtime_data
    entities = []
    for ident, row in coordinator.data.items():
        if row.get("point") is MARKER and row.get("kind") == "Bool":
            entities.append(CascadeBinarySensor(coordinator, ident))
        if row.get("equip") is MARKER:
            entities.extend(CascadeBinarySensor(coordinator, ident, field) for field in STATUS_FIELDS if type(row.get(field)) is bool)
    async_add_entities(entities)


class CascadeBinarySensor(CascadeEntity, BinarySensorEntity):
    def __init__(self, coordinator, ident, field="curVal"):
        super().__init__(coordinator, ident, field)
        if field == "isInAlarm" or (field == "curVal" and model_key(row) == "errorStatus"):
            self._attr_device_class = BinarySensorDeviceClass.PROBLEM
        elif field == "isConnected":
            self._attr_device_class = BinarySensorDeviceClass.CONNECTIVITY
        elif field == "isRunning":
            self._attr_device_class = BinarySensorDeviceClass.RUNNING

    @property
    def is_on(self):
        raw = state(self.row) if self.field == "curVal" else self.row.get(self.field)
        return raw if type(raw) is bool else None
