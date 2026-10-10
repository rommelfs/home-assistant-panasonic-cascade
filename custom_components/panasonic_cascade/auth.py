"""FIN authentication primitives, based on captured login.js and Haystack Auth."""
import base64
from dataclasses import dataclass
import hashlib
import hmac
import re
import secrets


class AuthProtocolError(ValueError):
    """Invalid or unsupported challenge (without exposing its contents)."""


def encode(data):
    if isinstance(data, str):
        data = data.encode('utf-8')
    return base64.urlsafe_b64encode(data).decode().rstrip('=')


def decode(data):
    try:
        return base64.b64decode(data + '=' * (-len(data) % 4), altchars=b'-_', validate=True)
    except (ValueError, TypeError) as err:
        raise AuthProtocolError('Invalid authentication encoding') from err


def params(text):
    result = {}
    for item in text.split(','):
        key, sep, val = item.strip().partition('=')
        if not sep or key.lower() in result or not re.fullmatch(r'[A-Za-z][A-Za-z0-9-]*', key):
            raise AuthProtocolError('Invalid authentication parameters')
        val = val.strip().strip('"')
        if not val or re.search(r'[\s\r\n]', val):
            raise AuthProtocolError('Invalid authentication parameter')
        result[key.lower()] = val
    return result


def challenge(header):
    # FIN login.js picks the first offered scheme; reject unsupported schemes.
    scheme, sep, rest = header.strip().partition(' ')
    if not scheme or '\n' in scheme or '\r' in scheme:
        raise AuthProtocolError('Missing authentication scheme')
    return scheme.lower(), params(rest) if sep and rest.strip() else {}


def hash_name(raw):
    names = {'sha-1': 'sha1', 'sha-256': 'sha256', 'sha-512': 'sha512'}
    if raw.lower() not in names:
        raise AuthProtocolError('Unsupported authentication hash')
    return names[raw.lower()]


def add_handshake(header, info):
    token = info.get('handshaketoken')
    if token:
        if not re.fullmatch(r'[A-Za-z0-9_.~+/%=-]+', token):
            raise AuthProtocolError('Invalid handshake token')
        header += ', handshakeToken=' + token
    return header


@dataclass
class Scram:
    username: str
    password: str
    algorithm: str = 'sha256'
    nonce: str = ''
    server_signature: bytes = b''

    def __post_init__(self):
        self.nonce = self.nonce or secrets.token_urlsafe(24)
        escaped = self.username.replace('=', '=3D').replace(',', '=2C')
        self.bare = f'n={escaped},r={self.nonce}'

    def first(self):
        return encode('n,,' + self.bare)

    def final(self, data):
        try:
            message = decode(data).decode('utf-8')
            fields = params(message)
            nonce = fields['r']
            iterations = int(fields['i'])
            salt = decode(fields['s'])
            if 'm' in fields or not nonce.startswith(self.nonce) or len(nonce) <= len(self.nonce):
                raise AuthProtocolError('Invalid SCRAM nonce or extension')
            if not 1 <= iterations <= 1_000_000 or not 1 <= len(salt) <= 1024:
                raise AuthProtocolError('Invalid SCRAM parameters')
            salted = hashlib.pbkdf2_hmac(self.algorithm, self.password.encode('utf-8'), salt, iterations)
            client_key = hmac.digest(salted, b'Client Key', self.algorithm)
            stored = hashlib.new(self.algorithm, client_key).digest()
            without_proof = f'c=biws,r={nonce}'
            auth_message = f'{self.bare},{message},{without_proof}'.encode('utf-8')
            signature = hmac.digest(stored, auth_message, self.algorithm)
            proof = bytes(a ^ b for a, b in zip(client_key, signature))
            server_key = hmac.digest(salted, b'Server Key', self.algorithm)
            self.server_signature = hmac.digest(server_key, auth_message, self.algorithm)
            return encode(without_proof + ',p=' + base64.b64encode(proof).decode())
        except (KeyError, UnicodeError, ValueError) as err:
            raise AuthProtocolError('Invalid SCRAM challenge') from err

    def verify(self, data):
        try:
            fields = params(decode(data).decode('utf-8'))
            if 'e' in fields or not hmac.compare_digest(decode(fields['v']), self.server_signature):
                raise AuthProtocolError('SCRAM server proof mismatch')
        except (KeyError, UnicodeError, ValueError) as err:
            raise AuthProtocolError('SCRAM server proof mismatch') from err


def hmac_header(username, password, info):
    try:
        algorithm = hash_name(info['hash'])
        salt = base64.b64encode(decode(info['salt'])).decode()
        pwd_hash = hmac.digest(password.encode('utf-8'), f'{username}:{salt}'.encode('utf-8'), algorithm)
        nonce = info['nonce']
        if not re.fullmatch(r'[A-Za-z0-9_.~+/%=-]+', nonce):
            raise AuthProtocolError('Invalid HMAC nonce')
        digest = hashlib.sha1((base64.b64encode(pwd_hash).decode() + ':' + nonce).encode()).digest()
        return add_handshake(f'HMAC digest={encode(digest)}, nonce={nonce}, username={encode(username)}', info)
    except (KeyError, ValueError) as err:
        raise AuthProtocolError('Invalid HMAC challenge') from err
