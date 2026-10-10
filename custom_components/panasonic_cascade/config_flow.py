"""Login, project selection and site selection through Home Assistant."""
import voluptuous as vol

from homeassistant import config_entries
from homeassistant.core import callback
from homeassistant.helpers import selector
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .api import ApiError, AuthError, CascadeClient, normalize_url
from .const import DOMAIN
from .model import name
from .zinc import reference


def secret_field():
    return selector.TextSelector(selector.TextSelectorConfig(type=selector.TextSelectorType.PASSWORD))


def login_schema(defaults=None, reauth=False):
    d = defaults or {}
    fields = {}
    if not reauth:
        fields[vol.Required('url', default=d.get('url', 'https://172.17.0.1'))] = str
    fields[vol.Required('username', default=d.get('username', ''))] = str
    # An empty password is permitted for FIN accounts configured without one.
    fields[vol.Optional('password', default='')] = secret_field()
    if not reauth:
        fields[vol.Required('verify_ssl', default=d.get('verify_ssl', True))] = bool
    return vol.Schema(fields)


def project_choices(rows):
    choices = {}
    for row in rows:
        project = row.get('name')
        if not isinstance(project, str):
            ident = reference(row.get('id'))
            project = ident[2:] if ident and ident.startswith('p:') else None
        if not project or project == 'sys' or row.get('routeStatus') not in (None, 'ok'):
            continue
        try:
            CascadeClient._validate_project(project)
        except ValueError:
            continue
        label = row.get('dis') or project
        choices[project] = f'{label} ({project})'
    return choices


class CascadeConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    VERSION = 1
    MINOR_VERSION = 2

    async def async_step_user(self, user_input=None):
        errors = {}
        if user_input is not None:
            try:
                user_input['url'] = normalize_url(user_input['url'])
                self._client = CascadeClient(async_get_clientsession(self.hass, verify_ssl=user_input['verify_ssl']), user_input)
                self._projects = project_choices(await self._client.projects())
                if not self._projects:
                    errors['base'] = 'no_projects'
                else:
                    self._pending = user_input
                    return await self.async_step_project()
            except AuthError:
                errors['base'] = 'invalid_auth'
            except ApiError:
                errors['base'] = 'cannot_connect'
            except ValueError:
                errors['base'] = 'invalid_config'
        return self.async_show_form(step_id='user', data_schema=login_schema(user_input), errors=errors)

    async def async_step_project(self, user_input=None):
        errors = {}
        if user_input is not None:
            project = user_input['project']
            if project not in self._projects:
                errors['base'] = 'invalid_config'
            else:
                try:
                    self._client.project = project
                    self._sites = {reference(s.get('id')): name(s) for s in await self._client.sites() if reference(s.get('id'))}
                    if not self._sites:
                        errors['base'] = 'no_sites'
                    else:
                        self._pending['project'] = project
                        return await self.async_step_site()
                except AuthError:
                    errors['base'] = 'invalid_auth'
                except ApiError:
                    errors['base'] = 'cannot_connect'
        return self.async_show_form(step_id='project', data_schema=vol.Schema({vol.Required('project'): vol.In(self._projects)}), errors=errors)

    async def async_step_site(self, user_input=None):
        errors = {}
        if user_input is not None:
            site_id = user_input['site_id']
            if site_id not in self._sites:
                errors['base'] = 'invalid_config'
            else:
                unique = f'{self._pending["url"]}|{self._pending["project"]}|{site_id}'
                await self.async_set_unique_id(unique)
                self._abort_if_unique_id_configured()
                return self.async_create_entry(title=f'{self._sites[site_id]} ({self._pending["project"]})',
                                               data={**self._pending, 'site_id': site_id})
        return self.async_show_form(step_id='site', data_schema=vol.Schema({vol.Required('site_id'): vol.In(self._sites)}), errors=errors)

    async def async_step_reauth(self, entry_data):
        return await self.async_step_reauth_confirm()

    async def async_step_reauth_confirm(self, user_input=None):
        return await self._async_credentials(self._get_reauth_entry(), user_input, 'reauth_confirm')

    async def async_step_reconfigure(self, user_input=None):
        return await self._async_credentials(self._get_reconfigure_entry(), user_input, 'reconfigure')

    async def _async_credentials(self, entry, user_input, step_id):
        errors = {}
        if user_input is not None:
            try:
                # Existing cookie-based entries can switch to password login here.
                credentials = {'username': user_input['username'], 'password': user_input.get('password', ''),
                               'session_cookie': '', 'bearer_token': '', 'attest_key': ''}
                data = {**entry.data, **entry.options, **credentials}
                client = CascadeClient(async_get_clientsession(self.hass, verify_ssl=data.get('verify_ssl', True)), data)
                if entry.data['project'] not in project_choices(await client.projects()):
                    errors['base'] = 'no_projects'
                elif entry.data['site_id'] not in {reference(s.get('id')) for s in await client.sites()}:
                    errors['base'] = 'no_sites'
                else:
                    return self.async_update_reload_and_abort(entry, data_updates=credentials,
                                                             reason='reconfigure_successful' if step_id == 'reconfigure' else 'reauth_successful')
            except AuthError:
                errors['base'] = 'invalid_auth'
            except ApiError:
                errors['base'] = 'cannot_connect'
            except ValueError:
                errors['base'] = 'invalid_config'
        return self.async_show_form(step_id=step_id, data_schema=login_schema(entry.data, reauth=True), errors=errors)

    @staticmethod
    @callback
    def async_get_options_flow(config_entry):
        return CascadeOptionsFlow()


class CascadeOptionsFlow(config_entries.OptionsFlow):
    async def async_step_init(self, user_input=None):
        if user_input is not None:
            return self.async_create_entry(title='', data=user_input)
        d = self.config_entry.options
        return self.async_show_form(step_id='init', data_schema=vol.Schema({
            vol.Required('scan_interval', default=d.get('scan_interval', 30)): vol.All(vol.Coerce(int), vol.Range(min=15, max=300)),
            vol.Required('enable_controls', default=d.get('enable_controls', False)): bool,
            vol.Required('verify_ssl', default=d.get('verify_ssl', self.config_entry.data.get('verify_ssl', True))): bool,
        }))
