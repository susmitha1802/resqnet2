"""The demo fixture must stay isolated, truthful and reversible."""
from pathlib import Path
import sys
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app import create_app
from extensions import db
from models import (DisasterReport, HelpRequest, PreparednessPing, ReliefResource,
                    ReliefTask, User, Volunteer, WeatherAlert)
from seed_demo import EMAILS, TAG, cleanup_demo_data, seed_demo_data, set_demo_password
from sos_lifecycle import proof_directory


class DemoSeedTests(unittest.TestCase):
    def setUp(self):
        self.storage = TemporaryDirectory(prefix='resqnet-demo-tests-')
        config = type('DemoFixture', (), dict(
            TESTING=True, APP_ENV='testing', DEBUG=False, DEMO_MODE=True,
            SEED_DEMO_DATA=False, SECRET_KEY='demo-fixture-session',
            JWT_SECRET_KEY='demo-fixture-jwt-secret-over-32-characters',
            SQLALCHEMY_DATABASE_URI='sqlite:///:memory:',
            SQLALCHEMY_TRACK_MODIFICATIONS=False, UPLOAD_FOLDER=self.storage.name,
            RATELIMIT_ENABLED=False, CORS_ORIGINS=[]))
        self.app = create_app(config)
        self.context = self.app.app_context()
        self.context.push()
        self.client = self.app.test_client()

    def tearDown(self):
        db.session.remove()
        db.engine.dispose()
        self.context.pop()
        self.storage.cleanup()

    def _login(self, key):
        result = self.client.post('/login', json={'email': EMAILS[key], 'password': 'fixture-only-long-password'})
        self.assertEqual(result.status_code, 200, key)
        return {'Authorization': 'Bearer ' + result.json['token']}

    def test_seed_idempotence_four_roles_and_safe_counts(self):
        self.assertTrue(seed_demo_data('fixture-only-long-password'))
        self.assertFalse(seed_demo_data('fixture-only-long-password'))
        self.assertEqual((User.query.count(), Volunteer.query.count(), DisasterReport.query.count(),
                          HelpRequest.query.count(), ReliefTask.query.count(), ReliefResource.query.count(),
                          WeatherAlert.query.count(), PreparednessPing.query.count()),
                         (8, 3, 3, 5, 2, 4, 1, 3))
        self.assertEqual(self.client.get('/public/stats').json['stats'], dict(
            total_requests=5, active_requests=3, active_volunteers=1,
            total_volunteers=3, completed=1))
        self.assertTrue(self.client.get('/public/stats').json['demo_mode'])

        citizen = self._login('reporter1')
        volunteer = self._login('vol2')
        ngo = self._login('ngo1')
        admin = self._login('admin')
        self.assertEqual(len(self.client.get('/help-requests', headers=citizen).json['requests']), 2)
        self.assertEqual(len(self.client.get('/volunteer/tasks', headers=volunteer).json['tasks']), 1)
        self.assertEqual(len(self.client.get('/ngo/resources', headers=ngo).json['resources']), 2)
        self.assertEqual(self.client.get('/admin/dashboard', headers=admin).json['stats']['total_requests'], 5)
        self.assertEqual(self.client.get('/admin/dashboard', headers=citizen).status_code, 403)
        self.assertEqual(self.client.get('/volunteer/tasks', headers=ngo).status_code, 403)
        self.assertEqual(self.client.get('/ngo/resources', headers=volunteer).status_code, 403)

        map_data = self.client.get('/map/data', headers=admin).json
        self.assertEqual((len(map_data['requests']), len(map_data['reports'])), (3, 3))
        self.assertTrue(all(row['is_demo'] for row in map_data['requests'] + map_data['reports']))
        self.assertEqual(self.client.get('/map/data').json['visibility'], 'aggregate-only')
        self.assertEqual(len(self.client.get('/alerts').json['alerts']), 1)
        self.assertTrue(self.client.get('/alerts').json['alerts'][0]['is_demo'])
        self.assertTrue(all(row.description.startswith(TAG) for row in DisasterReport.query.all()))
        self.assertTrue(all(row.prediction_confidence is None for row in DisasterReport.query.all()))
        self.assertTrue(all(row.image_path is None for row in DisasterReport.query.all()))
        completed = ReliefTask.query.filter_by(status='Completed').one()
        proof_url = f'/volunteer/tasks/{completed.task_id}/proof'
        proof_response = self.client.get(proof_url, headers=admin)
        self.assertEqual(proof_response.status_code, 200)
        self.assertTrue(proof_response.get_data().startswith(b'\x89PNG'))
        proof_response.close()
        self.assertEqual(self.client.get(proof_url, headers=citizen).status_code, 403)
        set_demo_password('second-fixture-only-password')
        self.assertEqual(self.client.post('/login', json={'email': EMAILS['admin'],
            'password': 'fixture-only-long-password'}).status_code, 401)
        self.assertEqual(self.client.post('/login', json={'email': EMAILS['admin'],
            'password': 'second-fixture-only-password'}).status_code, 200)

    def test_cleanup_deletes_fixture_and_refuses_mixed_records(self):
        seed_demo_data('fixture-only-long-password')
        outsider = User(name='Real user', email='real@test.invalid', phone='123', password='unused')
        db.session.add(outsider)
        db.session.commit()
        with self.assertRaisesRegex(RuntimeError, 'cleanup refused'):
            cleanup_demo_data()
        self.assertEqual(User.query.count(), 9)
        db.session.delete(outsider)
        db.session.commit()
        self.assertTrue(cleanup_demo_data())
        self.assertFalse(cleanup_demo_data())
        self.assertFalse((proof_directory() / 'demo-seed-v1.png').exists())
        self.assertTrue(all(count == 0 for count in (
            User.query.count(), HelpRequest.query.count(), DisasterReport.query.count(),
            ReliefTask.query.count(), ReliefResource.query.count(), WeatherAlert.query.count())))

    def test_existing_rows_and_production_are_never_seeded(self):
        db.session.add(User(name='Existing', email='existing@test.invalid', phone='123', password='unused'))
        db.session.commit()
        with self.assertRaisesRegex(RuntimeError, 'other or changed records'):
            seed_demo_data('fixture-only-long-password')
        self.assertEqual(User.query.count(), 1)
        self.app.config['APP_ENV'] = 'production'
        with self.assertRaisesRegex(RuntimeError, 'disabled in production'):
            seed_demo_data('fixture-only-long-password')
        with self.assertRaisesRegex(RuntimeError, 'disabled in production'):
            cleanup_demo_data()

    def test_failed_seed_rolls_back_every_table(self):
        with patch.object(db.session, 'commit', side_effect=RuntimeError('fixture failure')):
            with self.assertRaisesRegex(RuntimeError, 'fixture failure'):
                seed_demo_data('fixture-only-long-password')
        self.assertTrue(all(count == 0 for count in (
            User.query.count(), Volunteer.query.count(), HelpRequest.query.count(),
            DisasterReport.query.count(), WeatherAlert.query.count())))
        self.assertFalse((proof_directory() / 'demo-seed-v1.png').exists())


if __name__ == '__main__':
    unittest.main()
