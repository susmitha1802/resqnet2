"""Admin-only proxy check using synthetic addresses and an in-memory database."""
from contextlib import redirect_stdout
import io
from pathlib import Path
import sys
from tempfile import TemporaryDirectory
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app import create_app
from extensions import db
from flask_jwt_extended import create_access_token
from models import User


class ProxyDiagnosticTests(unittest.TestCase):
    def setUp(self):
        self.storage = TemporaryDirectory()
        config = type('ProxyFixture', (), dict(
            TESTING=True, APP_ENV='testing', SECRET_KEY='fixture-session-secret-over-32-characters',
            JWT_SECRET_KEY='fixture-jwt-secret-over-32-characters',
            SQLALCHEMY_DATABASE_URI='sqlite:///:memory:',
            SQLALCHEMY_TRACK_MODIFICATIONS=False,
            UPLOAD_FOLDER=self.storage.name, RATELIMIT_STORAGE_URI='memory://',
            RATELIMIT_ENABLED=True, TRUSTED_PROXY_HOPS=1,
            PROXY_DIAGNOSTIC_ENABLED=True))
        with redirect_stdout(io.StringIO()):
            self.app = create_app(config)
        self.context = self.app.app_context()
        self.context.push()
        self.client = self.app.test_client()
        for role in ('admin', 'reporter'):
            user = User(name='Fixture', email=f'{role}@test.invalid', phone='test',
                        password='unused', role=role)
            db.session.add(user)
            db.session.flush()
            setattr(self, role + '_headers', {
                'Authorization': 'Bearer ' + create_access_token(identity=str(user.user_id))})
        db.session.commit()

    def tearDown(self):
        db.session.remove()
        db.engine.dispose()
        self.context.pop()
        self.storage.cleanup()

    def test_private_comparison_and_spoof_resistance(self):
        path = '/admin/proxy-diagnostic'
        self.assertEqual(self.client.get(path).status_code, 401)
        self.assertEqual(self.client.get(path, headers=self.reporter_headers).status_code, 403)
        def probe(chain):
            return self.client.get(path, headers=self.admin_headers | {'X-Forwarded-For': chain})
        first = probe('192.0.2.1, 198.51.100.1')
        spoofed = probe('192.0.2.99, 198.51.100.1')
        second = probe('192.0.2.1, 198.51.100.2')
        self.assertEqual(first.status_code, 200)
        self.assertEqual(first.json['client_code'], spoofed.json['client_code'])
        self.assertNotEqual(first.json['client_code'], second.json['client_code'])
        self.assertEqual(first.json['trusted_proxy_hops'], 1)
        self.assertEqual(first.headers['Cache-Control'], 'private, no-store')
        self.assertNotIn('198.51.100.', str(first.json))
        self.assertNotIn('192.0.2.', str(first.json))
        self.assertNotIn('X-Forwarded-For', str(first.json))

    def test_disabled_flag_does_not_register_route(self):
        with redirect_stdout(io.StringIO()):
            disabled = create_app(type('DisabledProxyFixture', (), {
                **dict(self.app.config), 'PROXY_DIAGNOSTIC_ENABLED': False}))
        self.assertEqual(disabled.test_client().get('/admin/proxy-diagnostic',
                        headers=self.admin_headers).status_code, 404)
        with disabled.app_context():
            db.session.remove()
            db.engine.dispose()


if __name__ == '__main__':
    unittest.main()
