"""Panasonic Cascade / Smart Edge integration."""
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .api import CascadeClient
from .const import PLATFORMS
from .coordinator import CascadeCoordinator


async def async_setup_entry(hass, entry):
    config = {**entry.data, **entry.options}
    client = CascadeClient(async_get_clientsession(hass, verify_ssl=config.get("verify_ssl", True)), config)
    coordinator = CascadeCoordinator(hass, entry, client)
    await coordinator.async_config_entry_first_refresh()
    entry.runtime_data = coordinator
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    entry.async_on_unload(entry.add_update_listener(async_reload_entry))
    return True


async def async_unload_entry(hass, entry):
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)


async def async_reload_entry(hass, entry):
    await hass.config_entries.async_reload(entry.entry_id)
