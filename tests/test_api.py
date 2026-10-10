"""Mock transport tests; no controller traffic or real credentials required."""
import importlib
import sys
import types
import unittest
from unittest.mock import patch

from test_protocol import PACKAGE, model, zinc

# Keep protocol/transport tests runnable with the Python standard library.
# This fallback only mocks aiohttp's exception/timeout types, never its transport.
try:
    import aiohttp
except ImportError:
    aiohttp = types.ModuleType("aiohttp")
    aiohttp.ClientError = type("ClientError", (Exception,), {})
    aiohttp.ClientTimeout = lambda **kw: kw
    sys.modules["aiohttp"] = aiohttp
api = importlib.import_module(PACKAGE + ".api")


class Response:
    def __init__(self, status=200, text='ver:"3.0"\nval\nT\n'):
        self.status, self.body = status, text

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        pass

    async def text(self):
        return self.body


class Session:
    def __init__(self, responses=None):
        self.calls = []
        self.responses = responses or [Response()]

    def post(self, url, **kwargs):
        self.calls.append((url, kwargs))
        return self.responses.pop(0)


def client(session, **overrides):
    config = {"url": "https://controller.invalid", "project": "pSmartEdge", "session_cookie": "skyarc-auth-80=FAKE", "attest_key": "FAKE"}
    return api.CascadeClient(session, {**config, **overrides})


def number_point():
    return {"id": zinc.Ref("p:demo:r:a"), "writable": zinc.MARKER, "kind": "Number", "unit": "°C", "actions": "pointSetDef($self,$val)", "bufferModelId": "_equip:buffer_point:zone1WaterTemperatureHotSetpoint"}


class ApiTest(unittest.IsolatedAsyncioTestCase):
    async def test_eval_envelope_headers_and_no_redirects(self):
        s = Session()
        await client(s).read('point and siteRef==@p:demo:r:a')
        url, kwargs = s.calls[0]
        self.assertEqual(url, 'https://controller.invalid/api/pSmartEdge/eval')
        expr = zinc.parse_grids(kwargs['data'].decode())[0][0]['expr']
        self.assertEqual(expr, 'parseFilter("point and siteRef==@p:demo:r:a").readAll()')
        self.assertFalse(kwargs['allow_redirects'])
        self.assertTrue(kwargs['ssl'])
        self.assertEqual(kwargs['headers']['SkyArc-Attest-Key'], 'FAKE')

    async def test_expiry_redirect_html_and_error_grid(self):
        for response in (Response(401), Response(403), Response(302), Response(200, '<html>Login</html>')):
            with self.assertRaises(api.AuthError):
                await client(Session([response])).sites()
        with self.assertRaises(api.ApiError):
            await client(Session([Response(200, 'ver:"3.0" err\nempty\n')])).sites()

    async def test_out_of_range_or_invalid_writes_never_transmit(self):
        s = Session()
        c = client(s)
        for v in (19, 56, float('nan'), float('inf'), True, '40;deleteAll()'):
            with self.assertRaises(ValueError):
                await c.set_default(number_point(), v)
        self.assertEqual(s.calls, [])

    async def test_temperature_default_has_unit_and_no_override(self):
        s = Session()
        await client(s).set_default(number_point(), 40)
        expression = zinc.parse_grids(s.calls[0][1]['data'].decode())[0][0]['expr']
        self.assertEqual(expression, 'pointSetDef(@p:demo:r:a, 40°C)')

    async def test_bool_enum_and_bad_reference_writes(self):
        s = Session([Response(), Response()]); c = client(s)
        r = {"id": zinc.Ref("p:demo:r:a"), "writable": zinc.MARKER, "kind": "Bool", "actions": "pointSetDef($self,$val)", "siteModelId": "_site:sgReady"}
        await c.set_default(r, False)
        self.assertIn('false', zinc.parse_grids(s.calls[0][1]['data'].decode())[0][0]['expr'])
        r.update(kind='Str', siteModelId='_site:quietModeRequest', enum='Off,Level 1')
        await c.set_default(r, 'Level 1')
        with self.assertRaises(ValueError):
            await c.set_default(r, 'Level 1"); deleteAll()')
        r['id'] = zinc.Ref('bad)')
        with self.assertRaises(ValueError):
            await c.set_default(r, 'Off')
        self.assertEqual(len(s.calls), 2)

    async def test_power_summary_preserves_kw(self):
        s = Session([Response(200, 'ver:"3.0"\nid,point,kind,curVal\n@p:demo:r:t,M,"Number",31°C\n'), Response(200, 'ver:"3.0"\nval\n13.628kW\n'), Response(200, 'ver:"3.0"\nval\n4.111kW\n')])
        rows = await client(s).snapshot('p:demo:r:site')
        self.assertEqual(rows['summary:generatedPower']['curVal'], zinc.Number(13.628, 'kW'))
        self.assertEqual(rows['summary:consumedPower']['unit'], 'kW')
        self.assertEqual(len(s.calls), 3)

    async def test_config_and_secret_validation(self):
        for overrides in ({'url':'http://controller.invalid'}, {'url':'https://user:pass@controller.invalid'}, {'project':'../other'}, {'session_cookie':'token\r\nInjected: header'}, {'session_cookie':'', 'bearer_token':''}):
            with self.assertRaises(ValueError):
                client(Session(), **overrides)
        self.assertEqual(api.normalize_url('https://controller.invalid/pod/app#/overview'), 'https://controller.invalid')


    async def test_zone_read_is_scoped_and_validated(self):
        s = Session([Response(200, 'ver:"3.0"\nid,curVal\n@p:demo:r:zone,"On/On"\n')])
        row = await client(s).read_point('p:demo:r:zone', 'p:demo:r:site')
        self.assertEqual(row['curVal'], 'On/On')
        expression = zinc.parse_grids(s.calls[0][1]['data'].decode())[0][0]['expr']
        self.assertEqual(expression, 'parseFilter("id==@p:demo:r:zone and siteRef==@p:demo:r:site").readAll()')
        for text in ('ver:"3.0"\nid\n', 'ver:"3.0"\nid\n@p:demo:r:wrong\n'):
            with self.assertRaises(api.ApiError):
                await client(Session([Response(200,text)])).read_point('p:demo:r:zone', 'p:demo:r:site')
        with self.assertRaises(ValueError):
            await client(Session()).read_point('bad);deleteAll()', 'p:demo:r:site')
