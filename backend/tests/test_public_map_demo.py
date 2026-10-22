"""Fictional map scenarios must remain separate from operational map data."""
import os
from pathlib import Path
import sys
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app import create_app
from extensions import db
from models import WeatherAlert
from public_map_demo import cleanup_map_demo, configured_engine, seed_map_demo


class PublicMapDemoTests(unittest.TestCase):
    def setUp(self):
        self.storage = TemporaryDirectory(prefix='resqnet-public-demo-')
        config = type('PublicMapDemoTestConfig', (), dict(
            TESTING=True, APP_ENV='testing', DEBUG=False, DEMO_MODE=False,
            SEED_DEMO_DATA=False, SECRET_KEY='public-demo-test-session',
            JWT_SECRET_KEY='public-demo-test-jwt-secret-over-32-characters',
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

    def test_seed_is_idempotent_public_only_in_demo_endpoint_and_reversible(self):
        real = WeatherAlert('Storm', 'Actual unverified observation', 11, 77,
                            source='Manual', severity='Watch')
        db.session.add(real)
        db.session.commit()
        self.assertEqual(self.client.get('/map/demo-scenarios').json['scenarios'], [])
        self.assertTrue(seed_map_demo(db.session))
        db.session.commit()
        self.assertFalse(seed_map_demo(db.session))
        self.assertEqual(WeatherAlert.query.count(), 4)
        data = self.client.get('/map/demo-scenarios')
        self.assertEqual(data.status_code, 200)
        self.assertEqual(data.headers['Cache-Control'], 'no-store')
        self.assertEqual(len(data.json['scenarios']), 3)
        for scenario in data.json['scenarios']:
            self.assertTrue(scenario['is_demo'])
            self.assertIn('FICTIONAL DEMO', scenario['notice'])
            self.assertNotIn('description', scenario)
        self.assertEqual(self.client.get('/map/data').json['total_active'], 0)
        self.assertEqual(self.client.get('/map/data').json['visibility'], 'aggregate-only')
        self.assertEqual(self.client.get('/map/risk-zones').json['zones'][0]['source'], 'Manual')
        self.assertEqual(len(self.client.get('/map/risk-zones').json['zones']), 1)
        self.assertEqual(self.client.get('/public/stats').json['stats']['total_requests'], 0)
        self.assertTrue(cleanup_map_demo(db.session))
        db.session.commit()
        self.assertFalse(cleanup_map_demo(db.session))
        self.assertEqual(WeatherAlert.query.count(), 1)
        self.assertEqual(self.client.get('/map/demo-scenarios').json['scenarios'], [])

    def test_partial_or_changed_fixture_is_never_exposed_or_cleaned(self):
        seed_map_demo(db.session)
        db.session.commit()
        one = WeatherAlert.query.filter(WeatherAlert.description.like('[DEMO] [resqnet2-public-map-v1]%')).first()
        one.description += ' changed'
        db.session.commit()
        self.assertEqual(self.client.get('/map/demo-scenarios').json['scenarios'], [])
        with self.assertRaisesRegex(RuntimeError, 'cleanup refused'):
            cleanup_map_demo(db.session)
        with self.assertRaisesRegex(RuntimeError, 'no records written'):
            seed_map_demo(db.session)
        self.assertEqual(WeatherAlert.query.count(), 3)

    def test_config_rejects_mismatched_or_insecure_database_without_connecting(self):
        with patch.dict(os.environ, {'RESQNET_DEMO_DATABASE_URL': 'sqlite:///wrong.db',
                                    'SUPABASE_URL': 'https://testref.supabase.co'}):
            with self.assertRaisesRegex(RuntimeError, 'Matching Supabase'):
                configured_engine()
        with patch.dict(os.environ, {'RESQNET_DEMO_DATABASE_URL':
                                    'postgresql+psycopg://postgres.otherref:x@aws-0.pooler.supabase.com:5432/postgres?sslmode=require',
                                    'SUPABASE_URL': 'https://testref.supabase.co'}):
            with self.assertRaisesRegex(RuntimeError, 'Matching Supabase'):
                configured_engine()
        with patch.dict(os.environ, {'RESQNET_DEMO_DATABASE_URL':
                                    'postgresql+psycopg://postgres.testref:x@aws-0.pooler.supabase.com:5432/postgres?sslmode=require',
                                    'SUPABASE_URL': 'https://testref.supabase.co'}):
            engine = configured_engine()
            self.assertEqual(engine.dialect.name, 'postgresql')
            engine.dispose()


if __name__ == '__main__':
    unittest.main()
