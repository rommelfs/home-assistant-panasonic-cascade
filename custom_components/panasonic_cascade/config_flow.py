"""Configure controller, credentials and site through Home Assistant."""
import voluptuous as vol

from homeassistant import config_entries
from homeassistant.helpers import selector
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .api import ApiError, AuthError, CascadeClient, normalize_url
from .const import DEFAULT_PROJECT, DOMAIN
from .model import name
from .zinc import reference


def secret_field():
    return selector.TextSelector(selector.TextSelectorConfig(type=selector.TextSelectorType.PASSWORD))


def schema(defaults=None):
    d = defaults or {}
    # Never put stored credentials into form defaults.
    return vol.Schema({
        vol.Required("url", default=d.get("url", "https://172.17.0.1")): str,
        vol.Required("project", default=d.get("project", DEFAULT_PROJECT)): str,
        vol.Optional("session_cookie", default=""): secret_field(),
        vol.Optional("bearer_token", default=""): secret_field(),
        vol.Optional("attest_key", default=""): secret_field(),
        vol.Required("verify_ssl", default=d.get("verify_ssl", True)): bool,
    })


class CascadeConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    VERSION = 1

    async def async_step_user(self, user_input=None):
        errors = {}
        if user_input is not None:
            try:
                user_input["url"] = normalize_url(user_input["url"])
                client = CascadeClient(async_get_clientsession(self.hass, verify_ssl=user_input["verify_ssl"]), user_input)
                sites = await client.sites()
                self._sites = {reference(s.get("id")): name(s) for s in sites if reference(s.get("id"))}
                if not self._sites:
                    errors["base"] = "no_sites"
                else:
                    self._pending = user_input
                    return await self.async_step_site()
            except AuthError:
                errors["base"] = "invalid_auth"
            except ApiError:
                errors["base"] = "cannot_connect"
            except ValueError:
                errors["base"] = "invalid_config"
        return self.async_show_form(step_id="user", data_schema=schema(user_input), errors=errors)

    async def async_step_site(self, user_input=None):
        if user_input is not None:
            site_id = user_input["site_id"]
            if site_id not in self._sites:
                return self.async_show_form(step_id="site", data_schema=vol.Schema({vol.Required("site_id"): vol.In(self._sites)}), errors={"base": "invalid_config"})
            unique = f'{self._pending["url"]}|{self._pending["project"]}|{site_id}'
            await self.async_set_unique_id(unique)
            self._abort_if_unique_id_configured()
            return self.async_create_entry(title=self._sites[site_id], data={**self._pending, "site_id": site_id})
        return self.async_show_form(step_id="site", data_schema=vol.Schema({vol.Required("site_id"): vol.In(self._sites)}))

    async def async_step_reauth(self, entry_data):
        return await self.async_step_reauth_confirm()

    async def async_step_reauth_confirm(self, user_input=None):
        entry = self._get_reauth_entry()
        errors = {}
        if user_input is not None:
            try:
                credentials = {key: user_input.get(key, "") for key in ("session_cookie", "bearer_token", "attest_key")}
                data = {**entry.data, **entry.options, **credentials}
                client = CascadeClient(async_get_clientsession(self.hass, verify_ssl=data.get("verify_ssl", True)), data)
                sites = await client.sites()
                if entry.data["site_id"] not in {reference(s.get("id")) for s in sites}:
                    errors["base"] = "no_sites"
                else:
                    return self.async_update_reload_and_abort(entry, data_updates=credentials)
            except AuthError:
                errors["base"] = "invalid_auth"
            except ApiError:
                errors["base"] = "cannot_connect"
            except ValueError:
                errors["base"] = "invalid_config"
        return self.async_show_form(step_id="reauth_confirm", data_schema=vol.Schema({
            vol.Optional("session_cookie", default=""): secret_field(),
            vol.Optional("bearer_token", default=""): secret_field(),
            vol.Optional("attest_key", default=""): secret_field(),
        }), errors=errors)

    @staticmethod
    def async_get_options_flow(config_entry):
        return CascadeOptionsFlow()


class CascadeOptionsFlow(config_entries.OptionsFlow):
    async def async_step_init(self, user_input=None):
        if user_input is not None:
            return self.async_create_entry(title="", data=user_input)
        d = self.config_entry.options
        return self.async_show_form(step_id="init", data_schema=vol.Schema({
            vol.Required("scan_interval", default=d.get("scan_interval", 30)): vol.All(vol.Coerce(int), vol.Range(min=15, max=300)),
            vol.Required("enable_controls", default=d.get("enable_controls", False)): bool,
            vol.Required("verify_ssl", default=d.get("verify_ssl", self.config_entry.data.get("verify_ssl", True))): bool,
        }))
