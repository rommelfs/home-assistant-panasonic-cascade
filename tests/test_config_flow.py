"""Real Home Assistant flow classes with a fake FIN backend."""
import importlib
from pathlib import Path
import sys
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
try:
    flow_module = importlib.import_module('custom_components.panasonic_cascade.config_flow')
    from custom_components.panasonic_cascade.zinc import Ref
    from homeassistant.data_entry_flow import AbortFlow
except ImportError:
    flow_module = None


class FakeClient:
    def __init__(self, session, config):
        self.project = config.get('project', 'sys')
        self.config = config

    @staticmethod
    def _validate_project(project):
        if project not in ('one', 'two'):
            raise ValueError()

    async def projects(self):
        if self.config.get('password') == 'wrong':
            raise flow_module.AuthError()
        return [{'id':Ref('p:one'),'name':'one','dis':'First','routeStatus':'ok'},
                {'id':Ref('p:two'),'name':'two','dis':'Second','routeStatus':'ok'}]

    async def sites(self):
        return [{'id':Ref(f'p:{self.project}:r:site', f'{self.project} site')}]


@unittest.skipIf(flow_module is None, 'Home Assistant needed for flow tests')
class FlowTest(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.client_patch = patch.object(flow_module, 'CascadeClient', FakeClient)
        self.client_patch.start()
        self.addCleanup(self.client_patch.stop)
        self.session_patch = patch.object(flow_module, 'async_get_clientsession', return_value=object())
        self.session_patch.start()
        self.addCleanup(self.session_patch.stop)

    def flow(self):
        flow = flow_module.CascadeConfigFlow()
        flow.hass = Mock()
        flow.handler = 'panasonic_cascade'
        flow.flow_id = 'test-flow'
        flow.context = {'source':'user'}
        flow._async_in_progress = Mock(return_value=[])
        flow.hass.config_entries.async_entry_for_domain_unique_id.return_value = None
        return flow

    async def start(self, flow):
        return await flow.async_step_user({'url':'https://controller.invalid', 'username':'test-user', 'password':'password', 'verify_ssl':True})

    async def test_login_then_project_then_site(self):
        f = self.flow()
        self.assertEqual((await self.start(f))['step_id'], 'project')
        self.assertEqual(f._projects, {'one':'First (one)', 'two':'Second (two)'})
        self.assertEqual((await f.async_step_project({'project':'two'}))['step_id'], 'site')
        result = await f.async_step_site({'site_id':'p:two:r:site'})
        self.assertEqual(result['type'], 'create_entry')
        self.assertEqual(result['data']['project'], 'two')
        self.assertEqual(result['data']['username'], 'test-user')
        self.assertEqual(result['data']['password'], 'password')
        self.assertNotIn('session_cookie', result['data'])
        self.assertEqual(f.unique_id, 'https://controller.invalid|two|p:two:r:site')

    async def test_wrong_login_stays_on_user_form(self):
        f = self.flow()
        result = await f.async_step_user({'url':'https://controller.invalid','username':'test-user','password':'wrong','verify_ssl':True})
        self.assertEqual(result['step_id'], 'user')
        self.assertEqual(result['errors']['base'], 'invalid_auth')

    async def test_invalid_project_not_queried(self):
        f = self.flow(); await self.start(f)
        result = await f.async_step_project({'project':'unknown'})
        self.assertEqual(result['step_id'], 'project')
        self.assertEqual(result['errors']['base'], 'invalid_config')
        self.assertEqual(f._client.project, 'sys')

    async def test_invalid_site_not_saved(self):
        f = self.flow(); await self.start(f); await f.async_step_project({'project':'two'})
        result = await f.async_step_site({'site_id':'p:one:r:site'})
        self.assertEqual(result['step_id'], 'site')
        self.assertEqual(result['errors']['base'], 'invalid_config')

    async def test_duplicate_site_aborts(self):
        f = self.flow(); await self.start(f); await f.async_step_project({'project':'two'})
        f.hass.config_entries.async_entry_for_domain_unique_id.return_value = SimpleNamespace(source='user')
        with self.assertRaises(AbortFlow) as context:
            await f.async_step_site({'site_id':'p:two:r:site'})
        self.assertEqual(context.exception.reason, 'already_configured')

    async def test_two_projects_have_distinct_unique_ids(self):
        ids = []
        for project in ('one', 'two'):
            f = self.flow(); await self.start(f); await f.async_step_project({'project':project})
            await f.async_step_site({'site_id':f'p:{project}:r:site'})
            ids.append(f.unique_id)
        self.assertNotEqual(*ids)

    async def test_reauth_keeps_project_and_site_and_removes_legacy_secrets(self):
        f = self.flow()
        entry = SimpleNamespace(data={'url':'https://controller.invalid','project':'two','site_id':'p:two:r:site','session_cookie':'FAKE-OLD','attest_key':'FAKE-OLD','verify_ssl':True}, options={})
        f._get_reauth_entry = Mock(return_value=entry)
        f.async_update_reload_and_abort = Mock(return_value={'type':'abort','reason':'reauth_successful'})
        await f.async_step_reauth_confirm({'username':'test-user','password':'password'})
        updates = f.async_update_reload_and_abort.call_args.kwargs['data_updates']
        self.assertEqual(updates['username'], 'test-user')
        self.assertEqual(updates['session_cookie'], '')
        self.assertNotIn('project', updates)
        self.assertNotIn('site_id', updates)

    async def test_reconfigure_retains_entry_and_uses_correct_abort_reason(self):
        f = self.flow()
        entry = SimpleNamespace(data={'url':'https://controller.invalid','project':'two','site_id':'p:two:r:site','verify_ssl':True}, options={})
        f._get_reconfigure_entry = Mock(return_value=entry)
        f.async_update_reload_and_abort = Mock(return_value={'type':'abort'})
        initial = await f.async_step_reconfigure()
        self.assertEqual(initial['step_id'], 'reconfigure')
        await f.async_step_reconfigure({'username':'test-user','password':'password'})
        kwargs = f.async_update_reload_and_abort.call_args.kwargs
        self.assertEqual(kwargs['reason'], 'reconfigure_successful')
        self.assertNotIn('site_id', kwargs['data_updates'])

    async def test_secret_is_not_prefilled(self):
        schema = flow_module.login_schema({'username':'test-user','password':'stored-password'})
        password_key = next(k for k in schema.schema if k.schema == 'password')
        self.assertEqual(password_key.default(), '')
