"""Real Lovelace resource storage, migration, and early startup registration."""
import importlib
import tempfile
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch
import unittest

try:
    integration=importlib.import_module('custom_components.panasonic_cascade')
    frontend=importlib.import_module('custom_components.panasonic_cascade.frontend')
    from homeassistant.core import HomeAssistant
    from homeassistant.components.lovelace.resources import ResourceStorageCollection, ResourceYAMLCollection
    from homeassistant.components.lovelace.const import LOVELACE_DATA
except ImportError:
    frontend=None


@unittest.skipIf(frontend is None,'Home Assistant required')
class FrontendRegistrationTest(unittest.IsolatedAsyncioTestCase):
    async def test_real_resource_storage_updates_old_url_and_retains_unrelated_resources(self):
        with tempfile.TemporaryDirectory() as directory:
            hass=HomeAssistant(directory)
            resources=ResourceStorageCollection(hass,SimpleNamespace(async_load=AsyncMock(return_value={})))
            await resources.async_create_item({'url':frontend.CARD_URL+'?v=0.6.0','res_type':'module'})
            await resources.async_create_item({'url':frontend.CARD_URL+'?v=0.6.1','res_type':'module'})
            other=await resources.async_create_item({'url':'/local/other.js','res_type':'module'})
            hass.data[LOVELACE_DATA]=SimpleNamespace(resources=resources)
            hass.data[frontend.frontend.DATA_EXTRA_MODULE_URL]=Mock()
            hass.http=SimpleNamespace(async_register_static_paths=AsyncMock())
            with patch.object(frontend.frontend,'add_extra_js_url') as add:
                await frontend.async_setup_frontend(hass)
                await frontend.async_setup_frontend(hass)
            items=list(resources.async_items())
            self.assertEqual(len(items),2)
            self.assertIn(other,items)
            self.assertEqual(next(i for i in items if i['id']!=other['id'])['url'],frontend.CARD_URL+'?v=0.6.2')
            self.assertEqual(next(i for i in items if i['id']!=other['id'])['type'],'module')
            hass.http.async_register_static_paths.assert_awaited_once()
            add.assert_called_once()
            await hass.async_stop()

    async def test_empty_resources_get_one_module_and_yaml_is_left_unchanged(self):
        with tempfile.TemporaryDirectory() as directory:
            hass=HomeAssistant(directory)
            resources=ResourceStorageCollection(hass,SimpleNamespace(async_load=AsyncMock(return_value={})))
            hass.data[LOVELACE_DATA]=SimpleNamespace(resources=resources)
            hass.data[frontend.frontend.DATA_EXTRA_MODULE_URL]=Mock()
            hass.http=SimpleNamespace(async_register_static_paths=AsyncMock())
            with patch.object(frontend.frontend,'add_extra_js_url'):
                await frontend.async_setup_frontend(hass)
            self.assertEqual(len(list(resources.async_items())),1)
            yaml=ResourceYAMLCollection([{'url':'/local/yaml.js','type':'module'}])
            hass.data[LOVELACE_DATA].resources=yaml
            await frontend.async_setup_frontend(hass)
            self.assertEqual(yaml.async_items(),[{'url':'/local/yaml.js','type':'module'}])
            await hass.async_stop()

    async def test_card_registration_precedes_controller_and_platform_setup(self):
        order=[]
        hass=Mock(); entry=SimpleNamespace(data={},options={},async_on_unload=Mock(),add_update_listener=Mock())
        hass.config_entries.async_forward_entry_setups=AsyncMock(side_effect=lambda *args:order.append('platforms'))
        coordinator=SimpleNamespace(all_data={},async_config_entry_first_refresh=AsyncMock(side_effect=lambda:order.append('refresh')))
        with patch.object(integration,'async_setup_frontend',new=AsyncMock(side_effect=lambda *args:order.append('frontend'))), \
             patch.object(integration,'async_get_clientsession'),patch.object(integration,'CascadeClient'), \
             patch.object(integration,'CascadeCoordinator',return_value=coordinator), \
             patch.object(integration,'async_apply_dhw_visibility',new=AsyncMock()), \
             patch.object(integration,'async_register_dashboard_service'):
            await integration.async_setup_entry(hass,entry)
        self.assertEqual(order,['frontend','refresh','platforms'])
