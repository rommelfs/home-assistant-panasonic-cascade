"""Opt-in boolean Set Default controls."""
from homeassistant.components.switch import SwitchEntity

from .entity import CascadeEntity
from .model import control_kind

PARALLEL_UPDATES = 1


async def async_setup_entry(hass, entry, async_add_entities):
    if entry.options.get("enable_controls", False):
        c = entry.runtime_data
        async_add_entities(CascadeSwitch(c, i) for i, r in c.data.items() if control_kind(r) == "switch")


class CascadeSwitch(CascadeEntity, SwitchEntity):
    def __init__(self, coordinator, ident):
        super().__init__(coordinator, ident)
        self._attr_unique_id += "|control"
        self._attr_name += " | Set Default"

    @property
    def is_on(self):
        # Show the default being edited, not an overriding schedule/manual value.
        raw = self.row.get("writeDef")
        return raw if type(raw) is bool else None

    async def async_turn_on(self, **kwargs):
        await self.coordinator.write(self.ident, True)

    async def async_turn_off(self, **kwargs):
        await self.coordinator.write(self.ident, False)
