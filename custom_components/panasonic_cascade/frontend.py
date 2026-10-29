"""Serve the bundled, dependency-free heating curve card."""
import asyncio
import logging
from pathlib import Path

from homeassistant.components import frontend
from homeassistant.components.http import StaticPathConfig
from homeassistant.components.lovelace.const import LOVELACE_DATA
from homeassistant.components.lovelace.resources import ResourceStorageCollection
from homeassistant.exceptions import HomeAssistantError

from .const import DOMAIN

CARD_URL = '/panasonic_cascade/heating-curve.js'
CARD_VERSION = '0.6.2'
LOGGER = logging.getLogger(__name__)


async def async_setup_frontend(hass):
    if frontend.DATA_EXTRA_MODULE_URL not in hass.data:
        return
    lock = hass.data.setdefault(f'{DOMAIN}_frontend_lock', asyncio.Lock())
    async with lock:
        if not hass.data.get(f'{DOMAIN}_frontend_ready'):
            await hass.http.async_register_static_paths([
                StaticPathConfig(CARD_URL, str(Path(__file__).parent / 'www' / 'heating-curve.js'), False)
            ])
            frontend.add_extra_js_url(hass, f'{CARD_URL}?v={CARD_VERSION}')
            hass.data[f'{DOMAIN}_frontend_ready'] = True
        lovelace = hass.data.get(LOVELACE_DATA)
        resources = getattr(lovelace, 'resources', None)
        if isinstance(resources, ResourceStorageCollection):
            try:
                await resources.async_get_info()  # Public API loads the collection from storage.
                matches = [item for item in resources.async_items()
                           if item.get('url', '').split('?')[0] == CARD_URL]
                resource = {'url':f'{CARD_URL}?v={CARD_VERSION}', 'res_type':'module'}
                if not matches:
                    await resources.async_create_item(resource)
                else:
                    first = matches[0]
                    if first.get('url') != resource['url'] or first.get('type') != 'module':
                        await resources.async_update_item(first['id'], resource)
                    for duplicate in matches[1:]:
                        await resources.async_delete_item(duplicate['id'])
            except (HomeAssistantError, OSError) as err:
                # Dashboard resource problems must not prevent sensor/control setup.
                LOGGER.warning('Could not register heating curve dashboard resource: %s', err)
