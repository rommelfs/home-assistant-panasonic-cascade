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
    async def test_storage_resource_removes_early_module_but_preserves_other_scripts(self):
        with tempfile.TemporaryDirectory() as directory:
            hass=HomeAssistant(directory)
            resources=ResourceStorageCollection(hass,SimpleNamespace(async_load=AsyncMock(return_value={})))
            hass.data[LOVELACE_DATA]=SimpleNamespace(resources=resources)
            manager=frontend.frontend.UrlManager(lambda *args:None,[frontend.LEGACY_CARD_URL+'?v=old','/local/other.js'])
            hass.data[frontend.frontend.DATA_EXTRA_MODULE_URL]=manager
            hass.http=SimpleNamespace(async_register_static_paths=AsyncMock())
            await frontend.async_setup_frontend(hass)
            self.assertEqual(manager.urls,frozenset(['/local/other.js']))
            self.assertEqual(len(list(resources.async_items())),1)
            hass.data[LOVELACE_DATA].resources=ResourceYAMLCollection([])
            await frontend.async_setup_frontend(hass)
            self.assertIn(frontend.module_url(hass),manager.urls)
            await hass.async_stop()

    async def test_real_resource_storage_updates_old_url_and_retains_unrelated_resources(self):
        with tempfile.TemporaryDirectory() as directory:
            hass=HomeAssistant(directory)
            resources=ResourceStorageCollection(hass,SimpleNamespace(async_load=AsyncMock(return_value={})))
            await resources.async_create_item({'url':frontend.CARD_URL+'?v=0.6.0','res_type':'module'})
            await resources.async_create_item({'url':frontend.CARD_URL+'?v=0.6.1','res_type':'module'})
            other=await resources.async_create_item({'url':'/local/other.js','res_type':'module'})
            hass.data[LOVELACE_DATA]=SimpleNamespace(resources=resources)
            hass.data[frontend.frontend.DATA_EXTRA_MODULE_URL]=frontend.frontend.UrlManager(lambda *args:None,[])
            hass.http=SimpleNamespace(async_register_static_paths=AsyncMock())
            with patch.object(frontend.frontend,'add_extra_js_url') as add:
                await frontend.async_setup_frontend(hass)
                await frontend.async_setup_frontend(hass)
            items=list(resources.async_items())
            self.assertEqual(len(items),2)
            self.assertIn(other,items)
            self.assertEqual(next(i for i in items if i['id']!=other['id'])['url'],frontend.module_url(hass))
            self.assertEqual(next(i for i in items if i['id']!=other['id'])['type'],'module')
            hass.http.async_register_static_paths.assert_awaited_once()
            add.assert_not_called()
            await hass.async_stop()

    async def test_empty_resources_get_one_module_and_yaml_is_left_unchanged(self):
        with tempfile.TemporaryDirectory() as directory:
            hass=HomeAssistant(directory)
            resources=ResourceStorageCollection(hass,SimpleNamespace(async_load=AsyncMock(return_value={})))
            hass.data[LOVELACE_DATA]=SimpleNamespace(resources=resources)
            hass.data[frontend.frontend.DATA_EXTRA_MODULE_URL]=frontend.frontend.UrlManager(lambda *args:None,[])
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
             patch.object(integration,'async_setup_charge',new=AsyncMock()), \
             patch.object(integration,'CascadeCoordinator',return_value=coordinator), \
             patch.object(integration,'async_apply_dhw_visibility',new=AsyncMock()), \
             patch.object(integration,'async_register_dashboard_service'),patch.object(integration,'async_call_later') as later, \
             patch.object(integration,'async_refresh_starts_tables',new=AsyncMock()) as refresh:
            await integration.async_setup_entry(hass,entry)
            await later.call_args.args[2](None)
        self.assertEqual(order,['frontend','refresh','platforms'])
        self.assertEqual(later.call_args.args[1],15)
        refresh.assert_awaited_once_with(hass)

    async def test_http_file_is_served_before_frontend_ready_and_registration_retries_at_started(self):
        from aiohttp.test_utils import TestClient, TestServer
        from homeassistant.components.http.server import HomeAssistantHTTP
        from homeassistant.helpers.http import KEY_ALLOW_CONFIGURED_CORS
        from homeassistant.const import EVENT_HOMEASSISTANT_STARTED
        from homeassistant.core import CoreState
        with tempfile.TemporaryDirectory() as directory:
            hass=HomeAssistant(directory)
            hass.http=HomeAssistantHTTP(hass,None,None,None,['127.0.0.1'],0,[],'modern')
            hass.http.app[KEY_ALLOW_CONFIGURED_CORS]=lambda resource:None
            # No frontend URL manager yet: the previous implementation returned before registering HTTP.
            await frontend.async_setup_frontend(hass)
            client=TestClient(TestServer(hass.http.app))
            await client.start_server()
            try:
                for path in (frontend.LEGACY_CARD_URL+'?v=0.6.2',frontend.module_url(hass)):
                    response=await client.get(path)
                    self.assertEqual(response.status,200)
                    self.assertIn('javascript',response.headers['Content-Type'])
                    self.assertIn("customElements.define('panasonic-cascade-heating-curve'",await response.text())
                resources=ResourceStorageCollection(hass,SimpleNamespace(async_load=AsyncMock(return_value={})))
                hass.data[LOVELACE_DATA]=SimpleNamespace(resources=resources)
                hass.data[frontend.frontend.DATA_EXTRA_MODULE_URL]=frontend.frontend.UrlManager(lambda *args:None,[])
                with patch.object(frontend.frontend,'add_extra_js_url') as add:
                    hass.state=CoreState.running
                    hass.bus.async_fire(EVENT_HOMEASSISTANT_STARTED)
                    await hass.async_block_till_done()
                    add.assert_not_called()
                self.assertEqual(len(list(resources.async_items())),1)
            finally:
                await client.close()
                await hass.async_stop()


@unittest.skipIf(frontend is None,'Home Assistant required')
class BootResourceTest(unittest.TestCase):
    def test_cache_key_is_stable_within_boot_and_changes_after_restart(self):
        first=SimpleNamespace(data={}); second=SimpleNamespace(data={})
        url=frontend.module_url(first)
        self.assertEqual(url,frontend.module_url(first))
        self.assertNotEqual(url,frontend.module_url(second))
        self.assertIn('boot=',url)
