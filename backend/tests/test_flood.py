"""Focused Stage A contract checks; no DB, processing or external service needed."""
import importlib.util
import io
import json
from pathlib import Path
import unittest
from unittest.mock import patch
from urllib.error import HTTPError, URLError

from flask import Flask

spec = importlib.util.spec_from_file_location('flood', Path(__file__).parents[1] / 'routes' / 'flood.py')
flood = importlib.util.module_from_spec(spec)
spec.loader.exec_module(flood)
BASE = f'/api/flood/events/{flood.EVENT}'


class FloodTests(unittest.TestCase):
    def setUp(self):
        self.app = Flask(__name__)
        self.app.config['FLOOD_API_BASE_URL'] = 'http://127.0.0.1:8765'
        self.app.register_blueprint(flood.flood_bp)
        self.client = self.app.test_client()

    def test_allowlist_and_query_limits(self):
        with patch.object(flood, '_upstream') as upstream:
            for path in ['/events/other/summary', f'/events/{flood.EVENT}/provenance',
                         f'/events/{flood.EVENT}/layers/evidence']:
                self.assertEqual(self.client.get('/api/flood' + path).status_code, 404)
            for query in ['limit=501', 'limit=0', 'offset=-1', 'offset=1000001', 'limit=x',
                          'bbox=nan,0,1,2', 'bbox=0,1,2', 'bbox=2,0,1,3', 'bbox=0,0,181,1',
                          'url=http://other', 'limit=1&limit=2']:
                self.assertEqual(self.client.get(BASE + '/layers/buildings?' + query).status_code, 400, query)
            self.assertEqual(self.client.get(BASE + '/summary?limit=1').status_code, 400)
            self.assertEqual(self.client.post(BASE + '/summary').status_code, 405)
            upstream.assert_not_called()

    def test_pagination_bbox_and_property_filter(self):
        feature = dict(type='Feature', geometry={'type': 'Point', 'coordinates': [76, 10]},
                       properties={'name': 'Bridge', 'local_path': 'private', 'evidence_categories': 'OPTICAL_UNKNOWN'})
        page = dict(type='FeatureCollection', features=[feature], returned=1, limit=1, offset=4, next_offset=5)
        with patch.object(flood, '_upstream', return_value=(page, 200)) as upstream:
            result = self.client.get(BASE + '/layers/bridges?limit=1&offset=4&bbox=75,9,77,11')
        self.assertEqual(result.status_code, 200)
        self.assertEqual(result.json['next_offset'], 5)
        self.assertNotIn('local_path', result.json['features'][0]['properties'])
        self.assertEqual(result.headers['Cache-Control'], 'no-store')
        self.assertEqual(result.mimetype, 'application/geo+json')
        upstream.assert_called_once_with('layers/bridges', {'limit': 1, 'offset': 4, 'bbox': '75.0,9.0,77.0,11.0'})
        page['next_offset'] = 4
        with patch.object(flood, '_upstream', return_value=(page, 200)):
            self.assertEqual(self.client.get(BASE + '/layers/bridges?limit=1&offset=4').status_code, 502)

    def test_summary_and_metadata_projection_and_event_identity(self):
        for resource in ['metadata', 'summary']:
            with patch.object(flood, '_upstream', return_value=({'event_id': flood.EVENT, 'event_date': '2024-07-30',
                              'paths': {'secret': 'private'}, 'scientific_status': {'confirmed_flood': False}}, 200)):
                response = self.client.get(BASE + '/' + resource)
            self.assertEqual(response.status_code, 200)
            self.assertNotIn('paths', response.json)
        with patch.object(flood, '_upstream', return_value=({'event_id': 'other'}, 200)):
            self.assertEqual(self.client.get(BASE + '/summary').status_code, 502)

    def test_unavailable_unverified_and_oversized_fail_closed(self):
        self.app.config['FLOOD_API_BASE_URL'] = ''
        self.assertEqual(self.client.get(BASE + '/summary').status_code, 503)
        for error, status in [(URLError('private host'), 503),
                              (HTTPError('url', 409, 'private path', {}, None), 409),
                              (HTTPError('url', 302, 'redirect', {}, None), 502)]:
            with patch.object(flood, '_upstream', side_effect=error):
                result = self.client.get(BASE + '/summary')
            self.assertEqual(result.status_code, status)
            self.assertNotIn('private', result.get_data(as_text=True))
        self.app.config['FLOOD_API_BASE_URL'] = 'http://127.0.0.1:8765'
        for body in [b'x' * (flood.MAX_BYTES + 1), b'not json']:
            with patch.object(flood, 'build_opener') as opener:
                opener.return_value.open.return_value.__enter__.return_value = io.BytesIO(body)
                self.assertEqual(self.client.get(BASE + '/summary').status_code, 502)

    def test_http_transport_requests_only_selected_event(self):
        body = {'event_id': flood.EVENT, 'candidate': {'pixels': 7111}}
        with patch.object(flood, 'build_opener') as opener:
            opener.return_value.open.return_value.__enter__.return_value = io.BytesIO(json.dumps(body).encode())
            self.assertEqual(self.client.get(BASE + '/summary').json, body)
            opener.return_value.open.assert_called_once_with(
                f'http://127.0.0.1:8765/api/events/{flood.EVENT}/summary', timeout=30)


if __name__ == '__main__':
    unittest.main()
