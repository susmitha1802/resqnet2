"""Homepage aggregate and weather responses with isolated SQLite and mock provider data."""
import io
import json
import os
from pathlib import Path
import sys
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch
from urllib.error import URLError

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app import create_app
from extensions import db
from models import User, Volunteer


class HomepageDataTests(unittest.TestCase):
    def setUp(self):
        self.storage = TemporaryDirectory()
        config = type('HomepageFixture', (), dict(
            TESTING=True, APP_ENV='testing', SECRET_KEY='fixture-session-secret',
            JWT_SECRET_KEY='fixture-jwt-secret-over-32-characters',
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

    def test_empty_stats_are_zero_and_volunteer_total_is_record_based(self):
        empty = self.client.get('/public/stats')
        self.assertEqual(empty.status_code, 200)
        self.assertEqual(empty.json['stats'], dict(total_requests=0, active_requests=0,
            active_volunteers=0, total_volunteers=0, completed=0))
        user = User(name='Fixture', email='offline@test.invalid', phone='test',
                    password='unused', role='volunteer')
        db.session.add(user)
        db.session.flush()
        db.session.add(Volunteer(user_id=user.user_id, availability_status='unavailable'))
        db.session.commit()
        inactive = self.client.get('/public/stats').json['stats']
        self.assertEqual(inactive['active_volunteers'], 0)
        self.assertEqual(inactive['total_volunteers'], 1)

    def test_weather_keeps_current_observation_if_forecast_fails(self):
        current = {'name': 'Provider Place', 'main': {'temp': 27.5, 'humidity': 72},
                   'weather': [{'main': 'Clouds', 'description': 'scattered clouds'}],
                   'wind': {'speed': 3.5}, 'rain': {'1h': 0.4}}

        def provider(req, timeout):
            if '/forecast?' in req.full_url:
                raise URLError('private provider detail')
            return io.BytesIO(json.dumps(current).encode())

        with patch.dict(os.environ, {'OPENWEATHER_API_KEY': 'fixture-private-key'}), \
                patch('routes.alerts.urllib.request.urlopen', side_effect=provider):
            result = self.client.get('/weather/live')
        self.assertEqual(result.status_code, 200)
        self.assertEqual(result.json['current'], current)
        self.assertEqual(result.json['forecast'], [])
        self.assertFalse(result.json['forecast_available'])
        self.assertNotIn('fixture-private-key', str(result.json))

    def test_weather_preserves_available_forecast(self):
        current = {'main': {'temp': 20}, 'weather': [{'main': 'Clear'}]}
        forecast = {'list': [{'dt_txt': '2026-10-21 12:00:00'},
                             {'dt_txt': '2026-10-21 15:00:00'},
                             {'dt_txt': '2026-10-22 12:00:00'}]}
        responses = [io.BytesIO(json.dumps(current).encode()),
                     io.BytesIO(json.dumps(forecast).encode())]
        with patch.dict(os.environ, {'OPENWEATHER_API_KEY': 'fixture-private-key'}), \
                patch('routes.alerts.urllib.request.urlopen', side_effect=responses):
            result = self.client.get('/weather/live')
        self.assertEqual(result.status_code, 200)
        self.assertTrue(result.json['forecast_available'])
        self.assertEqual(len(result.json['forecast']), 2)

    def test_weather_missing_key_and_current_provider_failure_are_unavailable(self):
        with patch.dict(os.environ, {'OPENWEATHER_API_KEY': ''}):
            self.assertEqual(self.client.get('/weather/live').status_code, 503)
        with patch.dict(os.environ, {'OPENWEATHER_API_KEY': 'fixture-private-key'}), \
                patch('routes.alerts.urllib.request.urlopen', side_effect=URLError('private provider detail')):
            result = self.client.get('/weather/live')
        self.assertEqual(result.status_code, 502)
        self.assertNotIn('private', str(result.json))


if __name__ == '__main__':
    unittest.main()
