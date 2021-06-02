from time import time

from slyguy import settings, userdata
from slyguy.log import log
from slyguy.session import Session
from slyguy.exceptions import Error

from .constants import *
from .language import _

class APIError(Error):
    pass

class API(object):
    def new_session(self):
        self.logged_in = False
        self._auth_header = {}

        self._session = Session(HEADERS)
        self._set_authentication()

    def _set_authentication(self):
        access_token = userdata.get('access_token')
        if not access_token:
            return

        self._auth_header = {'authorization': 'Bearer {}'.format(access_token)}
        self.logged_in = True

    def _oauth_token(self, data, _raise=True):
        token_data = self._session.post('https://auth.streamotion.com.au/oauth/token', json=data, headers={'User-Agent': 'okhttp/3.10.0'}, error_msg=_.TOKEN_ERROR).json()

        if 'error' in token_data:
            error = _.REFRESH_TOKEN_ERROR if data.get('grant_type') == 'refresh_token' else _.LOGIN_ERROR
            if _raise:
                raise APIError(_(error, msg=token_data.get('error_description')))
            else:
                return False, token_data

        userdata.set('access_token', token_data['access_token'])
        userdata.set('expires', int(time() + token_data['expires_in'] - 15))

        if 'refresh_token' in token_data:
            userdata.set('refresh_token', token_data['refresh_token'])

        self._set_authentication()
        return True, token_data

    def refresh_token(self):
        self._refresh_token()

    def _refresh_token(self, force=False):
        if not force and userdata.get('expires', 0) > time() or not self.logged_in:
            return

        log.debug('Refreshing token')

        payload = {
            'client_id': CLIENT_ID,
            'refresh_token': userdata.get('refresh_token'),
            'grant_type': 'refresh_token',
            'scope': 'openid offline_access drm:{} email'.format('high' if settings.getBool('wv_secure', False) else 'low'),
        }

        self._oauth_token(payload)

    def device_code(self):
        payload = {
            'client_id': CLIENT_ID,
            'audience' : 'streamotion.com.au',
            'scope': 'openid offline_access drm:{} email'.format('high' if settings.getBool('wv_secure', False) else 'low'),
        }

        return self._session.post('https://auth.streamotion.com.au/oauth/device/code', data=payload).json()

    def device_login(self, device_code):
        payload = {
            'client_id': CLIENT_ID,
            'device_code' : device_code,
            'scope': 'openid offline_access drm:{}'.format('high' if settings.getBool('wv_secure', False) else 'low'),
            'grant_type': 'urn:ietf:params:oauth:grant-type:device_code',
        }

        result, token_data = self._oauth_token(payload, _raise=False)
        if result:
            self._refresh_token(force=True)
            return True

        if token_data.get('error') != 'authorization_pending':
            raise APIError(_(_.LOGIN_ERROR, msg=token_data.get('error_description')))
        else:
            return False

    def login(self, username, password):
        payload = {
            'client_id': CLIENT_ID,
            'username': username,
            'password': password,
            'audience': 'streamotion.com.au',
            'scope': 'openid offline_access drm:{} email'.format('high' if settings.getBool('wv_secure', False) else 'low'),
            'grant_type': 'http://auth0.com/oauth/grant-type/password-realm',
            'realm': 'prod-martian-database',
        }

        self._oauth_token(payload)
        self._refresh_token(force=True)

    def search(self, query):
        params = {
            'q': query,
        }

        return self._session.get('https://api.binge.com.au/v1/search/types/landing', params=params).json()

    #landing has heros and panels
    def landing(self, name, params=None):
        _params = {
            'evaluate': 4,
        }

        _params.update(params or {})

        return self._session.get('https://api.binge.com.au/v1/content/types/landing/names/{}'.format(name), params=_params).json()

    def panel(self, link=None, panel_id=None):
        self._refresh_token()
        params = {'profile': userdata.get('profile_id')}

        if panel_id:
            url = 'https://api.binge.com.au/v1/private/panels/{panel_id}' if self.logged_in else 'https://api.binge.com.au/v1/panels/{panel_id}'
            link = url.format(panel_id=panel_id)

        return self._session.get(link, params=params, headers=self._auth_header).json()

    def profiles(self):
        self._refresh_token()

        try:
            return self._session.get('https://profileapi.streamotion.com.au/user/profile/type/ares', headers=self._auth_header).json()
        except:
            return []

    def add_profile(self, name, avatar_id):
        self._refresh_token()

        payload = {
            'name': name,
            'avatar_id': avatar_id,
            'onboarding_status': 'welcomeScreen',
        }

        return self._session.post('https://profileapi.streamotion.com.au/user/profile/type/ares', json=payload, headers=self._auth_header).json()

    def delete_profile(self, profile):
        self._refresh_token()

        return self._session.delete('https://profileapi.streamotion.com.au/user/profile/type/ares/{profile_id}'.format(profile_id=profile['id']), headers=self._auth_header)

    def profile_config(self):
        return self._session.get('https://resources.streamotion.com.au/production/binge/profile/profile-config.json').json()

    def license_request(self, data):
        self._refresh_token()

        resp = self._session.post(LICENSE_URL, data=data, headers=self._auth_header)
        if not resp.ok:
            raise APIError('Failed to get license')

        return resp.content

    def stream(self, asset_id):
        self._refresh_token()

        payload = {
            'assetId': asset_id,
            'canPlayHevc': settings.getBool('hevc', False),
            'contentType':  'application/xml+dash',
            'drm': True,
            'forceSdQuality': False,
            'playerName': 'exoPlayerTV',
            'udid': UDID,
        }

        data = self._session.post('https://play.binge.com.au/api/v1/play', json=payload, headers=self._auth_header).json()
        if ('status' in data and data['status'] != 200) or 'errors' in data:
            msg = data.get('detail') or data.get('errors', [{}])[0].get('detail')
            raise APIError(_(_.ASSET_ERROR, msg=msg))

        return data['data'][0]

    def logout(self):
        userdata.delete('access_token')
        userdata.delete('refresh_token')
        userdata.delete('expires')
        self.new_session()