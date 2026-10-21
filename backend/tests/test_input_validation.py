"""Input validation regressions using only temporary uploads and memory SQLite."""
import io
import base64
from pathlib import Path
import sys
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from PIL import Image
from sqlalchemy.exc import SQLAlchemyError

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app import create_app
from extensions import db
from flask_jwt_extended import create_access_token
from models import ContactMessage, DisasterReport, HelpRequest, ReliefResource, User, Volunteer, WeatherAlert


class InputValidationTests(unittest.TestCase):
    def setUp(self):
        self.storage = TemporaryDirectory(prefix='resqnet-input-validation-')
        config = type('InputTestConfig', (), dict(
            TESTING=True, PROPAGATE_EXCEPTIONS=False, APP_ENV='testing', DEBUG=False,
            SEED_DEMO_DATA=False, RATELIMIT_ENABLED=False,
            SECRET_KEY='isolated-input-test-session-secret',
            JWT_SECRET_KEY='isolated-input-test-signing-secret',
            SQLALCHEMY_DATABASE_URI='sqlite:///:memory:',
            SQLALCHEMY_TRACK_MODIFICATIONS=False,
            UPLOAD_FOLDER=self.storage.name, CORS_ORIGINS=[]))
        self.app = create_app(config)
        self.context = self.app.app_context()
        self.context.push()
        self.client = self.app.test_client()
        self.ids = {}
        for role in ('reporter', 'volunteer', 'ngo', 'admin'):
            user = User(name='Fixture', email=role + '@test.invalid', phone='test',
                        password='unused', role=role)
            db.session.add(user)
            db.session.flush()
            self.ids[role] = user.user_id
            if role == 'volunteer':
                db.session.add(Volunteer(user_id=user.user_id))
        db.session.commit()

    def tearDown(self):
        db.session.remove()
        db.engine.dispose()
        self.context.pop()
        self.storage.cleanup()

    def headers(self, role):
        return {'Authorization': 'Bearer ' + create_access_token(identity=str(self.ids[role]))}

    def sos(self, **changes):
        data = dict(name='Citizen', contact='000', request_type='Rescue',
                    number_of_people='1', latitude='12.97', longitude='77.59')
        data.update(changes)
        return self.client.post('/help-request', headers=self.headers('reporter'), data=data)

    @staticmethod
    def image():
        result = io.BytesIO()
        Image.new('RGB', (2, 2), 'white').save(result, format='PNG')
        result.seek(0)
        return result

    def assert_no_uploads(self):
        self.assertEqual([p for p in Path(self.storage.name).rglob('*') if p.is_file()], [])

    def test_sos_rejects_bad_coordinates_people_and_type_without_writes(self):
        bad = [dict(latitude=value) for value in ('nan', 'inf', '-inf', 'x', '90.01', '')]
        bad += [dict(longitude=value) for value in ('181', '-181', 'nan', 'bad')]
        bad += [dict(number_of_people=value) for value in ('0', '-1', '1.2', 'abc', '99999999999999999999')]
        bad += [dict(request_type='Unknown'), dict(contact='x' * 21)]
        for fields in bad:
            with self.subTest(fields=fields):
                self.assertEqual(self.sos(**fields).status_code, 400)
                self.assertEqual(HelpRequest.query.count(), 0)
                self.assert_no_uploads()
        for path in ('/help-requests', '/map/data', '/admin/requests'):
            self.assertEqual(self.client.get(path, headers=self.headers('admin')).status_code, 200)

    def test_sos_accepts_zero_and_coordinate_boundaries(self):
        for lat, lng in (('0', '0'), ('90', '180'), ('-90', '-180')):
            with self.subTest(lat=lat, lng=lng):
                result = self.sos(latitude=lat, longitude=lng)
                self.assertEqual(result.status_code, 201)
                self.assertEqual(result.json['request']['latitude'], float(lat))
                self.assertEqual(result.json['request']['longitude'], float(lng))
        self.assertEqual(HelpRequest.query.count(), 3)

    def test_invalid_sos_image_is_rejected_not_silently_dropped(self):
        result = self.sos(image=(io.BytesIO(b'not an image'), 'proof.png'))
        self.assertEqual(result.status_code, 400)
        self.assertEqual(HelpRequest.query.count(), 0)
        self.assert_no_uploads()

    def test_private_sos_image_and_duplicate_recovery(self):
        response = self.sos(image=(self.image(), 'evidence.png'))
        self.assertEqual(response.status_code, 201)
        row = response.json['request']
        self.assertNotIn('image_path', row)
        image_url = row['image_url']
        self.assertEqual(self.client.get(image_url).status_code, 401)
        self.assertEqual(self.client.get(image_url, headers=self.headers('ngo')).status_code, 403)
        for role in ('reporter', 'admin'):
            result = self.client.get(image_url, headers=self.headers(role))
            self.assertEqual(result.status_code, 200)
            self.assertEqual(result.mimetype, 'image/png')
            self.assertEqual(result.headers['Cache-Control'], 'private, no-store')
            result.close()
        req_id = row['request_id']
        for status, duplicate in [('Duplicate', True), ('Pending', False)]:
            result = self.client.put('/help-request/status', json={'request_id': req_id, 'status': status},
                                     headers=self.headers('admin'))
            self.assertEqual(result.status_code, 200)
            self.assertEqual(result.json['request']['is_duplicate'], duplicate)
            db.session.expire_all()
            self.assertEqual(db.session.get(HelpRequest, req_id).is_duplicate, duplicate)
        for url in ('/help-requests', '/map/data', '/admin/requests'):
            self.assertEqual(self.client.get(url, headers=self.headers('admin')).status_code, 200)

    def test_private_report_image_and_single_file_contract(self):
        payload = dict(disaster_type='Flood', description='Observation', latitude='12', longitude='77')
        multi = {**payload, 'images': [(self.image(), 'one.png'), (self.image(), 'two.png')]}
        self.assertEqual(self.client.post('/report-disaster', data=multi,
                         headers=self.headers('reporter')).status_code, 400)
        self.assert_no_uploads()
        created = self.client.post('/report-disaster', data={**payload, 'images': (self.image(), 'one.png')},
                                   headers=self.headers('reporter'))
        self.assertEqual(created.status_code, 201)
        url = created.json['report']['image_url']
        self.assertNotIn('image_path', created.json['report'])
        self.assertEqual(self.client.get(url).status_code, 401)
        self.assertEqual(self.client.get(url, headers=self.headers('volunteer')).status_code, 403)
        for role in ('reporter', 'admin'):
            viewed = self.client.get(url, headers=self.headers(role))
            self.assertEqual(viewed.status_code, 200)
            viewed.close()
        self.assertEqual(self.client.get('/admin/reports', headers=self.headers('admin')).json['reports'][0]['image_url'], url)
        report = db.session.get(DisasterReport, created.json['report']['report_id'])
        report.image_path = str(Path(self.storage.name) / 'outside.png')
        (Path(self.storage.name) / 'outside.png').write_bytes(b'not private report storage')
        db.session.commit()
        self.assertEqual(self.client.get(url, headers=self.headers('admin')).status_code, 404)

    def test_ngo_resource_edit_and_admin_overview_are_role_scoped(self):
        created = self.client.post('/ngo/resources', json={'name': 'Water', 'quantity': 4, 'location': 'Store'},
                                   headers=self.headers('ngo'))
        self.assertEqual(created.status_code, 201)
        resource_id = created.json['resource']['resource_id']
        url = f'/ngo/resources/{resource_id}'
        other = User(name='Other NGO', email='other-ngo@test.invalid', phone='test', password='unused', role='ngo')
        db.session.add(other)
        db.session.commit()
        other_headers = {'Authorization': 'Bearer ' + create_access_token(identity=str(other.user_id))}
        self.assertEqual(self.client.put(url, json={'quantity': 10}, headers=other_headers).status_code, 403)
        for value in (0, -1, 1.2, '2', True, None):
            self.assertEqual(self.client.put(url, json={'quantity': value},
                             headers=self.headers('ngo')).status_code, 400)
        self.assertEqual(self.client.put(url, json={'quantity': 6, 'location': 'New store'},
                         headers=self.headers('reporter')).status_code, 403)
        updated = self.client.put(url, json={'quantity': 6, 'location': 'New store'}, headers=self.headers('ngo'))
        self.assertEqual(updated.status_code, 200)
        self.assertEqual(updated.json['resource']['quantity'], 6)
        self.assertEqual(self.client.get('/admin/resources', headers=self.headers('reporter')).status_code, 403)
        overview = self.client.get('/admin/resources', headers=self.headers('admin'))
        self.assertEqual(overview.status_code, 200)
        self.assertEqual(overview.json['resources'][0]['location'], 'New store')
        self.assertEqual(overview.json['total'], 1)
        for page in ('limit=0', 'limit=501', 'offset=-1', 'offset=abc'):
            self.assertEqual(self.client.get('/admin/resources?' + page,
                             headers=self.headers('admin')).status_code, 400)
        resource = db.session.get(ReliefResource, resource_id)
        resource.allocated_to = self.sos().json['request']['request_id']
        db.session.commit()
        self.assertEqual(self.client.put(url, json={'quantity': 9}, headers=self.headers('ngo')).status_code, 409)
        self.assertEqual(db.session.get(ReliefResource, resource_id).quantity, 6)

    def test_public_stats_use_aggregate_status_counts(self):
        self.sos()
        result = self.client.get('/public/stats')
        self.assertEqual(result.status_code, 200)
        self.assertEqual(result.json['stats']['active_requests'], 1)
        self.assertEqual(result.json['stats']['completed'], 0)

    def test_four_role_assistance_flow_with_rejection_and_approval(self):
        created = self.sos()
        self.assertEqual(created.status_code, 201)
        req_id = created.json['request']['request_id']
        self.assertEqual(self.client.put('/volunteer/accept-task', json={'request_id': req_id},
                         headers=self.headers('reporter')).status_code, 403)
        self.assertEqual(self.client.put('/volunteer/accept-task', json={'request_id': req_id},
                         headers=self.headers('volunteer')).status_code, 200)
        self.assertEqual(self.client.put('/volunteer/accept-task', json={'request_id': req_id},
                         headers=self.headers('volunteer')).status_code, 409)
        task_id = self.client.get('/volunteer/tasks', headers=self.headers('volunteer')).json['tasks'][0]['task_id']
        resource = self.client.post('/ngo/resources', json={'name': 'Water', 'quantity': 4},
                                    headers=self.headers('ngo')).json['resource']['resource_id']
        self.assertEqual(self.client.put('/ngo/allocate', json={'resource_id': resource, 'request_id': req_id},
                         headers=self.headers('ngo')).status_code, 200)
        for status in ('En Route', 'On Site'):
            self.assertEqual(self.client.put('/help-request/status', json={'request_id': req_id, 'status': status},
                             headers=self.headers('volunteer')).status_code, 200)
        def upload():
            return self.client.post(f'/volunteer/upload-proof/{task_id}',
                                    data={'proof_image': (self.image(), 'proof.png'), 'notes': 'Test assistance'},
                                    headers=self.headers('volunteer'))
        self.assertEqual(upload().status_code, 200)
        self.assertEqual(self.client.get(f'/help-request/{req_id}',
                         headers=self.headers('reporter')).json['request']['progress_status'], 'Awaiting admin verification')
        self.assertEqual(self.client.put(f'/admin/verify-task/{task_id}', json={'action': 'Reject'},
                         headers=self.headers('ngo')).status_code, 403)
        self.assertEqual(self.client.put(f'/admin/verify-task/{task_id}', json={'action': 'Reject'},
                         headers=self.headers('admin')).status_code, 200)
        self.assertEqual(upload().status_code, 200)
        self.assertEqual(self.client.put(f'/admin/verify-task/{task_id}', json={'action': 'Approve'},
                         headers=self.headers('admin')).status_code, 200)
        self.assertEqual(self.client.put(f'/admin/verify-task/{task_id}', json={'action': 'Approve'},
                         headers=self.headers('admin')).status_code, 409)
        self.assertEqual(self.client.get(f'/help-request/{req_id}',
                         headers=self.headers('reporter')).json['request']['status'], 'Completed')
        self.assertEqual(self.client.get('/public/stats').json['stats']['completed'], 1)

    def test_corrupt_proof_image_does_not_interrupt_active_task(self):
        req_id = self.sos().json['request']['request_id']
        volunteer = self.headers('volunteer')
        self.assertEqual(self.client.put('/volunteer/accept-task', json={'request_id': req_id},
                         headers=volunteer).status_code, 200)
        task_id = self.client.get('/volunteer/tasks', headers=volunteer).json['tasks'][0]['task_id']
        for status in ('En Route', 'On Site'):
            self.assertEqual(self.client.put('/help-request/status', json={'request_id': req_id,
                             'status': status}, headers=volunteer).status_code, 200)
        corrupt = base64.b64decode('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAusB9Wl6JXcAAAAASUVORK5CYII=')
        response = self.client.post(f'/volunteer/upload-proof/{task_id}',
                                    data={'proof_image': (io.BytesIO(corrupt), 'bad.png'), 'notes': 'Fixture'},
                                    headers=volunteer)
        self.assertEqual(response.status_code, 400)
        self.assertEqual(self.client.get('/volunteer/tasks', headers=volunteer).json['tasks'][0]['status'], 'On Site')

    def test_corrupt_sos_image_does_not_create_request_or_file(self):
        corrupt = base64.b64decode('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAusB9Wl6JXcAAAAASUVORK5CYII=')
        response = self.sos(image=(io.BytesIO(corrupt), 'bad.png'))
        self.assertEqual(response.status_code, 400)
        self.assertEqual(HelpRequest.query.count(), 0)
        self.assert_no_uploads()

    def test_geocoder_validates_and_caches_user_triggered_lookup(self):
        for url in ('/geocode?kind=search&q=x', '/geocode?kind=reverse&lat=nan&lon=1',
                    '/geocode?kind=reverse&lat=1&lon=181', '/geocode?kind=other'):
            self.assertEqual(self.client.get(url).status_code, 400)
        fake_response = io.BytesIO(b'[{' + b'"lat":"12","lon":"77","display_name":"Test Place"' + b'}]')
        with patch('routes.geocode.urlopen', return_value=fake_response) as upstream:
            first = self.client.get('/geocode?kind=search&q=Kochi')
            second = self.client.get('/geocode?kind=search&q=Kochi')
        self.assertEqual(first.status_code, 200)
        self.assertEqual(first.json, second.json)
        self.assertEqual(upstream.call_count, 1)

    def test_two_nearby_households_require_admin_duplicate_recovery(self):
        first = self.sos()
        self.assertEqual(first.status_code, 201)
        other = User(name='Other household', email='household@test.invalid', phone='test',
                     password='unused', role='reporter')
        db.session.add(other)
        db.session.commit()
        second_headers = {'Authorization': 'Bearer ' + create_access_token(identity=str(other.user_id))}
        second = self.client.post('/help-request', data=dict(name='Other', contact='000',
            request_type='Rescue', number_of_people='1', latitude='12.97', longitude='77.59'),
            headers=second_headers)
        self.assertEqual(second.status_code, 201)
        duplicate = second.json['request']
        self.assertEqual((duplicate['status'], duplicate['is_duplicate']), ('Duplicate', True))
        self.assertEqual(self.client.put('/help-request/status', json={
            'request_id': duplicate['request_id'], 'status': 'Pending'},
            headers=second_headers).status_code, 403)
        restored = self.client.put('/help-request/status', json={
            'request_id': duplicate['request_id'], 'status': 'Pending'},
            headers=self.headers('admin'))
        self.assertEqual(restored.status_code, 200)
        self.assertEqual((restored.json['request']['status'], restored.json['request']['is_duplicate']),
                         ('Pending', False))
        self.assertEqual(self.client.get('/public/stats').json['stats']['active_requests'], 2)


    def test_sos_upload_and_db_failure_cleans_only_new_file(self):
        existing = Path(self.storage.name) / 'requests' / 'keep.png'
        existing.parent.mkdir(parents=True)
        existing.write_bytes(b'existing')
        with patch.object(db.session, 'commit', side_effect=SQLAlchemyError('synthetic failure')):
            result = self.sos(image=(self.image(), 'new.png'))
        self.assertEqual(result.status_code, 503)
        self.assertEqual(HelpRequest.query.count(), 0)
        self.assertEqual([p for p in existing.parent.iterdir() if p.is_file()], [existing])
        self.assertEqual(existing.read_bytes(), b'existing')
        self.assertEqual(self.sos(image=(self.image(), 'new.png')).status_code, 201)

    def test_volunteer_gps_rejects_nonfinite_out_of_range_and_wrong_json_types(self):
        endpoint = '/volunteer/update-location'
        headers = self.headers('volunteer')
        for bad in (None, True, '12.5', 'nan', [], {}, 91, -91, float('nan'), float('inf')):
            with self.subTest(value=repr(bad)):
                result = self.client.put(endpoint, headers=headers, json={'latitude': bad, 'longitude': 0})
                self.assertEqual(result.status_code, 400)
        for bad in (181, -181, '77.0', False, float('-inf')):
            with self.subTest(value=repr(bad)):
                self.assertEqual(self.client.put(endpoint, headers=headers,
                                 json={'latitude': 0, 'longitude': bad}).status_code, 400)
        self.assertEqual(self.client.put(endpoint, headers=headers, json=[1, 2]).status_code, 400)
        vol = Volunteer.query.filter_by(user_id=self.ids['volunteer']).one()
        self.assertIsNone(vol.last_location_lat)
        self.assertEqual(self.client.put(endpoint, headers=headers,
                         json={'latitude': 0, 'longitude': 0}).status_code, 200)
        self.assertEqual(float(vol.last_location_lat), 0)

    def test_ngo_resource_rejects_bad_quantities_and_json_types(self):
        headers = self.headers('ngo')
        base = {'name': 'Water', 'quantity': 1}
        for quantity in (None, False, True, 0, -1, 1.5, '2', [], {}, 2_147_483_648):
            with self.subTest(value=repr(quantity)):
                result = self.client.post('/ngo/resources', headers=headers,
                                          json={**base, 'quantity': quantity})
                self.assertEqual(result.status_code, 400)
                self.assertEqual(ReliefResource.query.count(), 0)
        for data in ([], {'name': None, 'quantity': 1}, {'name': 'A', 'quantity': 1, 'unit': []}):
            self.assertEqual(self.client.post('/ngo/resources', headers=headers, json=data).status_code, 400)
        good = self.client.post('/ngo/resources', headers=headers, json=base)
        self.assertEqual(good.status_code, 201)
        self.assertEqual(good.json['resource']['quantity'], 1)

    def test_auth_and_contact_reject_wrong_json_shapes_without_writes(self):
        registration = {'name': 'Test', 'email': 'new@test.invalid', 'phone': '000',
                        'password': 'password', 'role': 'volunteer'}
        for data in ([], {**registration, 'role': []}, {**registration, 'availability': 'on_task'},
                     {**registration, 'skills': {}}, {**registration, 'email': None}):
            self.assertEqual(self.client.post('/register', json=data).status_code, 400)
        self.assertIsNone(User.query.filter_by(email='new@test.invalid').first())
        for data in ([], {'email': [], 'password': 'x'}, {'email': 'x', 'password': None}):
            self.assertEqual(self.client.post('/login', json=data).status_code, 400)
        for data in ([], {'name': {}, 'email': 'x', 'subject': 'x', 'message': 'x'},
                     {'name': 'x', 'email': 'x', 'subject': 'x' * 201, 'message': 'x'}):
            self.assertEqual(self.client.post('/contact', json=data).status_code, 400)
        self.assertEqual(ContactMessage.query.count(), 0)
        self.assertEqual(self.client.post('/register', json=registration).status_code, 201)
        self.assertEqual(self.client.post('/contact', json={'name': 'x', 'email': 'x',
                         'subject': 'x', 'message': 'x'}).status_code, 201)

    def test_report_coordinates_and_status_enums_do_not_break_feeds(self):
        headers = self.headers('reporter')
        base = {'disaster_type': 'Flood', 'description': 'Observation',
                'latitude': '0', 'longitude': '0'}
        for fields in ({'latitude': 'nan'}, {'latitude': '91'}, {'longitude': 'inf'},
                       {'longitude': '-181'}, {'latitude': 'bad'}):
            result = self.client.post('/report-disaster', headers=headers, data=base | fields)
            self.assertEqual(result.status_code, 400)
        self.assertEqual(DisasterReport.query.count(), 0)
        self.assertEqual(self.client.post('/report-disaster', headers=headers, data=base).status_code, 201)
        self.assertEqual(self.client.put('/volunteer/update-status', headers=self.headers('volunteer'),
                         json={'status': []}).status_code, 400)
        self.assertEqual(self.client.put('/help-request/status', headers=self.headers('admin'),
                         json={'status': [], 'request_id': 1}).status_code, 400)
        for path in ('/reports', '/map/data', '/admin/reports'):
            self.assertEqual(self.client.get(path, headers=self.headers('admin')).status_code, 200)

    def test_admin_alert_rejects_bad_json_enum_and_coordinates(self):
        base = {'alert_type': 'Flood', 'severity': 'Watch', 'description': 'Manual advisory',
                'affected_lat': 0, 'affected_lng': 0, 'affected_radius_km': 50}
        bad = ([], {**base, 'alert_type': []}, {**base, 'severity': {}},
               {**base, 'affected_lat': '0'}, {**base, 'affected_lng': float('nan')},
               {**base, 'affected_lat': 91}, {**base, 'affected_radius_km': True})
        for data in bad:
            with self.subTest(data=repr(data)):
                self.assertEqual(self.client.post('/alerts', headers=self.headers('admin'),
                                 json=data).status_code, 400)
                self.assertEqual(WeatherAlert.query.count(), 0)
        self.assertEqual(self.client.post('/alerts', headers=self.headers('admin'),
                         json=base).status_code, 201)
        self.assertEqual(self.client.get('/alerts').status_code, 200)


