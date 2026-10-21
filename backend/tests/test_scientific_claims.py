"""Scientific provenance and preserved SOS rules using only temporary/memory data."""
import io
from pathlib import Path
import sys
from tempfile import TemporaryDirectory
import unittest

from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app import create_app
from extensions import db
from flask_jwt_extended import create_access_token
from models import DisasterReport, User


class ScientificClaimTests(unittest.TestCase):
    def setUp(self):
        self.storage = TemporaryDirectory(prefix='resqnet-scientific-claims-')
        config = type('ClaimTestConfig', (), dict(
            TESTING=True, APP_ENV='testing', DEBUG=False, SEED_DEMO_DATA=False,
            RATELIMIT_ENABLED=False, SECRET_KEY='isolated-claim-test-session-secret',
            JWT_SECRET_KEY='isolated-claim-test-signing-secret',
            SQLALCHEMY_DATABASE_URI='sqlite:///:memory:', SQLALCHEMY_TRACK_MODIFICATIONS=False,
            UPLOAD_FOLDER=self.storage.name, CORS_ORIGINS=[]))
        self.app = create_app(config)
        self.context = self.app.app_context()
        self.context.push()
        self.client = self.app.test_client()
        self.users = {}
        for role in ['reporter', 'admin']:
            user = User(name='Fixture', email=role+'@test.invalid', phone='test',
                        password='unused', role=role)
            db.session.add(user)
            db.session.flush()
            self.users[role] = user.user_id
        db.session.commit()

    def tearDown(self):
        db.session.remove()
        db.engine.dispose()
        self.context.pop()
        self.storage.cleanup()

    def headers(self, role='reporter'):
        return {'Authorization': 'Bearer '+create_access_token(identity=str(self.users[role]))}

    def assert_unvalidated(self, report):
        self.assertFalse(report['independently_verified'])
        self.assertIsNone(report['prediction_confidence'])
        self.assertEqual(report['severity_method'], 'Rule-based severity estimate (unvalidated)')
        self.assertIn('not independently verified', report['status'])
        self.assertIn('unverified', report['source'])

    def legacy_report(self):
        report = DisasterReport(user_id=self.users['reporter'], disaster_type='Fire',
                                description='Fixture observation', latitude=10, longitude=76,
                                predicted_disaster_type='Cyclone', prediction_confidence=98.4)
        db.session.add(report)
        db.session.commit()
        return report

    def test_new_reports_label_color_and_type_rules_as_unvalidated(self):
        for color, severity in [(None, 'Moderate Damage'), ('black', 'Severe Damage'), ('cyan', 'Low Damage')]:
            with self.subTest(image=color):
                data = dict(disaster_type='Fire', description='Fixture observation', latitude='10', longitude='76')
                if color:
                    image = io.BytesIO()
                    Image.new('RGB', (2, 2), color).save(image, format='PNG')
                    image.seek(0)
                    data['images'] = (image, 'fixture.png')
                response = self.client.post('/report-disaster', headers=self.headers(), data=data)
                self.assertEqual(response.status_code, 201)
                report = response.json['report']
                self.assertEqual(report['disaster_type'], 'Fire')
                self.assertEqual(report['severity'], severity)
                self.assert_unvalidated(report)

    def test_legacy_confidence_is_not_published_as_model_evidence_or_modified_in_storage(self):
        original = self.legacy_report()
        report_id = original.report_id
        for path in ['/reports', f'/report/{report_id}', '/map/data', '/admin/reports']:
            with self.subTest(path=path):
                response = self.client.get(path, headers=self.headers('admin'))
                self.assertEqual(response.status_code, 200)
                report = response.json.get('report') or response.json['reports'][0]
                self.assert_unvalidated(report)
        db.session.expire_all()
        stored = db.session.get(DisasterReport, report_id)
        self.assertEqual(stored.predicted_disaster_type, 'Cyclone')
        self.assertAlmostEqual(float(stored.prediction_confidence), 98.4)

    def test_admin_type_correction_is_not_scientific_verification(self):
        report = self.legacy_report()
        response = self.client.put(f'/admin/report/{report.report_id}/override',
                                   headers=self.headers('admin'), json={'disaster_type': 'Flood'})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json['report']['disaster_type'], 'Flood')
        self.assert_unvalidated(response.json['report'])

    def test_sos_priority_remains_server_rule_based(self):
        for index, (kind, people, priority) in enumerate([
            ('Rescue', 1, 'High'), ('Medicine', 1, 'High'), ('Food', 1, 'Medium'),
            ('Water', 1, 'Medium'), ('Shelter', 1, 'Low'), ('Shelter', 11, 'High')]):
            with self.subTest(kind=kind, people=people):
                response = self.client.post('/help-request', headers=self.headers(), data={
                    'name': 'Fixture', 'contact': 'test', 'request_type': kind,
                    'number_of_people': str(people), 'latitude': str(10+index), 'longitude': '76'})
                self.assertEqual(response.status_code, 201)
                self.assertEqual(response.json['request']['priority_level'], priority)
                self.assertEqual(response.json['ai']['priority'], priority)


if __name__ == '__main__':
    unittest.main()
