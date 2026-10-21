"""Readiness and private GPS tests use a fresh memory database per case."""
from pathlib import Path
import sys
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from sqlalchemy.exc import SQLAlchemyError

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app import create_app
from extensions import db
from flask_jwt_extended import create_access_token
from models import HelpRequest, ReliefTask, User, Volunteer


class AvailabilityLocationTests(unittest.TestCase):
    def setUp(self):
        self.storage = TemporaryDirectory(prefix='resqnet-readiness-')
        config = type('ReadinessConfig', (), dict(
            TESTING=True, PROPAGATE_EXCEPTIONS=False, APP_ENV='testing', DEBUG=False,
            SEED_DEMO_DATA=False, RATELIMIT_ENABLED=False,
            SECRET_KEY='isolated-readiness-session-secret',
            JWT_SECRET_KEY='isolated-readiness-signing-secret',
            SQLALCHEMY_DATABASE_URI='sqlite:///:memory:',
            SQLALCHEMY_TRACK_MODIFICATIONS=False, UPLOAD_FOLDER=self.storage.name,
            CORS_ORIGINS=[]))
        self.app = create_app(config)
        self.context = self.app.app_context()
        self.context.push()
        self.client = self.app.test_client()
        self.admin = User(name='Admin', email='admin@test.invalid', phone='test',
                          password='unused', role='admin')
        db.session.add(self.admin)
        db.session.commit()

    def tearDown(self):
        db.session.remove()
        db.engine.dispose()
        self.context.pop()
        self.storage.cleanup()

    def headers(self, user):
        return {'Authorization': 'Bearer ' + create_access_token(identity=str(user.user_id))}

    def register(self, role, suffix, **fields):
        data = {'name': suffix, 'email': suffix + '@test.invalid', 'phone': '000',
                'password': 'test-password', 'role': role, **fields}
        result = self.client.post('/register', json=data)
        self.assertEqual(result.status_code, 201, result.json)
        return User.query.filter_by(email=data['email']).one(), result.json

    def test_volunteer_registration_and_profile_use_operational_status(self):
        offline, response = self.register('volunteer', 'offline', availability='unavailable')
        ready, _ = self.register('volunteer', 'ready', availability='available')
        self.assertEqual(offline.availability, 'unavailable')
        self.assertEqual(offline.volunteer.availability_status, 'unavailable')
        self.assertEqual(ready.volunteer.availability_status, 'available')
        self.assertEqual(response['user']['volunteer']['availability_status'], 'unavailable')
        for path in ('/profile',):
            result = self.client.get(path, headers=self.headers(offline))
            self.assertEqual(result.json['user']['availability'], 'unavailable')
        logged_in = self.client.post('/login', json={'email': offline.email, 'password': 'test-password'})
        self.assertEqual(logged_in.json['user']['volunteer']['availability_status'], 'unavailable')
        self.assertEqual(self.client.get('/preparedness/summary', headers=self.headers(self.admin))
                         .json['volunteers'], {'ready': 1, 'busy': 0, 'offline': 1})

    def test_volunteer_status_is_owned_and_active_assignment_blocks_clearing(self):
        volunteer, _ = self.register('volunteer', 'worker', availability='unavailable')
        other, _ = self.register('volunteer', 'other', availability='available')
        reporter, _ = self.register('reporter', 'citizen')
        endpoint = '/volunteer/update-status'
        self.assertEqual(self.client.put(endpoint, headers=self.headers(reporter),
                         json={'status': 'available'}).status_code, 403)
        self.assertEqual(self.client.put(endpoint, headers=self.headers(self.admin),
                         json={'status': 'available'}).status_code, 403)
        self.assertEqual(self.client.put(endpoint, headers=self.headers(volunteer),
                         json={'status': 'on_task'}).status_code, 409)
        changed = self.client.put(endpoint, headers=self.headers(volunteer), json={'status': 'available'})
        self.assertEqual(changed.status_code, 200)
        self.assertEqual(volunteer.volunteer.availability_status, 'available')
        self.assertEqual(volunteer.availability, 'available')
        self.assertEqual(other.volunteer.availability_status, 'available')
        request = HelpRequest(user_id=reporter.user_id, name='Citizen', contact='000',
                              request_type='Rescue', latitude=1, longitude=1)
        db.session.add(request)
        db.session.flush()
        db.session.commit()
        accepted = self.client.put('/volunteer/accept-task', headers=self.headers(volunteer),
                                   json={'request_id': request.request_id})
        self.assertEqual(accepted.status_code, 200)
        self.assertEqual(volunteer.availability, 'unavailable')
        self.assertEqual(volunteer.volunteer.availability_status, 'on_task')
        self.assertEqual(self.client.put(endpoint, headers=self.headers(volunteer),
                         json={'status': 'unavailable'}).status_code, 409)
        self.assertEqual(self.client.put(endpoint, headers=self.headers(volunteer),
                         json={'status': 'available'}).status_code, 409)
        self.assertEqual(self.client.get('/profile', headers=self.headers(volunteer))
                         .json['user']['volunteer']['availability_status'], 'on_task')

    def test_failed_acceptance_keeps_both_availability_records_and_sos_unchanged(self):
        volunteer, _ = self.register('volunteer', 'worker')
        reporter, _ = self.register('reporter', 'citizen')
        request = HelpRequest(user_id=reporter.user_id, name='Citizen', contact='000',
                              request_type='Rescue', latitude=1, longitude=1)
        db.session.add(request)
        db.session.commit()
        with patch.object(db.session, 'commit', side_effect=SQLAlchemyError('synthetic failure')):
            response = self.client.put('/volunteer/accept-task', headers=self.headers(volunteer),
                                       json={'request_id': request.request_id})
        self.assertEqual(response.status_code, 503)
        db.session.expire_all()
        self.assertEqual(request.status, 'Pending')
        self.assertEqual(volunteer.availability, 'available')
        self.assertEqual(volunteer.volunteer.availability_status, 'available')
        self.assertEqual(ReliefTask.query.count(), 0)

    def test_private_gps_survives_fresh_client_and_is_account_scoped(self):
        owner, _ = self.register('volunteer', 'gps-owner')
        other, _ = self.register('volunteer', 'gps-other')
        ngo, _ = self.register('ngo', 'org', org_name='Named organization')
        endpoint = '/volunteer/update-location'
        for outsider in (ngo, self.admin):
            self.assertEqual(self.client.put(endpoint, headers=self.headers(outsider),
                             json={'latitude': 0, 'longitude': 0}).status_code, 403)
        saved = self.client.put(endpoint, headers=self.headers(owner),
                                json={'latitude': 0, 'longitude': -180})
        self.assertEqual(saved.status_code, 200)
        self.assertEqual(saved.json['volunteer']['last_location_lat'], 0)
        fresh_client = self.app.test_client()
        profile = fresh_client.get('/profile', headers=self.headers(owner)).json['user']
        self.assertEqual((profile['volunteer']['last_location_lat'],
                          profile['volunteer']['last_location_lng']), (0, -180))
        self.assertEqual(self.client.put(endpoint, headers=self.headers(other),
                         json={'latitude': 10, 'longitude': 20}).status_code, 200)
        self.assertEqual(self.client.get('/profile', headers=self.headers(owner)).json['user']
                         ['volunteer']['last_location_lng'], -180)
        self.assertEqual(fresh_client.get('/profile', headers=self.headers(other))
                         .json['user']['volunteer']['last_location_lat'], 10)
        self.assertNotIn('volunteer', fresh_client.get('/profile', headers=self.headers(ngo)).json['user'])
        self.assertEqual(self.client.get('/profile').status_code, 401)

    def test_ngo_readiness_persists_and_admin_summary_tracks_it(self):
        ngo, _ = self.register('ngo', 'relief', org_name='Relief organization')
        other, _ = self.register('ngo', 'other-org', org_name='Other organization')
        volunteer, _ = self.register('volunteer', 'worker')
        reporter, _ = self.register('reporter', 'citizen')
        endpoint = '/ngo/readiness'
        for outsider in (volunteer, reporter, self.admin):
            self.assertEqual(self.client.put(endpoint, headers=self.headers(outsider),
                             json={'status': 'unavailable'}).status_code, 403)
        for data in ([], {'status': 'on_task'}, {'status': None}, {'status': []}):
            self.assertEqual(self.client.put(endpoint, headers=self.headers(ngo), json=data).status_code, 400)
        result = self.client.put(endpoint, headers=self.headers(ngo), json={'status': 'unavailable'})
        self.assertEqual(result.status_code, 200)
        self.assertEqual(result.json['availability'], 'unavailable')
        self.assertEqual(self.app.test_client().get('/profile', headers=self.headers(ngo))
                         .json['user']['availability'], 'unavailable')
        self.assertEqual(other.availability, 'available')
        summary = self.client.get('/preparedness/summary', headers=self.headers(self.admin)).json
        self.assertEqual(summary['ngos'], {'ready': 1, 'offline': 1})
        with patch.object(db.session, 'commit', side_effect=SQLAlchemyError('synthetic failure')):
            self.assertEqual(self.client.put(endpoint, headers=self.headers(ngo),
                             json={'status': 'available'}).status_code, 503)
        db.session.expire_all()
        self.assertEqual(self.client.get('/profile', headers=self.headers(ngo))
                         .json['user']['availability'], 'unavailable')
        self.assertEqual(self.client.put(endpoint, headers=self.headers(ngo),
                         json={'status': 'available'}).status_code, 200)
        self.assertEqual(self.client.get('/preparedness/summary', headers=self.headers(self.admin))
                         .json['ngos'], {'ready': 2, 'offline': 0})

    def test_public_ngo_map_excludes_unknown_or_invalid_positions(self):
        self.register('ngo', 'no-coordinates', org_name='City relief')
        self.register('ngo', 'invalid-coordinates', org_name='91,181')
        result = self.client.get('/ngo/locations')
        self.assertEqual(result.status_code, 200)
        self.assertEqual(result.json['locations'], [])
        self.assertEqual(result.json['total'], 0)
        self.register('ngo', 'coordinates', org_name='0,0')
        result = self.client.get('/ngo/locations').json
        self.assertEqual(result['total'], 1)
        self.assertEqual((result['locations'][0]['latitude'], result['locations'][0]['longitude']), (0, 0))


if __name__ == '__main__':
    unittest.main()