class GeocoderLimitTests(unittest.TestCase):
    def test_shared_geocoder_limit_is_not_per_client(self):
        with TemporaryDirectory(prefix='resqnet-geocode-limit-') as storage:
            config = type('GeocoderLimitConfig', (), dict(
                TESTING=True, APP_ENV='testing', DEBUG=False, SEED_DEMO_DATA=False,
                SECRET_KEY='isolated-geocode-session', JWT_SECRET_KEY='isolated-geocode-jwt',
                SQLALCHEMY_DATABASE_URI='sqlite:///:memory:', SQLALCHEMY_TRACK_MODIFICATIONS=False,
                UPLOAD_FOLDER=storage, CORS_ORIGINS=[], RATELIMIT_ENABLED=True,
                RATELIMIT_STORAGE_URI='memory://'))
            app = create_app(config)
            with patch('routes.geocode.urlopen', side_effect=lambda *_args, **_kwargs: io.BytesIO(b'[]')) as upstream:
                first = app.test_client().get('/geocode?kind=search&q=Kochi')
                second = app.test_client().get('/geocode?kind=search&q=Delhi')
            self.assertEqual(first.status_code, 200)
            self.assertEqual(second.status_code, 429)
            self.assertEqual(upstream.call_count, 1)


if __name__ == '__main__':
    unittest.main()
