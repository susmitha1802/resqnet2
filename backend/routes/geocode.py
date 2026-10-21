"""User-triggered, bounded OSM address lookups; no autocomplete."""
import hashlib
import json
import os

from urllib.error import URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen
from redis.exceptions import RedisError
from flask import Blueprint, current_app, jsonify, request

from input_validation import coordinates


geocode_bp = Blueprint('geocode', __name__)


@geocode_bp.route('/geocode', methods=['GET'])
def geocode():
    kind = request.args.get('kind')
    if kind == 'search':
        query = request.args.get('q', '').strip()
        if not 3 <= len(query) <= 120:
            return jsonify(success=False, message='Search text must be 3–120 characters'), 400
        params = {'q': query, 'format': 'jsonv2', 'limit': 5, 'countrycodes': 'in'}
        path = 'search'
    elif kind == 'reverse':
        try:
            lat, lng = coordinates(request.args.get('lat'), request.args.get('lon'), form=True)
        except ValueError:
            return jsonify(success=False, message='Invalid coordinates'), 400
        params = {'lat': lat, 'lon': lng, 'format': 'jsonv2'}
        path = 'reverse'
    else:
        return jsonify(success=False, message='Invalid lookup kind'), 400

    # The shared production Redis store keeps cache entries across workers.
    key = 'resqnet:geocode:' + hashlib.sha256(json.dumps([path, params], sort_keys=True).encode()).hexdigest()
    redis_url = current_app.config.get('RATELIMIT_STORAGE_URI', '')
    cache = None
    if redis_url.startswith(('redis://', 'rediss://')):
        from redis import Redis
        cache = Redis.from_url(redis_url, socket_connect_timeout=2, socket_timeout=2)
    try:
        raw = cache.get(key) if cache else current_app.extensions.setdefault('geocode_cache', {}).get(key)
        if raw:
            return jsonify(success=True, result=json.loads(raw))
        base = os.environ.get('NOMINATIM_BASE_URL', 'https://nominatim.openstreetmap.org').rstrip('/')
        upstream = Request(f'{base}/{path}?{urlencode(params)}', headers={
            'User-Agent': os.environ.get('NOMINATIM_USER_AGENT', 'ResQNet/1.0 (community assistance map)'),
            'Accept': 'application/json'
        })
        with urlopen(upstream, timeout=5) as response:
            raw_result = response.read(131073)
            if len(raw_result) > 131072:
                raise ValueError('Geocoder response too large')
            result = json.loads(raw_result)
        if path == 'search' and not isinstance(result, list):
            raise ValueError('Unexpected geocoder response')
        if path == 'reverse' and not isinstance(result, dict):
            raise ValueError('Unexpected geocoder response')
        encoded = json.dumps(result)
        if cache:
            cache.setex(key, 86400, encoded)
        else:
            local_cache = current_app.extensions.setdefault('geocode_cache', {})
            if len(local_cache) >= 512:
                local_cache.clear()
            local_cache[key] = encoded
        return jsonify(success=True, result=result)
    except (URLError, ValueError, OSError, json.JSONDecodeError, RedisError):
        return jsonify(success=False, message='Address lookup unavailable'), 503
