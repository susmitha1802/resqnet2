"""Opt-in check of existing event artifacts over HTTP; no application DB or processing.

Start the existing Flood Mapper event API first. --serve also provides a temporary
loopback proxy/static frontend for the browser smoke; it does not start ResQNet's DB.
"""
import argparse
import importlib.util
import json
import math
from pathlib import Path

from flask import Flask


ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location('flood', ROOT / 'backend/routes/flood.py')
flood = importlib.util.module_from_spec(spec)
spec.loader.exec_module(flood)
BASE = f'/api/flood/events/{flood.EVENT}'


def make_app(base_url):
    app = Flask(__name__, static_folder=str(ROOT / 'frontend'), static_url_path='')
    app.config['FLOOD_API_BASE_URL'] = base_url
    app.register_blueprint(flood.flood_bp)
    return app


def positions(coordinates):
    if isinstance(coordinates[0], (int, float)):
        yield coordinates
    else:
        for child in coordinates:
            yield from positions(child)


def check(app):
    client = app.test_client()

    def get(path):
        response = client.get(BASE + '/' + path)
        assert response.status_code == 200, (path, response.status_code, response.json)
        assert len(response.data) <= flood.MAX_BYTES
        return response.json

    summary, metadata = get('summary'), get('metadata')
    assert metadata['event_id'] == summary['event_id'] == flood.EVENT
    assert metadata['event_date'] == summary['event_date']
    assert metadata['acquisition_pair']['before_acquisition'] < metadata['acquisition_pair']['after_acquisition']
    assert summary['scientific_status']['confirmed_flood'] is False
    assert summary['scientific_status']['level7'] == 'NOT_READY'
    expected = {
        'buildings': summary['exposure']['buildings']['candidate_intersecting'],
        'roads': summary['network']['exposure_reconciliation']['level9_candidate_segment_count'],
        'bridges': summary['exposure']['bridges']['potentially_exposed'],
    }
    counts = {}
    for layer in sorted(flood.LAYERS):
        offset, total = 0, 0
        while offset is not None and total < 2000:
            page = get(f'layers/{layer}?limit=250&offset={offset}')
            assert page['offset'] == offset and page['returned'] == len(page['features']) <= 250
            for feature in page['features']:
                assert set(feature['properties']) <= flood.PROPERTY_KEYS
                points = list(positions(feature['geometry']['coordinates']))
                for point in points:
                    assert all(type(v) in (int, float) and math.isfinite(v) for v in point)
                    assert -180 <= point[0] <= 180 and -90 <= point[1] <= 90, 'Expected EPSG:4326 GeoJSON'
                # Full exposed OSM ways/footprints can extend outside the AOI.
                # Require intersecting bounds, not that every vertex is inside.
                west, south, east, north = summary['aoi_bbox_epsg4326']
                assert min(p[0] for p in points) <= east and max(p[0] for p in points) >= west
                assert min(p[1] for p in points) <= north and max(p[1] for p in points) >= south
            total += page['returned']
            offset = page['next_offset']
            assert offset is None or offset == total
        counts[layer] = {'loaded': total, 'complete': offset is None}
        assert total > 0
        if layer in expected:
            assert offset is None and total == expected[layer], (layer, total, expected[layer])
        empty = get(f'layers/{layer}?limit=1&offset=0&bbox=0,0,1,1')
        assert empty['returned'] == 0 and empty['next_offset'] is None
    assert client.get(BASE + '/layers/buildings?limit=501').status_code == 400
    assert client.get(BASE + '/provenance').status_code == 404
    print(json.dumps({'event_date': metadata['event_date'],
                      'observations': {key: metadata['acquisition_pair'][key] for key in ('before_acquisition', 'after_acquisition')},
                      'candidate_km2': summary['candidate']['area_km2'], 'layers': counts,
                      'scientific_status': summary['scientific_status']}, indent=2), flush=True)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--base-url', default='http://127.0.0.1:8765')
    parser.add_argument('--serve', action='store_true')
    parser.add_argument('--port', type=int, default=8766)
    args = parser.parse_args()
    app = make_app(args.base_url)
    check(app)
    if args.serve:
        app.run(host='127.0.0.1', port=args.port, debug=False, use_reloader=False)
