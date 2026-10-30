"""Opt-in boolean Set Default controls."""
from homeassistant.components.switch import SwitchEntity

from .entity import CascadeEntity
from .model import control_kind, model_key, zone_states

PARALLEL_UPDATES = 1


async def async_setup_entry(hass, entry, async_add_entities):
    if entry.options.get("enable_controls", False):
        c = entry.runtime_data
        entities = [CascadeSwitch(c, i) for i, r in c.data.items() if control_kind(r) == "switch"]
        entities.extend(CascadeZone1Switch(c, i) for i, r in c.data.items()
                        if model_key(r) == "zone1Zone2OnOffSetpoint" and control_kind(r) == "select")
        async_add_entities(entities)


class CascadeSwitch(CascadeEntity, SwitchEntity):
    def __init__(self, coordinator, ident):
        super().__init__(coordinator, ident)
        self._attr_unique_id += "|control"
        self._attr_name += " · Vorgabe"

    @property
    def is_on(self):
        # Show the default being edited, not an overriding schedule/manual value.
        raw = self.row.get("writeDef")
        return raw if type(raw) is bool else None

    async def async_turn_on(self, **kwargs):
        await self.coordinator.write(self.ident, True)

    async def async_turn_off(self, **kwargs):
        await self.coordinator.write(self.ident, False)


class CascadeZone1Switch(CascadeEntity, SwitchEntity):
    _attr_icon = "mdi:radiator"

    def __init__(self, coordinator, ident):
        super().__init__(coordinator, ident)
        self._attr_unique_id += "|zone1_control"
        self._attr_name = "Zone 1 – Ein/Aus"

    @property
    def is_on(self):
        try:
            return zone_states(self.row.get("curVal"))[0] == "On"
        except ValueError:
            return None

    async def async_turn_on(self, **kwargs):
        await self.coordinator.write_zone1(self.ident, True)

    async def async_turn_off(self, **kwargs):
        await self.coordinator.write_zone1(self.ident, False)
