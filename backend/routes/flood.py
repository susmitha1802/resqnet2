"""Stage A: bounded, read-only access to one reviewed Flood Mapper event."""
import json
import math
import os
import socket
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode, urlsplit
from urllib.request import HTTPRedirectHandler, build_opener

from flask import Blueprint, current_app, jsonify, request

flood_bp = Blueprint('flood', __name__, url_prefix='/api/flood')
EVENT = 'kerala-discovery-check'
LAYERS = {'candidate', 'buildings', 'roads', 'bridges'}
MAX_BYTES = 4 * 1024 * 1024
SUMMARY_KEYS = {
    'schema', 'event_id', 'event_date', 'aoi_bbox_epsg4326', 'candidate',
    'optical_evidence', 'exposure', 'network', 'scientific_status', 'availability', 'warnings',
}
METADATA_KEYS = {'event_id', 'event_date', 'aoi_bbox_epsg4326', 'run_ids', 'acquisition_pair'}
PROPERTY_KEYS = {
    'osm_id', 'name', 'highway', 'layer', 'exposure_class', 'evidence_category',
    'evidence_categories', 'candidate_overlap_measure', 'potentially_exposed',
    'buffer_only_potential', 'noncontradicted_potential', 'multisensor_supported_only',
}


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def _page_args():
    if set(request.args) - {'limit', 'offset', 'bbox'} or any(
        len(request.args.getlist(key)) != 1 for key in request.args
    ):
        raise ValueError('Only single limit, offset and bbox parameters are allowed.')
    limit = int(request.args.get('limit', '250'))
    offset = int(request.args.get('offset', '0'))
    if not 1 <= limit <= 500 or not 0 <= offset <= 1_000_000:
        raise ValueError('limit must be 1..500; offset must be 0..1000000.')
    args = {'limit': limit, 'offset': offset}
    if 'bbox' in request.args:
        bbox = tuple(float(v) for v in request.args['bbox'].split(','))
        if len(bbox) != 4 or not all(math.isfinite(v) for v in bbox):
            raise ValueError('bbox requires four finite EPSG:4326 coordinates.')
        w, s, e, n = bbox
        if not (-180 <= w < e <= 180 and -90 <= s < n <= 90):
            raise ValueError('Invalid bbox bounds.')
        args['bbox'] = ','.join(map(str, bbox))
    return args


def _upstream(resource, args):
    base = current_app.config.get('FLOOD_API_BASE_URL', os.getenv('FLOOD_API_BASE_URL', '')).rstrip('/')
    parsed = urlsplit(base)
    if parsed.scheme not in {'http', 'https'} or not parsed.netloc or parsed.query or parsed.fragment or parsed.username:
        return None, 503
    url = f'{base}/api/events/{EVENT}/{resource}'
    if args:
        url += '?' + urlencode(args)
    with build_opener(NoRedirect()).open(url, timeout=30) as response:
        body = response.read(MAX_BYTES + 1)
    if len(body) > MAX_BYTES:
        raise ValueError('Upstream response exceeds byte limit.')
    payload = json.loads(body)
    if not isinstance(payload, dict):
        raise ValueError('Expected an object.')
    return payload, 200


@flood_bp.get('/events/<event_id>/<resource>')
@flood_bp.get('/events/<event_id>/layers/<layer>')
def event_data(event_id, resource=None, layer=None):
    if event_id != EVENT or (layer is not None and layer not in LAYERS) or (
        layer is None and resource not in {'metadata', 'summary'}
    ):
        return jsonify(error='Event or resource is not approved for Stage A.'), 404
    try:
        if layer is None and request.args:
            raise ValueError('This resource accepts no query parameters.')
        args = _page_args() if layer else {}
    except ValueError as exc:
        return jsonify(error=str(exc)), 400
    try:
        payload, status = _upstream(f'layers/{layer}' if layer else resource, args)
        if status == 503:
            return jsonify(error='Flood Intelligence is not configured. Set FLOOD_API_BASE_URL.'), 503
        if layer:
            features = payload.get('features')
            next_offset = payload.get('next_offset')
            if (payload.get('type') != 'FeatureCollection' or not isinstance(features, list)
                    or len(features) > args['limit'] or payload.get('offset') != args['offset']
                    or payload.get('limit') != args['limit'] or payload.get('returned') != len(features)
                    or (next_offset is not None and (type(next_offset) is not int
                        or next_offset != args['offset'] + len(features) or not features))):
                raise ValueError('Invalid upstream pagination.')
            clean = []
            for feature in features:
                if feature.get('type') != 'Feature' or not isinstance(feature.get('properties'), dict):
                    raise ValueError('Invalid feature.')
                clean.append({'type': 'Feature', 'geometry': feature['geometry'], 'properties': {
                    k: v for k, v in feature['properties'].items() if k in PROPERTY_KEYS
                }})
            payload = dict(type='FeatureCollection', features=clean, layer=layer,
                           limit=args['limit'], offset=args['offset'], returned=len(clean), next_offset=next_offset)
        else:
            if payload.get('event_id') != EVENT:
                raise ValueError('Unexpected event identity.')
            approved = METADATA_KEYS if resource == 'metadata' else SUMMARY_KEYS
            payload = {k: v for k, v in payload.items() if k in approved}
        response = jsonify(payload)
        response.headers['Cache-Control'] = 'no-store'
        if layer:
            response.mimetype = 'application/geo+json'
        return response
    except HTTPError as exc:
        # Never relay upstream exception text, local paths or arbitrary responses.
        code = exc.code if exc.code in {400, 404, 409} else 502
        return jsonify(error='Reviewed event unavailable or inputs not verified.', upstream_status=exc.code), code
    except (URLError, TimeoutError, socket.timeout, OSError):
        return jsonify(error='Flood event service unavailable. Existing ResQNet workflows remain available.'), 503
    except (ValueError, KeyError, TypeError, AttributeError):
        return jsonify(error='Flood event service returned an invalid or oversized response.'), 502
