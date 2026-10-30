"""RFC vector and isolated local-server tests, never using controller credentials."""
import asyncio
import base64
import hashlib
import hmac
import importlib
import unittest
from unittest.mock import patch

from test_protocol import PACKAGE, zinc
from test_api import api

auth = importlib.import_module(PACKAGE + '.auth')
try:
    from aiohttp import web, ClientSession, DummyCookieJar
except ImportError:
    web = None


class CryptoTest(unittest.TestCase):
    def test_scram_sha256_rfc7677_vector(self):
        # RFC 7677 section 3 public test vector (user/pencil are example values).
        s = auth.Scram('user', 'pencil', nonce='rOprNGfwEbeRWgbNEkqO')
        server = 'r=rOprNGfwEbeRWgbNEkqO%hvYDpWUa2RaTCAfuxFIlj)hNlF$k0,s=W22ZaJ0SNY7soEsUEjb6gQ==,i=4096'
        final = auth.decode(s.final(auth.encode(server))).decode()
        self.assertEqual(final.rsplit(',p=', 1)[1], 'dHzbZapWIk4jUhN+Ute9ytag9zjfMHgsqmmiz7AndVQ=')
        s.verify(auth.encode('v=6rriTRBi23WpRR/wtup+mMhUZUn/dB5nLTJRsjl95G4='))
        with self.assertRaises(auth.AuthProtocolError):
            s.verify(auth.encode('v=' + base64.b64encode(b'wrong').decode()))

    def test_nonce_bounds_hash_and_parameter_validation(self):
        s = auth.Scram('user', 'password', nonce='known')
        for message in ('r=other,s=c2FsdA==,i=4096', 'r=known,s=c2FsdA==,i=4096', 'r=knownserver,s=c2FsdA==,i=1000001', 'r=knownserver,s=c2FsdA==,i=0', 'r=knownserver,s=c2FsdA==,i=bad'):
            with self.assertRaises(auth.AuthProtocolError):
                s.final(auth.encode(message))
        with self.assertRaises(auth.AuthProtocolError):
            auth.hash_name('md5')
        with self.assertRaises(auth.AuthProtocolError):
            auth.params('a=one,a=two')
        self.assertEqual(auth.decode(auth.encode('Müller')).decode(), 'Müller')
        self.assertIn('n=a=2Cb=3Dc', auth.decode(auth.Scram('a,b=c', '').first()).decode())

    def test_hmac_digest_matches_independent_calculation(self):
        info = {'hash':'SHA-256', 'salt':auth.encode(b'salt'), 'nonce':'server-nonce'}
        header = auth.hmac_header('user', 'password', info)
        digest = hmac.new(b'password', b'user:c2FsdA==', hashlib.sha256).digest()
        expected = hashlib.sha1(base64.b64encode(digest) + b':server-nonce').digest()
        _, fields = auth.challenge(header)
        self.assertEqual(auth.decode(fields['digest']), expected)


