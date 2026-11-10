"""MDBList transport and device authorisation. No Kodi UI or player callbacks.

The application Client ID is public; user credentials must stay in the profile.
Callers own persistence and scheduling. This module never logs request URLs,
headers, response bodies or exceptions supplied by the network library.
"""
import json
import math
import re
from urllib import error, parse, request

BASE = 'https://api.mdblist.com'
CLIENT_ID = 'sTPcPQ04BEaIATYP41ZDN7T3WPdMlIYEobhlYzzy'
MAX_RESPONSE = 2 * 1024 * 1024


class MDBError(Exception):
    def __init__(self, code, retry_after=0):
        self.code = code
        self.retry_after = retry_after
        super().__init__('MDBList: ' + code)


class NoRedirect(request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def bounded_number(value, default=0, maximum=86400):
    try:
        result = float(value)
        return min(maximum, max(0, result)) if math.isfinite(result) else default
    except (ValueError, TypeError):
        return default


def playback_percentage(value):
    if isinstance(value, str) and re.fullmatch(r'[0-9]{1,3}(?:\.[0-9]{1,8})?', value):
        value = float(value)
    if type(value) in (int, float) and 0 <= value <= 100:
        return value
    return None


def send(method, path, body=None, headers=None, query=None, form=False):
    # Fixed host; never follow redirects with bearer credentials or API keys.
    if not path.startswith('/') or '?' in path or '#' in path or '://' in path:
        raise MDBError('invalid_request')
    url = BASE + path
    if query:
        url += '?' + parse.urlencode(query)
    headers = dict(headers or {})
    headers.update({'Accept': 'application/json', 'User-Agent': 'MDM-Flix'})
    data = None
    if body is not None:
        data = (parse.urlencode(body) if form else json.dumps(body, allow_nan=False)).encode('utf-8')
        headers['Content-Type'] = 'application/x-www-form-urlencoded' if form else 'application/json'
    req = request.Request(url, data=data, headers=headers, method=method)
    try:
        response = request.build_opener(NoRedirect()).open(req, timeout=10)
    except error.HTTPError as exc:
        if exc.code == 429:
            raise MDBError('rate_limited', bounded_number(exc.headers.get('Retry-After'), 60, 604800)) from None
        # OAuth returns machine-readable pending states in HTTP 400 responses.
        if exc.code == 400 and path == '/oauth/token/':
            response = exc
        else:
            code = 'unauthorised' if exc.code in (401, 403) else 'service_unavailable' if exc.code >= 500 else 'request_rejected'
            raise MDBError(code) from None
    except (OSError, error.URLError, TimeoutError):
        raise MDBError('connection_failed') from None
    try:
        with response:
            raw = response.read(MAX_RESPONSE + 1)
            if len(raw) > MAX_RESPONSE:
                raise MDBError('response_too_large')
            value = json.loads(raw)
            if path == '/watchlist/items' and isinstance(value, dict):
                value['_has_more'] = response.headers.get('X-Has-More', '').lower() in ('1', 'true')
    except (ValueError, UnicodeError):
        raise MDBError('invalid_response') from None
    except OSError:
        raise MDBError('connection_failed') from None
    if not isinstance(value, (dict, list)):
        raise MDBError('invalid_response')
    if isinstance(value, dict) and 'error' in value:
        code = value['error']
        allowed = {'authorization_pending', 'slow_down', 'access_denied', 'expired_token', 'invalid_grant', 'invalid_client'}
        raise MDBError(code if isinstance(code, str) and code in allowed else 'request_rejected')
    return value


class Client:
    def __init__(self, token='', api_key='', transport=send):
        if token and api_key:
            raise MDBError('ambiguous_credentials')
        self._token, self._key, self.transport = token, api_key, transport

    def call(self, method, path, body=None, query=None):
        if not (self._token or self._key):
            raise MDBError('not_connected')
        query = dict(query or {})
        if self._key:
            query['apikey'] = self._key
        headers = {'Authorization': 'Bearer ' + self._token} if self._token else {}
        return self.transport(method, path, body=body, headers=headers, query=query)

    def account(self):
        value = self.call('GET', '/user')
        if not isinstance(value, dict) or type(value.get('user_id')) is not int or value['user_id'] <= 0:
            raise MDBError('invalid_account')
        # Never persist API quota, account/store tokens or arbitrary server fields.
        return {'id': str(value['user_id']), 'name': str(value.get('username') or value.get('name') or 'MDBList')[:100]}

    def lists(self):
        return self.call('GET', '/lists/user', query={'sort': 'ranked', 'unified': 'true'})

    def playback(self):
        return self.call('GET', '/sync/playback')


class DeviceFlow:
    def __init__(self, client_id, transport=send):
        if not isinstance(client_id, str) or not client_id.strip() or len(client_id) > 256:
            raise MDBError('application_not_configured')
        self.client_id, self.transport = client_id.strip(), transport

    def begin(self, scope='read'):
        value = self.transport('POST', '/oauth/device-authorization/', body={'client_id': self.client_id, 'scope': scope}, form=True)
        if not isinstance(value, dict):
            raise MDBError('invalid_response')
        code, device = value.get('user_code'), value.get('device_code')
        if not all(isinstance(v, str) and 0 < len(v) <= 512 for v in (code, device)):
            raise MDBError('invalid_response')
        expires = bounded_number(value.get('expires_in'), maximum=1800)
        if not expires:
            raise MDBError('invalid_response')
        # Fixed trusted verification URL instead of opening an arbitrary server URL.
        return {'user_code': code, 'device_code': device, 'verification_uri': 'https://mdblist.com/oauth/device/',
                'expires_in': expires, 'interval': max(5, bounded_number(value.get('interval'), 5, 60))}

    def poll(self, device_code):
        return self._token({'grant_type': 'urn:ietf:params:oauth:grant-type:device_code', 'device_code': device_code})

    def refresh(self, refresh_token):
        return self._token({'grant_type': 'refresh_token', 'refresh_token': refresh_token})

    def _token(self, body):
        body = dict(body, client_id=self.client_id)
        value = self.transport('POST', '/oauth/token/', body=body, form=True)
        if not isinstance(value, dict) or str(value.get('token_type', '')).lower() != 'bearer':
            raise MDBError('invalid_response')
        if not all(isinstance(value.get(k), str) and value[k] for k in ('access_token', 'refresh_token')):
            raise MDBError('invalid_response')
        duration = bounded_number(value.get('expires_in'), maximum=2592000)
        if not duration:
            raise MDBError('invalid_response')
        return {'access_token': value['access_token'], 'refresh_token': value['refresh_token'],
                'expires_in': duration, 'scope': value.get('scope', '')}
