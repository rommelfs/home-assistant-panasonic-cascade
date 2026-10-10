"""Opt-in enumerated defaults."""
from homeassistant.components.select import SelectEntity

from .entity import CascadeEntity
from .model import control_kind, enum_options

PARALLEL_UPDATES = 1


async def async_setup_entry(hass, entry, async_add_entities):
    if entry.options.get("enable_controls", False):
        c = entry.runtime_data
        async_add_entities(CascadeSelect(c, i) for i, r in c.data.items() if control_kind(r) == "select")


class CascadeSelect(CascadeEntity, SelectEntity):
    def __init__(self, coordinator, ident):
        super().__init__(coordinator, ident)
        self._attr_unique_id += "|control"
        self._attr_name += " | Set Default"

    @property
    def options(self):
        return enum_options(self.row)

    @property
    def current_option(self):
        raw = self.row.get("writeDef")
        return raw if raw in self.options else None

    async def async_select_option(self, option):
        await self.coordinator.write(self.ident, option)
