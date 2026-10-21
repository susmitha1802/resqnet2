"""Cloud contracts use only synthetic records and an in-memory Storage API."""
import io
import json
import os
import subprocess
import sys
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch
from urllib.error import HTTPError
from urllib.parse import urlsplit

from flask import Flask
from flask_jwt_extended import create_access_token
from PIL import Image
from sqlalchemy import create_mock_engine
from sqlalchemy.exc import SQLAlchemyError

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app import create_app
from extensions import db
from models import DisasterReport, HelpRequest, ReliefTask, User, Volunteer
from security import validate_runtime_config
from supabase_storage import StorageUnavailable, check_private_bucket


class FakeStorage:
    def __init__(self):
        self.objects = {}
        self.requests = []
        self.fail = False
        self.fail_after_post = False
        self.public = False

    def open(self, request):
        self.requests.append(request)
        if self.fail:
            raise StorageUnavailable('private failure')
        resource = urlsplit(request.full_url).path
        if resource == '/storage/v1/bucket/private-evidence':
            return io.BytesIO(json.dumps({'id':'private-evidence', 'public':self.public}).encode())
        path = resource.split('/storage/v1/object/', 1)[1]
        method = request.get_method()
        assert request.get_header('Apikey', '').startswith('sb_secret_')
        if method == 'POST':
            bucket, key = path.split('/', 1)
            assert bucket == 'private-evidence'
            self.objects[key] = request.data
            if self.fail_after_post:
                raise StorageUnavailable('response was lost')
            return io.BytesIO(b'{}')
        if method == 'GET':
            assert path.startswith('authenticated/private-evidence/')
            key = path.removeprefix('authenticated/private-evidence/')
            if key not in self.objects:
                raise HTTPError(request.full_url, 404, 'missing', {}, None)
            return io.BytesIO(self.objects[key])
        if method == 'DELETE':
            assert path == 'private-evidence'
            for key in json.loads(request.data)['prefixes']:
                self.objects.pop(key, None)
            return io.BytesIO(b'[]')
        raise AssertionError('Unexpected Storage method')


