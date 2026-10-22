"""Map provenance checks using the real app and seed in a memory-only database."""
from contextlib import redirect_stdout
from datetime import datetime, timedelta, timezone
import io
from pathlib import Path
import sys
from tempfile import TemporaryDirectory
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app import create_app
from extensions import db
from models import WeatherAlert, User, HelpRequest, DisasterReport
from flask_jwt_extended import create_access_token
from map_provenance import LEGACY_FLOOD_TEXT
from seed_demo import TAG


class MapProvenanceTests(unittest.TestCase):
    def setUp(self):
        self.storage = TemporaryDirectory(prefix='resqnet-map-')
        class Config:
            SEED_DEMO_DATA = True  # Explicitly opt in for this memory-only fixture.
            TESTING = True
            DEBUG = False
            SECRET_KEY = 'map-tests-only'
            JWT_SECRET_KEY = 'map-tests-only-secret-at-least-32-characters'
            SQLALCHEMY_DATABASE_URI = 'sqlite:///:memory:'
            SQLALCHEMY_TRACK_MODIFICATIONS = False
            UPLOAD_FOLDER = self.storage.name
        with redirect_stdout(io.StringIO()):
            self.app = create_app(Config)
        self.context = self.app.app_context()
        self.context.push()
        self.client = self.app.test_client()
        self.map_headers = {'Authorization': 'Bearer ' + create_access_token(
            identity=str(User.query.filter_by(role='admin').first().user_id))}

    def tearDown(self):
        db.session.remove()
        db.engine.dispose()
        self.context.pop()
        self.storage.cleanup()

    def test_seed_alert_is_explicit_demo_and_hidden_by_default(self):
        alert = WeatherAlert.query.one()
        self.assertTrue(alert.description.startswith(TAG))
        self.assertEqual(alert.source, 'Demo seed data')
        self.assertEqual(self.client.get('/map/risk-zones').json['zones'], [])
        self.assertEqual(self.client.get('/alerts').json['alerts'], [])
        preview = self.client.get('/map/risk-zones?include_demo=1').json['zones'][0]
        self.assertTrue(preview['is_demo'])
        self.assertEqual(preview['source'], 'Demo seed data')
        self.assertIn('not a live forecast', preview['description'])
        self.assertEqual((preview['lat'], preview['lng']), (17.4401, 78.4487))

    def test_legacy_seed_with_false_weather_source_is_still_identified(self):
        alert = WeatherAlert.query.one()
        alert.source = 'OpenWeatherMap'
        alert.description = LEGACY_FLOOD_TEXT
        alert.severity = 'Emergency'
        alert.affected_radius_km = 50
        db.session.commit()
        self.assertEqual(self.client.get('/map/risk-zones').json['zones'], [])
        alert = self.client.get('/alerts?include_demo=1').json['alerts'][0]
        self.assertTrue(alert['is_demo'])
        self.assertEqual(alert['source'], 'Demo seed data')

    def test_unmarked_legacy_seed_incidents_are_identified_without_modifying_them(self):
        for incident in DisasterReport.query.all():
            incident.description = incident.description.removeprefix('[DEMO] ')
        for incident in HelpRequest.query.all():
            incident.description = None
        db.session.commit()
        data = self.client.get('/map/data', headers=self.map_headers).json
        self.assertEqual(data['requests'], [])
        self.assertEqual(data['reports'], [])
        self.assertEqual(DisasterReport.query.count(), 3)

    def test_default_incident_feed_excludes_exact_seed_records_but_keeps_volunteers(self):
        data = self.client.get('/map/data', headers=self.map_headers).json
        self.assertTrue(data['success'])
        self.assertEqual(data['requests'], [])
        self.assertEqual(data['reports'], [])
        self.assertEqual(data['total_active'], 0)
        self.assertGreater(len(data['volunteers']), 0)
        preview = self.client.get('/map/data?include_demo=1', headers=self.map_headers).json
        self.assertTrue(all(r['is_demo'] for r in preview['requests'] + preview['reports']))
        self.assertEqual(len(preview['reports']), 3)

    def test_real_incidents_outside_hyderabad_use_their_own_coordinates_and_metadata(self):
        user = User(name='New reporter', email='new@test.invalid', phone='123', password='unused')
        db.session.add(user)
        db.session.flush()
        request = HelpRequest(user_id=user.user_id, name='Citizen', contact='123', request_type='Food',
                              latitude=9.9312, longitude=76.2673, status='On Site')
        report = DisasterReport(user_id=user.user_id, disaster_type='Flood', description='Observed water on road',
                                latitude=12.9716, longitude=77.5946)
        db.session.add_all([request, report])
        db.session.commit()
        data = self.client.get('/map/data', headers=self.map_headers).json
        self.assertEqual(data['total_active'], 2)
        self.assertEqual(data['requests'][0]['latitude'], 9.9312)
        self.assertEqual(data['requests'][0]['status'], 'On Site')
        self.assertEqual(data['requests'][0]['source'], 'Community SOS request')
        self.assertEqual(data['reports'][0]['longitude'], 77.5946)
        self.assertIn('unverified', data['reports'][0]['source'])
        self.assertFalse(data['reports'][0]['is_demo'])

    def test_same_city_does_not_make_a_real_alert_demo_and_expired_alerts_are_excluded(self):
        fresh = WeatherAlert('Storm', 'Manual observation from local coordinator', 17.4401, 78.4487, source='Manual')
        expired = WeatherAlert('Flood', 'Expired observation', 9.9, 76.2, source='Manual',
                               expires_at=datetime.now(timezone.utc) - timedelta(hours=1))
        db.session.add_all([fresh, expired])
        db.session.commit()
        zones = self.client.get('/map/risk-zones').json['zones']
        self.assertEqual(len(zones), 1)
        self.assertEqual(zones[0]['alert_id'], fresh.alert_id)
        self.assertEqual(zones[0]['source'], 'Manual')
        self.assertEqual(zones[0]['status'], 'Active alert')
        self.assertIn('not an official warning', zones[0]['risk_basis'])
        self.assertFalse(zones[0]['is_demo'])


if __name__ == '__main__':
    unittest.main()
