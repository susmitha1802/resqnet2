"""Production regressions: temporary data only; no Render, Redis or real database writes."""
from contextlib import redirect_stdout, closing
import hashlib
import io
import os
from pathlib import Path
import sqlite3
import subprocess
import sys
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from flask import Flask
from flask_jwt_extended import create_access_token
from redis.exceptions import ConnectionError as RedisConnectionError
from app import create_app
from extensions import db
from models import User, HelpRequest


class ProductionBackendTests(unittest.TestCase):
    def setUp(self):
        self.storage = TemporaryDirectory(prefix='resqnet-production-')
        self.config = dict(TESTING=True, DEBUG=False, APP_ENV='production', SEED_DEMO_DATA=False,
            SECRET_KEY='isolated-session-secret-with-32-characters',
            JWT_SECRET_KEY='isolated-token-secret-with-at-least-32-characters',
            SQLALCHEMY_DATABASE_URI='sqlite:///:memory:', SQLALCHEMY_TRACK_MODIFICATIONS=False,
            UPLOAD_FOLDER=self.storage.name, CORS_ORIGINS=['https://resqnet1-2026.netlify.app'],
            RATELIMIT_STORAGE_URI='memory://', RATELIMIT_ENABLED=True, TRUSTED_PROXY_HOPS=0)
        self.app = self.make_app()
        self.context = self.app.app_context(); self.context.push()
        self.client = self.app.test_client()

    def make_app(self, **values):
        with redirect_stdout(io.StringIO()):
            return create_app(type('ProductionFixture', (), self.config | values))

    def tearDown(self):
        db.session.remove(); db.engine.dispose(); self.context.pop(); self.storage.cleanup()

    def test_login_registration_limits_and_cors_preflight(self):
        for path, maximum in [('/login', 10), ('/register', 5), ('/contact', 5)]:
            for _ in range(maximum):
                self.assertEqual(self.client.post(path, json={}).status_code, 400)
            result = self.client.post(path, json={}, headers={'Origin':'https://resqnet1-2026.netlify.app'})
            self.assertEqual(result.status_code, 429)
            self.assertFalse(result.json['success'])
            self.assertGreater(int(result.headers['Retry-After']), 0)
            self.assertEqual(result.headers['Access-Control-Allow-Origin'], 'https://resqnet1-2026.netlify.app')
            self.assertEqual(self.client.options(path).status_code, 200)

    def test_authenticated_sos_limit_does_not_create_invalid_or_throttled_records(self):
        user = User(name='Fixture',email='reporter@test.invalid',phone='test',password='unused',role='reporter')
        db.session.add(user); db.session.commit()
        headers = {'Authorization':'Bearer '+create_access_token(identity=str(user.user_id))}
        for _ in range(10):
            self.assertEqual(self.client.post('/help-request',data={},headers=headers).status_code,400)
        self.assertEqual(self.client.post('/help-request',data={},headers=headers).status_code,429)
        self.assertEqual(HelpRequest.query.count(),0)

    def test_direct_clients_cannot_evade_limits_with_forged_forwarded_headers(self):
        for i in range(10):
            self.assertEqual(self.client.post('/login',json={},headers={'X-Forwarded-For':f'192.0.2.{i}'}).status_code,400)
        self.assertEqual(self.client.post('/login',json={},headers={'X-Forwarded-For':'198.51.100.55'}).status_code,429)

    def test_proxy_uses_only_configured_trusted_suffix_and_separates_real_clients(self):
        app = self.make_app(TRUSTED_PROXY_HOPS=1)
        client = app.test_client()
        for i in range(10):
            self.assertEqual(client.post('/login',json={},headers={'X-Forwarded-For':f'192.0.2.{i}, 198.51.100.1'}).status_code,400)
        self.assertEqual(client.post('/login',json={},headers={'X-Forwarded-For':'192.0.2.99, 198.51.100.1'}).status_code,429)
        self.assertEqual(client.post('/login',json={},headers={'X-Forwarded-For':'198.51.100.2'}).status_code,400)
        with app.app_context():
            db.session.remove(); db.engine.dispose()

    def test_rate_store_outage_blocks_handler_without_leaking_connection_details(self):
        limiter = self.app.extensions['resqnet_limiter']
        with patch.object(limiter.storage,'incr',side_effect=RedisConnectionError('private redis credential')), patch('routes.auth.bcrypt.hashpw') as hashing:
            self.assertEqual(self.client.get('/health').status_code,200)
            response = self.client.post('/register',json={'name':'Fixture','phone':'test',
                'email':'new@test.invalid','password':'isolated-password'})
        self.assertEqual(response.status_code,503)
        self.assertNotIn('private redis credential',str(response.json))
        hashing.assert_not_called()
        self.assertEqual(User.query.count(),0)

    def test_production_refuses_memory_disabled_counters_missing_mount_and_bad_proxy(self):
        base = dict(TESTING=False,PERSISTENT_STORAGE_PATH=self.storage.name,
            SQLALCHEMY_DATABASE_URI='sqlite:///'+(Path(self.storage.name)/'new.db').as_posix())
        for invalid in [dict(RATELIMIT_STORAGE_URI='memory://'),dict(RATELIMIT_ENABLED=False),
                        dict(TRUSTED_PROXY_HOPS=-1),dict(RUNNING_ON_RENDER=True,TRUSTED_PROXY_HOPS=0)]:
            with self.subTest(config=next(iter(invalid))):
                with self.assertRaises(RuntimeError):
                    self.make_app(**(base | invalid))
        with patch('pathlib.Path.is_mount',return_value=False), self.assertRaisesRegex(RuntimeError,'attached disk mount'):
            self.make_app(**(base | dict(RUNNING_ON_RENDER=True,TRUSTED_PROXY_HOPS=1,
                                        RATELIMIT_STORAGE_URI='redis://127.0.0.1:6379/15')))
        self.assertFalse((Path(self.storage.name)/'new.db').exists())

    def test_redis_startup_failure_is_generic_and_precedes_database_initialization(self):
        with patch('limits.storage.RedisStorage.check',return_value=False), self.assertRaisesRegex(RuntimeError,'storage is unavailable'):
            self.make_app(TESTING=False,PERSISTENT_STORAGE_PATH=self.storage.name,
                RATELIMIT_STORAGE_URI='redis://127.0.0.1:6379/15',
                SQLALCHEMY_DATABASE_URI='sqlite:///'+(Path(self.storage.name)/'not-created.db').as_posix())
        self.assertFalse((Path(self.storage.name)/'not-created.db').exists())

    def test_incompatible_existing_schema_fails_without_modifying_file(self):
        from database import initialize_database
        path = Path(self.storage.name)/'legacy.db'
        with closing(sqlite3.connect(path)) as connection:
            with connection:
                connection.execute('CREATE TABLE users (user_id INTEGER PRIMARY KEY)')
                connection.execute('INSERT INTO users VALUES (1)')
        before = hashlib.sha256(path.read_bytes()).digest()
        app = Flask('legacy-schema-fixture')
        app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///'+path.as_posix()
        db.init_app(app)
        with app.app_context():
            with self.assertRaisesRegex(RuntimeError,'schema is incompatible'):
                initialize_database()
            db.session.remove(); db.engine.dispose()
        self.assertEqual(hashlib.sha256(path.read_bytes()).digest(),before)

    def test_database_and_private_images_survive_second_factory_on_same_temp_storage(self):
        from PIL import Image
        from werkzeug.datastructures import FileStorage
        from private_uploads import save_incident_image
        from sos_lifecycle import save_proof, proof_file
        settings = dict(SQLALCHEMY_DATABASE_URI='sqlite:///'+(Path(self.storage.name)/'persistent.db').as_posix(),
                        UPLOAD_FOLDER=str(Path(self.storage.name)/'private-images'))
        app = self.make_app(**settings)
        def image_upload():
            content=io.BytesIO(); Image.new('RGB',(2,2)).save(content,format='PNG');content.seek(0)
            return FileStorage(stream=content,filename='fixture.png')
        with app.app_context():
            db.session.add(User(name='Fixture',email='persist@test.invalid',phone='test',password='unused'))
            db.session.commit()
            report_path=Path(save_incident_image(image_upload(),'reports'))
            proof=save_proof(image_upload()); proof_path=proof_file(proof)
            report_hash=hashlib.sha256(report_path.read_bytes()).digest()
            proof_hash=hashlib.sha256(proof_path.read_bytes()).digest()
            db.session.remove(); db.engine.dispose()
        second = self.make_app(**settings)
        with second.app_context():
            self.assertEqual(User.query.count(),1)
            self.assertEqual(hashlib.sha256(report_path.read_bytes()).digest(),report_hash)
            self.assertEqual(hashlib.sha256(proof_file(proof).read_bytes()).digest(),proof_hash)
            db.session.remove(); db.engine.dispose()
        self.assertEqual(second.test_client().get('/uploads/'+proof).status_code,404)
        self.assertEqual(second.test_client().get('/uploads/reports/'+report_path.name).status_code,404)

    def test_wsgi_entry_point_starts_with_fresh_temp_database_and_rejects_missing_secrets(self):
        folder = Path(self.storage.name)
        environment = os.environ.copy()
        environment.update(APP_ENV='development',RENDER='false',FLASK_DEBUG='False',SEED_DEMO_DATA='False',
            DATABASE_URL='sqlite:///'+(folder/'wsgi.db').as_posix(),UPLOAD_FOLDER=str(folder/'uploads'),
            RATELIMIT_STORAGE_URI='memory://',TRUSTED_PROXY_HOPS='0')
        result = subprocess.run([sys.executable,'-B','-c',
            "from wsgi import application; from extensions import db; from models import User; "
            "assert application.test_client().get('/health').status_code == 200; "
            "context=application.app_context(); context.push(); assert User.query.count()==0; "
            "db.session.remove(); db.engine.dispose(); context.pop()"],
            cwd=Path(__file__).resolve().parents[1],env=environment,capture_output=True)
        self.assertEqual(result.returncode,0,'Actual WSGI import/health check failed')
        environment.update(APP_ENV='production',SECRET_KEY='',JWT_SECRET_KEY='')
        result = subprocess.run([sys.executable,'-B','-c','import wsgi'],
            cwd=Path(__file__).resolve().parents[1],env=environment,capture_output=True)
        self.assertNotEqual(result.returncode,0)
        self.assertIn(b'Production requires',result.stderr)
