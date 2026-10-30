"""Panasonic Cascade / Smart Edge integration."""
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.start import async_at_started
from homeassistant.helpers.event import async_call_later

from .api import CascadeClient
from .const import PLATFORMS
from .coordinator import CascadeCoordinator
from .dashboard import async_register_dashboard_service, async_refresh_starts_tables
from .visibility import async_apply_dhw_visibility
from .notifications import AlarmMonitor
from .frontend import async_setup_frontend


async def async_setup_entry(hass, entry):
    await async_setup_frontend(hass)
    config = {**entry.data, **entry.options}
    client = CascadeClient(async_get_clientsession(hass, verify_ssl=config.get("verify_ssl", True)), config)
    coordinator = CascadeCoordinator(hass, entry, client)
    await coordinator.async_config_entry_first_refresh()
    await async_apply_dhw_visibility(hass, entry, coordinator.all_data)
    entry.runtime_data = coordinator
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    async_register_dashboard_service(hass)
    entry.async_on_unload(async_at_started(hass, async_refresh_starts_tables))
    async def refresh_dashboard(_):
        await async_refresh_starts_tables(hass)
    # Unrelated slow integrations must not hold dashboard upgrades until HA_STARTED.
    entry.async_on_unload(async_call_later(hass, 15, refresh_dashboard))
    if entry.options.get("alarm_notify_service"):
        monitor = AlarmMonitor(hass, entry, coordinator)
        coordinator.alarm_monitor = monitor
        await monitor.async_start()
        entry.async_on_unload(monitor.async_stop)
    entry.async_on_unload(entry.add_update_listener(async_reload_entry))
    return True


async def async_unload_entry(hass, entry):
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)


async def async_reload_entry(hass, entry):
    await hass.config_entries.async_reload(entry.entry_id)