@unittest.skipIf(web is None, 'aiohttp needed for real local transport tests')
class LocalLoginTest(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.handshakes = 0
        self.current_session = ''
        self.proof_verified = False
        self.expire_once = False
        self.always_expire = False
        self.force_403 = False
        self.expired_status = 401
        self.login_status = None
        self.attest_status = None
        self.bad_proof = False
        self.mechanism = 'SCRAM'
        self.password = 'test-password'
        self.bare = ''
        self.server_first = ''
        self.expected_signature = b''
        self.post_paths = []
        app = web.Application()
        app.router.add_get('/user/auth', self.authenticate)
        app.router.add_get('/finStackAuth', self.attest)
        app.router.add_post('/api/{project}/eval', self.evaluate)
        self.runner = web.AppRunner(app)
        await self.runner.setup()
        site = web.TCPSite(self.runner, '127.0.0.1', 0)
        await site.start()
        port = site._server.sockets[0].getsockname()[1]
        # Production URL validation still requires HTTPS. HTTP here is strictly
        # a loopback-only fixture with invented usernames/passwords/cookies.
        self.local_url = f'http://127.0.0.1:{port}'
        self.session = ClientSession(cookie_jar=DummyCookieJar())

    async def asyncTearDown(self):
        await self.session.close()
        await self.runner.cleanup()

    def client(self, username='test-user', password='test-password'):
        c = api.CascadeClient(self.session, {'url':'https://fixture.invalid', 'username':username, 'password':password})
        c.url = self.local_url
        return c

    def success(self, info=None):
        self.current_session = f'session-{self.handshakes}'
        response = web.Response(text='ok', headers={'Authentication-Info':info} if info else {})
        response.set_cookie('skyarc-auth-test', self.current_session, httponly=True)
        return response

    async def authenticate(self, request):
        if self.login_status is not None:
            return web.Response(status=self.login_status)
        scheme, info = auth.challenge(request.headers.get('Authorization', ''))
        if scheme == 'hello':
            self.handshakes += 1
            self.assertEqual(auth.decode(info['username']), b'test-user')
            if self.mechanism == 'PASSWORDLESS':
                return self.success()
            if self.mechanism == 'HMAC':
                return web.Response(status=401, headers={'WWW-Authenticate':f'HMAC hash=SHA-256, salt={auth.encode(b"salt")}, nonce=server-nonce'})
            if self.mechanism == 'X-PLAINTEXT':
                return web.Response(status=401, headers={'WWW-Authenticate':'X-PLAINTEXT'})
            return web.Response(status=401, headers={'WWW-Authenticate':'SCRAM hash=SHA-256, handshakeToken=first'})
        if scheme == 'x-plaintext':
            self.assertEqual(auth.decode(info['password']).decode(), self.password)
            return self.success()
        if scheme == 'hmac':
            self.assertEqual(request.headers['Authorization'], auth.hmac_header('test-user', self.password, {'hash':'SHA-256','salt':auth.encode(b'salt'),'nonce':'server-nonce'}))
            return self.success()
        decoded = auth.decode(info['data']).decode()
        if decoded.startswith('n,,'):
            self.assertEqual(info['handshaketoken'], 'first')
            self.bare = decoded[3:]
            nonce = auth.params(self.bare)['r']
            self.server_first = f'r={nonce}server,s={base64.b64encode(b"test-salt").decode()},i=4096'
            return web.Response(status=401, headers={'WWW-Authenticate':f'SCRAM hash=SHA-256, handshakeToken=second, data={auth.encode(self.server_first)}'})
        self.assertEqual(info['handshaketoken'], 'second')
        final, proof = decoded.rsplit(',p=', 1)
        salted = hashlib.pbkdf2_hmac('sha256', self.password.encode(), b'test-salt', 4096)
        key = hmac.new(salted, b'Client Key', hashlib.sha256).digest()
        message = f'{self.bare},{self.server_first},{final}'.encode()
        signature = hmac.new(hashlib.sha256(key).digest(), message, hashlib.sha256).digest()
        expected_proof = bytes(a ^ b for a,b in zip(key, signature))
        if not hmac.compare_digest(base64.b64decode(proof), expected_proof):
            return web.Response(status=403)
        self.proof_verified = True
        server_key = hmac.new(salted, b'Server Key', hashlib.sha256).digest()
        server_signature = hmac.new(server_key, message, hashlib.sha256).digest()
        if self.bad_proof:
            server_signature = b'wrong'
        return self.success('data=' + auth.encode('v=' + base64.b64encode(server_signature).decode()))

    async def attest(self, request):
        if self.attest_status is not None:
            return web.Response(status=self.attest_status)
        if request.cookies.get('skyarc-auth-test') != self.current_session:
            return web.Response(status=self.expired_status)
        return web.Response(text='ver:"3.0"\nusername\n"test-user"\n', headers={'fin-stack-auth':'attest-' + self.current_session})

    async def evaluate(self, request):
        self.post_paths.append(request.path)
        if self.expire_once or self.always_expire:
            self.expire_once = False
            return web.Response(status=401)
        if self.force_403:
            return web.Response(status=403)
        if request.cookies.get('skyarc-auth-test') != self.current_session or request.headers.get('SkyArc-Attest-Key') != 'attest-' + self.current_session:
            return web.Response(status=self.expired_status)
        expression = zinc.parse_grids(await request.text())[0][0]['expr']
        if expression == 'secureEval(projs())':
            text = 'ver:"3.0"\nid,name hidden,dis,routeStatus\n@p:one,"one","First","ok"\n@p:two,"two","Second","ok"\n'
        else:
            self.assertEqual(request.match_info['project'], 'two')
            text = 'ver:"3.0"\nid,dis\n@p:two:r:site,"Second site"\n'
        return web.Response(text=text, content_type='text/zinc')

    async def test_full_login_projects_and_selected_project(self):
        c = self.client()
        projects = await c.projects()
        self.assertEqual([r['name'] for r in projects], ['one', 'two'])
        self.assertTrue(self.proof_verified)
        self.assertNotIn('Cookie', c.headers)  # Managed privately in client memory.
        c.project = 'two'
        sites = await c.sites()
        self.assertEqual(zinc.reference(sites[0]['id']), 'p:two:r:site')
        self.assertEqual(self.post_paths, ['/api/sys/eval', '/api/two/eval'])
        self.assertEqual(self.handshakes, 1)

    async def test_session_expiry_renews_once_and_preserves_project(self):
        c = self.client(); await c.projects(); c.project = 'two'
        self.expire_once = True
        await c.sites()
        self.assertEqual(self.handshakes, 2)
        self.assertEqual(c.project, 'two')

    async def test_controller_reboot_invalidates_cookie_with_403_and_recovers_automatically(self):
        c=self.client(); await c.projects(); c.project='two'
        old_cookie=c.cookies['skyarc-auth-test'].value
        self.current_session='controller-rebooted'; self.expired_status=403
        await c.sites()
        self.assertEqual(self.handshakes,2)
        self.assertNotEqual(c.cookies['skyarc-auth-test'].value,old_cookie)
        self.assertEqual(c.project,'two')
        self.assertEqual(c.headers['SkyArc-Attest-Key'],'attest-'+self.current_session)

    async def test_boot_login_and_attestation_unavailable_retry_on_later_poll(self):
        c=self.client(); await c.projects(); c.project='two'
        for login_status,attest_status in [(503,None),(200,None),(None,503),(None,401)]:
            self.current_session='rebooted';self.login_status=login_status;self.attest_status=attest_status
            with self.assertRaises(api.ApiError):await c.sites()
            self.assertFalse(c.authenticated)
            self.assertFalse(c.cookies)
            self.login_status=self.attest_status=None
            self.assertTrue(await c.sites())
            self.assertEqual(c.project,'two')

    async def test_ha_restart_reuses_persisted_credentials_in_a_new_client(self):
        config={'url':'https://fixture.invalid','username':'test-user','password':'test-password','project':'two'}
        for _ in range(2):
            c=api.CascadeClient(self.session,config);c.url=self.local_url
            await c.sites()
        self.assertEqual(self.handshakes,2)

    async def test_transport_outage_discards_stale_session_and_next_poll_logs_in(self):
        from unittest.mock import patch
        c=self.client();await c.projects();c.project='two'
        request=c._request
        async def disconnected(method,path,**kwargs):
            if method=='POST':raise api.ApiError('Controller connection failed')
            return await request(method,path,**kwargs)
        with patch.object(c,'_request',side_effect=disconnected):
            with self.assertRaises(api.ApiError):await c.sites()
        self.assertFalse(c.authenticated)
        self.assertFalse(c.cookies)
        self.assertNotIn('SkyArc-Attest-Key',c.headers)
        await c.sites()
        self.assertEqual(self.handshakes,2)

    async def test_concurrent_expired_requests_share_renewal_after_reboot(self):
        c=self.client();await c.projects()
        self.current_session='rebooted';self.expired_status=403
        await asyncio.gather(c.projects(),c.projects())
        self.assertEqual(self.handshakes,2)

    async def test_wrong_password_rejected(self):
        c = self.client(password='wrong')
        with self.assertRaises(api.AuthError):
            await c.projects()
        self.assertFalse(c.authenticated)
        self.assertFalse(c.cookies)

    async def test_permission_denied_does_not_repeat_login(self):
        c = self.client(); await c.projects(); self.force_403 = True
        with self.assertRaises(api.ApiError):
            await c.projects()
        self.assertEqual(self.handshakes, 1)

    async def test_invalid_server_proof_rejected_and_session_cleared(self):
        c = self.client(); self.bad_proof = True
        with self.assertRaises(api.AuthError):
            await c.projects()
        self.assertFalse(c.authenticated)
        self.assertFalse(c.cookies)

    async def test_legacy_hmac(self):
        self.mechanism = 'HMAC'
        await self.client().projects()
        self.assertEqual(self.handshakes, 1)

    async def test_server_requested_plaintext(self):
        self.mechanism = 'X-PLAINTEXT'
        await self.client().projects()
        self.assertEqual(self.handshakes, 1)

    async def test_passwordless_hello_success(self):
        self.mechanism = 'PASSWORDLESS'
        await self.client(password='').projects()
        self.assertEqual(self.handshakes, 1)

    async def test_repeated_expiry_has_bounded_retry(self):
        c = self.client(); await c.projects(); self.always_expire = True
        with self.assertRaises(api.ApiError):
            await c.projects()
        self.assertEqual(self.handshakes, 2)
        self.assertFalse(c.authenticated)
        self.always_expire=False
        await c.projects()
        self.assertEqual(self.handshakes,3)

    async def test_concurrent_requests_share_one_login(self):
        c = self.client()
        results = await asyncio.gather(c.projects(), c.projects())
        self.assertEqual(self.handshakes, 1)
        self.assertEqual(len(results), 2)
