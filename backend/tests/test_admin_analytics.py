"""Actual admin endpoints against SQLite memory data; no existing DB is opened."""
from collections import Counter
from datetime import datetime, timedelta, timezone
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from flask import Flask
from flask_jwt_extended import create_access_token
from extensions import db, jwt
from models import User, Volunteer, HelpRequest, DisasterReport, ReliefTask
from routes.admin import admin_bp


class AdminAnalyticsTests(unittest.TestCase):
    def setUp(self):
        self.app = Flask(__name__)
        self.app.config.update(TESTING=True, SQLALCHEMY_DATABASE_URI='sqlite:///:memory:',
                               SQLALCHEMY_TRACK_MODIFICATIONS=False,
                               JWT_SECRET_KEY='admin-analytics-tests-only-secret-at-least-32-characters')
        db.init_app(self.app); jwt.init_app(self.app)
        self.app.register_blueprint(admin_bp)
        self.context = self.app.app_context(); self.context.push()
        db.create_all()
        self.users = {}
        for key, role in [('reporter', 'reporter'), ('volunteer', 'volunteer'),
                          ('busy', 'volunteer'), ('offline', 'volunteer'), ('ngo', 'ngo'), ('admin', 'admin')]:
            user = User(name='Fixture', email=key+'@test.invalid', phone='test', password='unused', role=role)
            db.session.add(user); db.session.flush()
            self.users[key] = user
        self.vols = [Volunteer(user_id=self.users[key].user_id, availability_status=status)
                     for key, status in [('volunteer', 'available'), ('busy', 'on_task'), ('offline', 'unavailable')]]
        db.session.add_all(self.vols); db.session.commit()
        self.client = self.app.test_client()

    def tearDown(self):
        db.session.remove(); db.engine.dispose(); self.context.pop()

    def headers(self, account='admin', **claims):
        token = create_access_token(identity=str(self.users[account].user_id), additional_claims=claims)
        return {'Authorization': 'Bearer '+token}

    def populate(self):
        now = datetime.now(timezone.utc).replace(tzinfo=None)
        midnight = now.replace(hour=0, minute=0, second=0, microsecond=0)
        dates = [now-timedelta(hours=1), now-timedelta(hours=2),
                 midnight-timedelta(days=2, seconds=1), midnight-timedelta(days=2),
                 now-timedelta(days=7)+timedelta(hours=1), now-timedelta(days=7,hours=1)]
        self.requests = []
        for i, status in enumerate(['Pending', 'Accepted', 'En Route', 'On Site', 'Completed', 'Duplicate']):
            req = HelpRequest(user_id=self.users['reporter'].user_id, name='Fixture', contact='test',
                              request_type=['Rescue', 'Food', 'Water', 'Medicine', 'Shelter', 'Food'][i],
                              latitude=10, longitude=76, status=status,
                              priority_level='High' if i < 2 else 'Medium', is_duplicate=status=='Duplicate')
            req.created_at = dates[i]
            self.requests.append(req)
        db.session.add_all(self.requests); db.session.flush()
        db.session.add_all([ReliefTask(volunteer_id=self.vols[0].volunteer_id,
                                      request_id=self.requests[4].request_id, status='Completed', verification_status='Approved'),
                            ReliefTask(volunteer_id=self.vols[1].volunteer_id,
                                       request_id=self.requests[1].request_id, status='Assigned')])
        self.reports = [DisasterReport(user_id=self.users['reporter'].user_id, disaster_type=kind,
                                       description='Fixture', latitude=10, longitude=76)
                        for kind in ['Flood', 'Cyclone', 'Flood']]
        db.session.add_all(self.reports); db.session.commit()
        return dates

    def test_sqlite_analytics_has_iso_days_correct_groups_and_rolling_window(self):
        dates = self.populate()
        response = self.client.get('/admin/analytics', headers=self.headers())
        self.assertEqual(response.status_code, 200)
        data = response.json
        expected = Counter(d.date().isoformat() for d in dates[:-1])
        self.assertEqual(data['by_day'], [{'day': d, 'count': expected[d]} for d in sorted(expected)])
        self.assertEqual(sum(row['count'] for row in data['by_day']), 5)
        self.assertEqual(data['by_type'], dict(Counter(r.request_type for r in self.requests)))
        self.assertEqual(data['by_status'], dict(Counter(r.status for r in self.requests)))
        self.assertEqual(data['by_priority'], dict(Counter(r.priority_level for r in self.requests)))
        self.assertEqual(data['by_disaster'], {'Flood': 2, 'Cyclone': 1})
        self.assertEqual(data['by_role'], {'reporter': 1, 'volunteer': 3, 'ngo': 1, 'admin': 1})

    def test_dashboard_counts_distinguish_busy_offline_and_completed_tasks(self):
        self.populate()
        response = self.client.get('/admin/dashboard', headers=self.headers())
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json['stats'], {
            'total_requests': 6, 'high_priority': 2, 'active_volunteers': 1, 'busy_volunteers': 1,
            'completed_tasks': 1, 'completed': 1, 'pending': 1, 'accepted': 1, 'duplicate': 1,
            'disaster_reports': 3, 'total_volunteers': 3, 'total_victims': 1, 'total_ngos': 1, 'relief_tasks': 2})
        self.assertEqual([r['request_id'] for r in response.json['recent_high']], [self.requests[0].request_id])

    def test_empty_incident_data_returns_empty_breakdowns(self):
        response = self.client.get('/admin/analytics', headers=self.headers())
        self.assertEqual(response.status_code, 200)
        for key in ['by_type', 'by_status', 'by_priority', 'by_disaster']:
            self.assertEqual(response.json[key], {})
        self.assertEqual(response.json['by_day'], [])

    def test_private_analytics_and_dashboard_require_database_admin_role(self):
        for endpoint in ['/admin/dashboard', '/admin/analytics']:
            self.assertEqual(self.client.get(endpoint).status_code, 401)
            for role in ['reporter', 'volunteer', 'ngo']:
                self.assertEqual(self.client.get(endpoint, headers=self.headers(role)).status_code, 403)
            self.assertEqual(self.client.get(endpoint, headers=self.headers('reporter', role='admin')).status_code, 403)


if __name__ == '__main__':
    unittest.main()
