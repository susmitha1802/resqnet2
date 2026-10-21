"""Notification persistence/authorization with memory-only data and temporary uploads."""
from pathlib import Path
import sys
from tempfile import TemporaryDirectory
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from sqlalchemy.exc import SQLAlchemyError

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app import create_app
from extensions import db
from flask_jwt_extended import create_access_token
from models import PreparednessPing, User, WeatherAlert


class NotificationTests(unittest.TestCase):
    def setUp(self):
        self.storage = TemporaryDirectory(prefix='resqnet-notifications-')
        self.app = create_app(type('NotificationConfig', (), dict(
            TESTING=True, APP_ENV='testing', DEBUG=False, SEED_DEMO_DATA=False,
            RATELIMIT_ENABLED=False, SECRET_KEY='isolated-notification-session-secret',
            JWT_SECRET_KEY='isolated-notification-signing-secret',
            SQLALCHEMY_DATABASE_URI='sqlite:///:memory:', SQLALCHEMY_TRACK_MODIFICATIONS=False,
            UPLOAD_FOLDER=self.storage.name, CORS_ORIGINS=[])))
        self.context = self.app.app_context()
        self.context.push()
        self.client = self.app.test_client()
        self.users = {}
        for key, role, location in [('admin', 'admin', None), ('reporter', 'reporter', '10,76'),
            ('volunteer', 'volunteer', '10,76'), ('ngo', 'ngo', '10,76'),
            ('far', 'volunteer', '28,77'), ('unknown', 'ngo', 'Fixture organization')]:
            user = User(name='Fixture', email=key+'@test.invalid', phone='private fixture',
                        password='unused', role=role, location=location)
            db.session.add(user)
            db.session.flush()
            self.users[key] = user.user_id
        alert = WeatherAlert('Storm', 'Fixture unverified advisory', 10, 76,
                             affected_radius_km=10, source='Manual')
        db.session.add(alert)
        db.session.commit()
        self.alert_id = alert.alert_id

    def tearDown(self):
        db.session.remove()
        db.engine.dispose()
        self.context.pop()
        self.storage.cleanup()

    def headers(self, role='admin'):
        return {'Authorization': 'Bearer '+create_access_token(identity=str(self.users[role]))}

    def notify(self, headers=None):
        return self.client.put(f'/alerts/{self.alert_id}/notify',
                               headers=headers if headers is not None else self.headers())

    def test_notify_reports_committed_in_app_counts_and_preserves_recipient_privacy(self):
        result = self.notify()
        self.assertEqual(result.status_code, 200)
        self.assertEqual(result.json['pings_created'], 2)
        self.assertEqual(result.json['pings_sent'], 2)  # Existing compatibility key.
        self.assertEqual(result.json['by_role'], {'volunteer': 1, 'ngo': 1})
        self.assertEqual(result.json['already_recorded'], 0)
        self.assertIn('no external delivery', result.json['delivery'])
        self.assertNotIn('private fixture', str(result.json))
        self.assertEqual({p.user_id for p in PreparednessPing.query.all()},
                         {self.users['volunteer'], self.users['ngo']})
        self.assertTrue(all(p.status == 'Sent' for p in PreparednessPing.query.all()))

    def test_replay_records_nothing_new_and_does_not_reset_acknowledgements(self):
        self.notify()
        ping = PreparednessPing.query.filter_by(user_id=self.users['volunteer']).one()
        self.client.put(f'/preparedness/ping/{ping.ping_id}', headers=self.headers('volunteer'),
                        json={'status': 'Acknowledged'})
        result = self.notify()
        self.assertEqual(result.status_code, 200)
        self.assertEqual(result.json['pings_created'], 0)
        self.assertEqual(result.json['by_role'], {'volunteer': 0, 'ngo': 0})
        self.assertEqual(result.json['already_recorded'], 2)
        self.assertEqual(PreparednessPing.query.count(), 2)
        db.session.expire_all()
        self.assertEqual(db.session.get(PreparednessPing, ping.ping_id).status, 'Acknowledged')

    def test_response_survives_fresh_client_read_and_admin_sees_actual_status(self):
        self.notify()
        for role, status in [('volunteer', 'Acknowledged'), ('ngo', 'Unavailable')]:
            ping = PreparednessPing.query.filter_by(user_id=self.users[role]).one()
            result = self.client.put(f'/preparedness/ping/{ping.ping_id}', headers=self.headers(role),
                                     json={'status': status})
            self.assertEqual(result.status_code, 200)
            self.assertEqual(result.json['ping'], {'ping_id': ping.ping_id, 'status': status})
            db.session.expire_all()
            reloaded = self.app.test_client().get('/preparedness/my-pings', headers=self.headers(role))
            self.assertEqual(reloaded.json['pending_count'], 0)
            self.assertEqual([p['status'] for p in reloaded.json['pings']], [status])
            self.assertIsNotNone(reloaded.json['pings'][0]['acknowledged_at'])
            self.assertEqual(self.client.put(f'/preparedness/ping/{ping.ping_id}',
                headers=self.headers(role), json={'status': status}).status_code, 409)
        admin = self.client.get(f'/alerts/{self.alert_id}/responses', headers=self.headers())
        self.assertEqual({p['status'] for p in admin.json['responses']}, {'Acknowledged', 'Unavailable'})

    def test_authorization_and_cross_account_responses_leave_records_unchanged(self):
        self.assertEqual(self.notify(headers={}).status_code, 401)
        for role in ['reporter', 'volunteer', 'ngo']:
            self.assertEqual(self.notify(headers=self.headers(role)).status_code, 403)
        self.notify()
        ping = PreparednessPing.query.filter_by(user_id=self.users['volunteer']).one()
        path = f'/preparedness/ping/{ping.ping_id}'
        self.assertEqual(self.client.put(path, json={'status': 'Acknowledged'}).status_code, 401)
        for role in ['reporter', 'admin', 'ngo']:
            self.assertEqual(self.client.put(path, headers=self.headers(role),
                                            json={'status': 'Acknowledged'}).status_code, 403)
        for role in ['reporter', 'volunteer', 'ngo']:
            self.assertEqual(self.client.get(f'/alerts/{self.alert_id}/responses',
                                             headers=self.headers(role)).status_code, 403)
        self.assertEqual(db.session.get(PreparednessPing, ping.ping_id).status, 'Sent')

    def test_invalid_response_payloads_are_rejected_without_changing_pending_state(self):
        self.notify()
        ping = PreparednessPing.query.filter_by(user_id=self.users['volunteer']).one()
        for body in [None, ['Acknowledged'], True, {}, {'status': None}, {'status': 123},
                     {'status': 'Ready'}, {'status': ['Acknowledged']}]:
            with self.subTest(body=body):
                response = self.client.put(f'/preparedness/ping/{ping.ping_id}',
                    headers=self.headers('volunteer'), json=body)
                self.assertEqual(response.status_code, 400)
                db.session.expire_all()
                self.assertEqual(db.session.get(PreparednessPing, ping.ping_id).status, 'Sent')
                self.assertIsNone(db.session.get(PreparednessPing, ping.ping_id).acknowledged_at)

    def test_failed_notification_commit_rolls_back_pings_and_advisory_timestamp(self):
        with patch.object(db.session, 'commit', side_effect=SQLAlchemyError('private database detail')):
            result = self.notify()
        self.assertEqual(result.status_code, 503)
        self.assertFalse(result.json['success'])
        self.assertNotIn('private database detail', str(result.json))
        self.assertEqual(PreparednessPing.query.count(), 0)
        self.assertIsNone(db.session.get(WeatherAlert, self.alert_id).notified_at)
        self.assertEqual(self.notify().json['pings_created'], 2)

    def test_failed_response_commit_rolls_back_status_and_timestamp(self):
        self.notify()
        ping = PreparednessPing.query.filter_by(user_id=self.users['volunteer']).one()
        with patch.object(db.session, 'commit', side_effect=SQLAlchemyError('private database detail')):
            response = self.client.put(f'/preparedness/ping/{ping.ping_id}',
                headers=self.headers('volunteer'), json={'status': 'Acknowledged'})
        self.assertEqual(response.status_code, 503)
        self.assertFalse(response.json['success'])
        self.assertNotIn('private database detail', str(response.json))
        db.session.expire_all()
        self.assertEqual(db.session.get(PreparednessPing, ping.ping_id).status, 'Sent')
        self.assertIsNone(db.session.get(PreparednessPing, ping.ping_id).acknowledged_at)

    def test_no_eligible_recipients_and_lost_claim_never_claim_new_records(self):
        with patch('routes.alerts._users_in_radius', return_value=[]):
            result = self.notify()
        self.assertEqual(result.status_code, 200)
        self.assertEqual(result.json['pings_created'], 0)
        self.assertEqual(PreparednessPing.query.count(), 0)
        with patch.object(db.session, 'execute', return_value=SimpleNamespace(rowcount=0)):
            result = self.notify()
        self.assertEqual(result.status_code, 409)
        self.assertFalse(result.json['success'])
        self.assertEqual(PreparednessPing.query.count(), 0)


if __name__ == '__main__':
    unittest.main()