class SupabaseDeploymentTests(unittest.TestCase):
    def test_config_selects_psycopg_and_small_pool_for_postgres_url(self):
        url = 'postgresql://postgres.testref:synthetic@aws-0-region.pooler.supabase.com:5432/postgres?sslmode=require'
        env = os.environ.copy()
        env['DATABASE_URL'] = url
        result = subprocess.run([sys.executable, '-B', '-c',
            "from config import Config; assert Config.SQLALCHEMY_DATABASE_URI.startswith('postgresql+psycopg://'); "
            "assert Config.SQLALCHEMY_ENGINE_OPTIONS['pool_size'] == 2"],
            cwd=Path(__file__).resolve().parents[1], env=env, capture_output=True)
        self.assertEqual(result.returncode, 0, 'PostgreSQL driver configuration did not initialize.')

    def test_model_schema_compiles_for_psycopg_postgresql_without_live_database(self):
        import psycopg
        import models
        statements = []
        engine = create_mock_engine('postgresql+psycopg://',
                                    lambda sql, *args, **kwargs: statements.append(str(sql.compile(dialect=engine.dialect))))
        db.metadata.create_all(engine, checkfirst=False)
        self.assertEqual(len(db.metadata.tables), 9)
        self.assertTrue(any('CREATE TYPE user_role' in ddl for ddl in statements))
        self.assertTrue(any('CREATE TABLE help_requests' in ddl for ddl in statements))

    def test_production_accepts_only_matching_tls_supabase_and_private_cloud_storage(self):
        base = dict(APP_ENV='production', TESTING=False, DEBUG=False, SEED_DEMO_DATA=False,
                    SECRET_KEY='s'*40, JWT_SECRET_KEY='j'*40, ADMIN_SECRET_CODE='',
                    CORS_ORIGINS=['https://resqnet-example.netlify.app'],
                    RATELIMIT_STORAGE_URI='redis://private.internal:6379', RATELIMIT_ENABLED=True,
                    TRUSTED_PROXY_HOPS=1, RUNNING_ON_RENDER=True, STORAGE_BACKEND='supabase',
                    SUPABASE_URL='https://testref.supabase.co',
                    SUPABASE_SECRET_KEY='sb_secret_'+'x'*32,
                    SUPABASE_STORAGE_BUCKET='private-evidence',
                    SQLALCHEMY_DATABASE_URI='postgresql+psycopg://postgres.testref:password@aws-0-region.pooler.supabase.com:5432/postgres?sslmode=require')
        valid = Flask(__name__); valid.config.update(base)
        validate_runtime_config(valid)
        invalid = [
            {'STORAGE_BACKEND': 'local'}, {'SUPABASE_SECRET_KEY': ''},
            {'SUPABASE_URL': 'http://testref.supabase.co'},
            {'SUPABASE_URL': 'https://testref.supabase.co.evil.invalid'},
            {'SUPABASE_STORAGE_BUCKET': '../public'},
            {'SQLALCHEMY_DATABASE_URI': base['SQLALCHEMY_DATABASE_URI'].replace('postgres.testref:', 'postgres.other:')},
            {'SQLALCHEMY_DATABASE_URI': base['SQLALCHEMY_DATABASE_URI'].replace('sslmode=require', 'sslmode=disable')},
            {'SQLALCHEMY_DATABASE_URI': base['SQLALCHEMY_DATABASE_URI'].replace(':5432/', ':6543/')},
            {'RATELIMIT_STORAGE_URI': 'memory://'}, {'CORS_ORIGINS': ['*']},
        ]
        for change in invalid:
            with self.subTest(change=next(iter(change))):
                candidate = Flask(__name__); candidate.config.update(base | change)
                with self.assertRaises(RuntimeError):
                    validate_runtime_config(candidate)
        with (patch('limits.storage.RedisStorage.check', return_value=True),
              patch('supabase_storage.check_private_bucket', side_effect=StorageUnavailable('public bucket')),
              self.assertRaises(StorageUnavailable)):
            create_app(type('ProductionCloudFixture', (), base))

    def setUp(self):
        self.temp = TemporaryDirectory(prefix='resqnet-cloud-test-')
        config = type('CloudTestConfig', (), dict(
            TESTING=True, APP_ENV='testing', DEBUG=False, SEED_DEMO_DATA=False,
            SECRET_KEY='synthetic-test-secret-at-least-32-characters',
            JWT_SECRET_KEY='synthetic-test-jwt-at-least-32-characters',
            SQLALCHEMY_DATABASE_URI='sqlite:///:memory:', SQLALCHEMY_TRACK_MODIFICATIONS=False,
            STORAGE_BACKEND='supabase', SUPABASE_URL='https://testref.supabase.co',
            SUPABASE_SECRET_KEY='sb_secret_'+'x'*32, SUPABASE_STORAGE_BUCKET='private-evidence',
            MAX_CONTENT_LENGTH=10*1024*1024, UPLOAD_FOLDER=self.temp.name,
            RATELIMIT_ENABLED=False, CORS_ORIGINS=[]))
        self.storage = FakeStorage()
        self.patch_open = patch('supabase_storage._open', side_effect=self.storage.open)
        self.patch_open.start()
        self.app = create_app(config)
        self.context = self.app.app_context(); self.context.push()
        self.client = self.app.test_client()
        self.ids = {}
        for role in ('reporter', 'volunteer', 'ngo', 'admin'):
            user = User(name='Fixture', email=role+'@test.invalid', phone='test',
                        password='unused', role=role)
            db.session.add(user); db.session.flush(); self.ids[role] = user.user_id
            if role == 'volunteer':
                db.session.add(Volunteer(user_id=user.user_id))
        db.session.commit()

    def tearDown(self):
        db.session.remove(); db.engine.dispose(); self.context.pop()
        self.patch_open.stop(); self.temp.cleanup()

    def headers(self, role):
        return {'Authorization': 'Bearer '+create_access_token(identity=str(self.ids[role]))}

    @staticmethod
    def image():
        data = io.BytesIO(); Image.new('RGB', (2, 2), 'green').save(data, format='PNG')
        return data.getvalue()

    def sos(self):
        return self.client.post('/help-request', headers=self.headers('reporter'), data={
            'name':'Citizen', 'contact':'test', 'request_type':'Rescue',
            'latitude':'10', 'longitude':'76', 'number_of_people':'1',
            'image':(io.BytesIO(self.image()), 'incident.png')})

    def test_private_sos_and_report_images_keep_role_checks_and_opaque_refs(self):
        check_private_bucket()
        self.storage.public = True
        with self.assertRaises(StorageUnavailable):
            check_private_bucket()
        self.storage.public = False
        sos = self.sos()
        self.assertEqual(sos.status_code, 201)
        self.assertEqual(sos.json['ai']['severity'], 'Severe Damage')
        req = HelpRequest.query.one()
        self.assertTrue(req.image_path.startswith('supabase://requests/'))
        self.assertNotIn('supabase://', str(sos.json))
        image_url = f'/help-request/{req.request_id}/image'
        for role, status in [(None,401), ('reporter',200), ('volunteer',403), ('ngo',403), ('admin',200)]:
            response = self.client.get(image_url, headers=self.headers(role) if role else {})
            self.assertEqual(response.status_code, status)
            if status == 200:
                self.assertEqual(response.data, self.image())
                self.assertEqual(response.headers['Cache-Control'], 'private, no-store')
        report = self.client.post('/report-disaster', headers=self.headers('reporter'), data={
            'disaster_type':'Flood','description':'Observation','latitude':'10','longitude':'76',
            'images':(io.BytesIO(self.image()), 'report.png')})
        self.assertEqual(report.status_code, 201)
        self.assertEqual(report.json['severity'], 'Severe Damage')
        row = DisasterReport.query.one()
        self.assertTrue(row.image_path.startswith('supabase://reports/'))
        self.assertEqual(self.client.get(f'/report/{row.report_id}/image', headers=self.headers('reporter')).status_code, 200)
        self.assertEqual(self.client.get(f'/report/{row.report_id}/image', headers=self.headers('volunteer')).status_code, 403)
        row.image_path = 'supabase://reports/../outside.png'; db.session.commit()
        before = len(self.storage.requests)
        self.assertEqual(self.client.get(f'/report/{row.report_id}/image', headers=self.headers('admin')).status_code, 404)
        self.assertEqual(len(self.storage.requests), before)
        self.assertFalse(list(Path(self.temp.name).rglob('*.png')))

    def test_proof_upload_approval_and_outage_keep_task_states_safe(self):
        sos = self.sos(); self.assertEqual(sos.status_code, 201)
        request_id = HelpRequest.query.one().request_id
        accepted = self.client.put('/volunteer/accept-task', json={'request_id': request_id},
                                   headers=self.headers('volunteer'))
        self.assertEqual(accepted.status_code, 200)
        task_id = ReliefTask.query.one().task_id
        with patch.object(db.session, 'commit', side_effect=SQLAlchemyError('synthetic')):
            failed = self.client.post(f'/volunteer/upload-proof/{task_id}', headers=self.headers('volunteer'),
                                      data={'proof_image':(io.BytesIO(self.image()), 'proof.png')})
        self.assertEqual(failed.status_code, 503)
        self.assertEqual(ReliefTask.query.one().status, 'Assigned')
        self.assertEqual(len(self.storage.objects), 1)  # The SOS image remains; the new proof was deleted.
        uploaded = self.client.post(f'/volunteer/upload-proof/{task_id}', headers=self.headers('volunteer'),
                                    data={'proof_image':(io.BytesIO(self.image()), 'proof.png')})
        self.assertEqual(uploaded.status_code, 200)
        self.assertTrue(ReliefTask.query.one().proof_image_path.startswith('supabase://task_proofs/'))
        proof = f'/volunteer/tasks/{task_id}/proof'
        for role, status in [(None,401), ('reporter',403), ('ngo',403), ('volunteer',200), ('admin',200)]:
            self.assertEqual(self.client.get(proof, headers=self.headers(role) if role else {}).status_code, status)
        self.storage.fail = True
        self.assertEqual(self.client.put(f'/admin/verify-task/{task_id}',json={'action':'Approve'},
                                         headers=self.headers('admin')).status_code, 503)
        self.assertEqual(ReliefTask.query.one().status, 'Proof Submitted')
        self.storage.fail = False
        self.assertEqual(self.client.put(f'/admin/verify-task/{task_id}',json={'action':'Approve'},
                                         headers=self.headers('admin')).status_code, 200)
        self.assertEqual(HelpRequest.query.one().status, 'Completed')

    def test_database_failure_deletes_new_cloud_object_and_storage_failure_writes_nothing(self):
        with patch.object(db.session, 'commit', side_effect=SQLAlchemyError('synthetic')):
            self.assertEqual(self.sos().status_code, 503)
        self.assertEqual(HelpRequest.query.count(), 0)
        self.assertEqual(self.storage.objects, {})
        self.storage.fail = True
        failed = self.sos()
        self.assertEqual(failed.status_code, 503)
        self.assertNotIn('private failure', str(failed.json))
        self.assertEqual(HelpRequest.query.count(), 0)

    def test_ambiguous_upstream_upload_is_compensated_without_database_write(self):
        self.storage.fail_after_post = True
        self.assertEqual(self.sos().status_code, 503)
        self.assertEqual(HelpRequest.query.count(), 0)
        self.assertEqual(self.storage.objects, {})
