"""Server-only private Supabase Storage objects; never expose keys or object URLs."""
import json
import re
from urllib.error import HTTPError, URLError
from urllib.parse import quote
from urllib.request import Request, build_opener, HTTPRedirectHandler
from uuid import uuid4

from flask import current_app


class StorageUnavailable(OSError):
    """A storage operation failed without disclosing provider credentials."""


class _NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, request, fp, code, msg, headers, newurl):
        return None  # Never forward the secret key to a redirect destination.


_REF = re.compile(r'^supabase://(requests|reports|task_proofs)/([a-f0-9]{32})\.(png|jpg)$')


def is_cloud():
    return current_app.config.get('STORAGE_BACKEND', 'local') == 'supabase'


def valid_key(reference, folder):
    match = _REF.fullmatch(reference or '') if isinstance(reference, str) else None
    if not match or match.group(1) != folder:
        return None
    return reference.removeprefix('supabase://')


def _open(request):
    return build_opener(_NoRedirect()).open(request, timeout=15)


def _request(method, path, body=None, content_type=None):
    config = current_app.config
    base = config['SUPABASE_URL'].rstrip('/')
    url = f'{base}/storage/v1/object/{path}'
    headers = {'apikey': config['SUPABASE_SECRET_KEY'], 'User-Agent': 'ResQNet-server/1.0'}
    if content_type:
        headers['Content-Type'] = content_type
    request = Request(url, data=body, headers=headers, method=method)
    try:
        with _open(request) as response:
            # Request limit is 10 MB; cap reads even if the provider misbehaves.
            data = response.read(10 * 1024 * 1024 + 1)
        if len(data) > 10 * 1024 * 1024:
            raise StorageUnavailable('Private image exceeds the supported size.')
        return data
    except HTTPError as exc:
        if method == 'GET' and exc.code == 404:
            return None
        raise StorageUnavailable('Private image storage is unavailable.') from None
    except (URLError, TimeoutError, OSError):
        raise StorageUnavailable('Private image storage is unavailable.') from None


def check_private_bucket():
    """Refuse production writes if the configured bucket is public or unknown."""
    config = current_app.config
    bucket = quote(config['SUPABASE_STORAGE_BUCKET'], safe='')
    request = Request(config['SUPABASE_URL'].rstrip('/') + '/storage/v1/bucket/' + bucket,
                      headers={'apikey': config['SUPABASE_SECRET_KEY'],
                               'User-Agent': 'ResQNet-server/1.0'}, method='GET')
    try:
        with _open(request) as response:
            details = json.loads(response.read(8192))
    except (HTTPError, URLError, TimeoutError, OSError, ValueError):
        raise StorageUnavailable('Private storage bucket could not be verified.') from None
    if (not isinstance(details, dict) or details.get('id') != config['SUPABASE_STORAGE_BUCKET']
            or details.get('public') is not False):
        raise StorageUnavailable('Private storage bucket is not private.')


def upload_image(image_bytes, folder, image_format):
    if folder not in {'requests', 'reports', 'task_proofs'} or image_format not in {'PNG', 'JPEG'}:
        raise ValueError('Invalid private image destination.')
    extension = 'png' if image_format == 'PNG' else 'jpg'
    key = f'{folder}/{uuid4().hex}.{extension}'
    bucket = quote(current_app.config['SUPABASE_STORAGE_BUCKET'], safe='')
    try:
        _request('POST', bucket + '/' + quote(key, safe='/'), image_bytes,
                 'image/png' if extension == 'png' else 'image/jpeg')
    except StorageUnavailable:
        # An upstream timeout can arrive after the object was accepted.
        try:
            delete_image('supabase://' + key, folder)
        except StorageUnavailable:
            current_app.logger.error('Ambiguous private upload could not be cleaned up.')
        raise
    return 'supabase://' + key


def download_image(reference, folder):
    key = valid_key(reference, folder)
    if not key:
        return None
    bucket = quote(current_app.config['SUPABASE_STORAGE_BUCKET'], safe='')
    return _request('GET', 'authenticated/' + bucket + '/' + quote(key, safe='/'))


def delete_image(reference, folder):
    key = valid_key(reference, folder)
    if not key:
        return False
    # Supabase Storage's remove API accepts a list of object paths in this bucket.
    bucket = quote(current_app.config['SUPABASE_STORAGE_BUCKET'], safe='')
    _request('DELETE', bucket, json.dumps({'prefixes': [key]}).encode(), 'application/json')
    return True
