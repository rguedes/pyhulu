"""
Client module

Main module for Hulu API requests
"""

import base64
import binascii
import hashlib
import json
import logging
import random
import requests

from Cryptodome.Cipher import AES
from Cryptodome.Util import Padding

from pyhulu.device import Device


class HuluClient(object):
    """
    HuluClient class

    Main class for Hulu API requests

    __init__:

    @param device_code: Three-digit string or integer (doesn't matter)
                        denoting the device you will make requests as

    @param device_key: 16-byte AES key that corresponds to the device
                       code you're using. This is used to decrypt the
                       device config response.

    @param cookies: Either a cookie jar object or a dict of cookie
                    key / value pairs. This is passed to the requests library,
                    so whatever it takes will work. Examples here:
                    http://docs.python-requests.org/en/master/user/quickstart/#cookies

    @param proxy: Proxy URL to use for requests to the Hulu API (optional)

    @param extra_playlist_params: A dict of extra playlist parameters (optional)

    @return: HuluClient object
    """

    def __init__(self, device_code, device_key, cookies, proxy=None, extra_playlist_params={}):
        self.logger = logging.getLogger(__name__)
        self.device = Device(device_code, device_key)
        self.extra_playlist_params = extra_playlist_params

        self.session = requests.Session()
        self.session.cookies = cookies
        self.session.proxies = {'http': proxy, 'https': proxy}

        self.session_key, self.server_key = self.get_session_key()

    def load_playlist(self, video_id):
        """
        load_playlist()

        Method to get a playlist containing the MPD
        and license URL for the provided video ID and return it

        @param video_id: String of the video ID to get a playlist for

        @return: Dict of decrypted playlist response
        """

        base_url = 'https://play.hulu.com/v5/playlist'
        params = {
            'device_identifier': hashlib.md5().hexdigest().upper(),
            'deejay_device_id': int(self.device.device_code),
            'version': 409160,
            'content_eab_id': video_id,
            'rv': random.randrange(1E5, 1E6),
            'kv': self.server_key,
        }
        params.update(self.extra_playlist_params)

        resp = self.session.post(url=base_url, json=params)
        ciphertext = self.__get_ciphertext(resp.text, params)

        return self.decrypt_response(self.session_key, ciphertext)

    def decrypt_response(self, key, ciphertext):
        """
        decrypt_response()

        Method to decrypt an encrypted response with provided key

        @param key: Key in bytes
        @param ciphertext: Ciphertext to decrypt in bytes

        @return: Decrypted response as a dict
        """

        aes_cbc_ctx = AES.new(key, AES.MODE_CBC, iv=b'\0'*16)

        try:
            plaintext = Padding.unpad(aes_cbc_ctx.decrypt(ciphertext), 16)
        except ValueError:
            self.logger.error('Error decrypting response')
            self.logger.error('Ciphertext:')
            self.logger.error(base64.b64encode(ciphertext).decode('utf8'))
            self.logger.error(
                'Tried decrypting with key %s',
                base64.b64encode(key).decode('utf8')
            )

            raise ValueError('Error decrypting response')

        return json.loads(plaintext.decode('utf8'))

    def get_session_key(self):
        """
        get_session_key()

        Method to do a Hulu config request and calculate
        the session key against device key and current server key

        @return: Session key in bytes
        """

        version = '409160'
        random_value = "307330725"

        base = '{device_key},{device},{version},{random_value}'.format(
            device_key=binascii.hexlify(self.device.device_key).decode('utf8'),
            device=self.device.device_code,
            version=version,
            random_value=random_value
        ).encode('utf8')

        nonce = hashlib.md5(base).hexdigest()

        url = 'https://play.hulu.com/config?app_version=4.8.0'
        payload = {
            'device': self.device.device_code,
            'format': 'json',
            'region': 'US',
            'device_model': 'AFTT',
            'android_sdk_version': '22',
            'encrypted_nonce': nonce,
            'android_version': '5.1.1',
            'rv': random_value,
            'o3n': '68fcf672a4760ae2cf1a62abf919a2d82af08f17b5d12949ab3d92282850dc056b32984ab35a933da72d8ef0be615af8',
            'device_id': 'bbb67585088b5e65',
            'version': '2',
            'device': self.device.device_code,
            'unencrypted': 'true',
        }

        resp = self.session.post(url=url, data=payload)
        ciphertext = self.__get_ciphertext(resp.text, payload)

        config_dict = self.decrypt_response(
            self.device.device_key,
            ciphertext
        )

        derived_key_array = bytearray()
        for device_byte, server_byte in zip(self.device.device_key,
                                            bytes.fromhex(config_dict['key'])):
            derived_key_array.append(device_byte ^ server_byte)

        return bytes(derived_key_array), config_dict['key_id']

    def __get_ciphertext(self, text, request):
        try:
            ciphertext = bytes.fromhex(text)
        except ValueError:
            self.logger.error('Error decoding response hex')
            self.logger.error('Request:')
            for line in json.dumps(request, indent=4).splitlines():
                self.logger.error(line)

            self.logger.error('Response:')
            for line in text.splitlines():
                self.logger.error(line)

            raise ValueError('Error decoding response hex')

        return ciphertext

    def __repr__(self):
        return '<HuluClient session_key=%s>' % base64.b64encode(
            self.session_key
        ).decode('utf8')
