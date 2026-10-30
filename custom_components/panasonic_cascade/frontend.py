"""Serve the bundled, dependency-free heating curve card."""
import asyncio
import logging
import re
from secrets import token_hex
from pathlib import Path

from homeassistant.components import frontend
from homeassistant.components.http import StaticPathConfig
from homeassistant.components.lovelace.const import LOVELACE_DATA
from homeassistant.components.lovelace.resources import ResourceStorageCollection
from homeassistant.exceptions import HomeAssistantError
from homeassistant.core import CoreState
from homeassistant.helpers.start import async_at_started

from .const import DOMAIN

LEGACY_CARD_URL = '/panasonic_cascade/heating-curve.js'
CARD_URL = '/panasonic_cascade/heating-curve-0.10.0.js'
CARD_VERSION = '0.10.0'
LOGGER = logging.getLogger(__name__)


def module_url(hass):
    """A fresh URL after each HA boot recovers clients that imported before HTTP was ready."""
    key = f'{DOMAIN}_frontend_boot'
    if key not in hass.data:
        hass.data[key] = token_hex(8)
    return f'{CARD_URL}?v={CARD_VERSION}&boot={hass.data[key]}'


async def async_setup_frontend(hass):
    if not getattr(hass, "http", None):
        return
    lock = hass.data.setdefault(f'{DOMAIN}_frontend_lock', asyncio.Lock())
    async with lock:
        if not hass.data.get(f'{DOMAIN}_frontend_ready'):
            await hass.http.async_register_static_paths([
                StaticPathConfig(CARD_URL, str(Path(__file__).parent / 'www' / 'heating-curve.js'), False),
                StaticPathConfig('/panasonic_cascade/heating-curve-0.8.1.js', str(Path(__file__).parent / 'www' / 'heating-curve.js'), False),
                StaticPathConfig('/panasonic_cascade/heating-curve-0.8.0.js', str(Path(__file__).parent / 'www' / 'heating-curve.js'), False),
                StaticPathConfig('/panasonic_cascade/heating-curve-0.7.0.js', str(Path(__file__).parent / 'www' / 'heating-curve.js'), False),
                StaticPathConfig(LEGACY_CARD_URL, str(Path(__file__).parent / 'www' / 'heating-curve.js'), False)
            ])
            hass.data[f'{DOMAIN}_frontend_ready'] = True
        lovelace = hass.data.get(LOVELACE_DATA)
        resources = getattr(lovelace, 'resources', None)
        # Extra modules run in parallel with the HA app, before the scoped
        # element registry may be installed. Lovelace resources are awaited.
        # Never publish the same card by both routes (module caching then keeps
        # the early registration from being repeated in the final registry).
        manager = hass.data.get(frontend.DATA_EXTRA_MODULE_URL)
        if isinstance(resources, ResourceStorageCollection) and manager is not None:
            for url in tuple(getattr(manager, 'urls', ())):
                if re.fullmatch(r'/panasonic_cascade/heating-curve(?:-[0-9.]+)?\.js', url.split('?')[0]):
                    frontend.remove_extra_js_url(hass, url)
        elif resources is not None and manager is not None and not hass.data.get(f'{DOMAIN}_frontend_module'):
            # YAML resources are user-managed. The module itself waits for HA's
            # final registry before defining the class on this fallback path.
            frontend.add_extra_js_url(hass, module_url(hass))
            hass.data[f'{DOMAIN}_frontend_module'] = True
        if isinstance(resources, ResourceStorageCollection):
            try:
                await resources.async_get_info()  # Public API loads the collection from storage.
                matches = [item for item in resources.async_items()
                           if re.fullmatch(r'/panasonic_cascade/heating-curve(?:-[0-9.]+)?\.js', item.get('url', '').split('?')[0])]
                resource = {'url':module_url(hass), 'res_type':'module'}
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
        if (frontend.DATA_EXTRA_MODULE_URL not in hass.data or not lovelace) and getattr(hass, 'state', CoreState.running) is not CoreState.running:
            if not hass.data.get(f'{DOMAIN}_frontend_deferred'):
                hass.data[f'{DOMAIN}_frontend_deferred'] = True
                async_at_started(hass, async_setup_frontend)
