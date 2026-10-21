"""Deployment/security regressions with temporary uploads and memory-only data."""
from contextlib import redirect_stdout
from datetime import datetime, timedelta, timezone
import io
import os
from pathlib import Path
import sys
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app import create_app
from extensions import db
from flask_jwt_extended import create_access_token
from models import User, WeatherAlert, PreparednessPing


class DeploymentSecurityTests(unittest.TestCase):
    def setUp(self):
        self.storage = TemporaryDirectory(prefix='resqnet-security-')
        self.config = dict(TESTING=True, DEBUG=False, APP_ENV='production', SEED_DEMO_DATA=False,
                           SECRET_KEY='isolated-session-secret-at-least-32-characters',
                           JWT_SECRET_KEY='isolated-jwt-secret-at-least-32-characters',
                           SQLALCHEMY_DATABASE_URI='sqlite:///:memory:', SQLALCHEMY_TRACK_MODIFICATIONS=False,
                           UPLOAD_FOLDER=self.storage.name, CORS_ORIGINS=['https://resqnet1-2026.netlify.app'])
        self.app = self.make_app()
        self.context = self.app.app_context(); self.context.push()
        self.client = self.app.test_client()
        self.users = {}
        for role in ['reporter', 'volunteer', 'ngo', 'admin']:
            user = User(name='Fixture', email=role+'@test.invalid', phone='test', password='unused', role=role)
            db.session.add(user); db.session.flush(); self.users[role] = user.user_id
        db.session.commit()

    def make_app(self, **overrides):
        with redirect_stdout(io.StringIO()):
            return create_app(type('SecurityConfig', (), self.config | overrides))

    def tearDown(self):
        db.session.remove(); db.engine.dispose(); self.context.pop(); self.storage.cleanup()

    def headers(self, role='admin'):
        return {'Authorization': 'Bearer '+create_access_token(identity=str(self.users[role]))}

    def test_production_rejects_missing_weak_secrets_debug_demo_and_wildcard_cors(self):
        for invalid in [{'JWT_SECRET_KEY':None}, {'JWT_SECRET_KEY':'your_jwt_secret'}, {'SECRET_KEY':None},
                        {'DEBUG':True}, {'SEED_DEMO_DATA':True}, {'ADMIN_SECRET_CODE':'weak-demo-code'},
                        {'CORS_ORIGINS':['*']}, {'CORS_ORIGINS':[]}]:
            with self.subTest(setting=next(iter(invalid))):
                with self.assertRaises((RuntimeError, ValueError)):
                    self.make_app(**invalid)

    def test_cors_allows_only_configured_frontend_and_preflight(self):
        origin = 'https://resqnet1-2026.netlify.app'
        allowed = self.client.options('/profile', headers={'Origin':origin,'Access-Control-Request-Method':'GET','Access-Control-Request-Headers':'Authorization'})
        self.assertEqual(allowed.headers.get('Access-Control-Allow-Origin'), origin)
        self.assertIsNone(self.client.get('/health',headers={'Origin':'https://untrusted.invalid'}).headers.get('Access-Control-Allow-Origin'))
        self.assertIsNone(self.client.get('/health',headers={'Origin':origin+'.untrusted.invalid'}).headers.get('Access-Control-Allow-Origin'))

    def test_private_responses_are_not_cacheable_and_upload_paths_are_not_public(self):
        result = self.client.get('/profile',headers=self.headers())
        self.assertEqual(result.status_code,200)
        self.assertIn('no-store',result.headers.get('Cache-Control',''))
        self.assertIn('no-store',self.client.post('/login',json={}).headers.get('Cache-Control',''))
        self.assertEqual(self.client.get('/uploads/task_proofs/private.png').status_code,404)
        self.assertEqual(self.client.get('/backend/resqnet.db').status_code,404)

    def test_seed_route_and_known_demo_account_are_unusable_in_production(self):
        result=self.client.post('/seed-demo-users',headers=self.headers())
        self.assertEqual(result.status_code,404)
        user=User(name='Legacy fixture',email='admin@resqnet.com',phone='test',password='unused',role='admin')
        db.session.add(user);db.session.commit()
        token=create_access_token(identity=str(user.user_id))
        self.assertEqual(self.client.get('/admin/users',headers={'Authorization':'Bearer '+token}).status_code,401)
        self.assertEqual(self.client.post('/login',json={'email':user.email,'password':'arbitrary-test-only'}).status_code,401)
        self.assertEqual(self.client.post('/register',json={'name':'Fixture','email':user.email,'phone':'test',
                         'password':'isolated-password','role':'volunteer'}).status_code,400)

    def test_weather_errors_never_expose_upstream_key_or_url(self):
        with patch.dict('os.environ',{'OPENWEATHER_API_KEY':'test-sensitive-weather-key'}), patch('routes.alerts.urllib.request.urlopen',side_effect=RuntimeError('https://weather.invalid/?appid=test-sensitive-weather-key')):
            for path,method in [('/weather/live','GET'),('/alerts/fetch','POST')]:
                response=self.client.open(path,method=method,headers=self.headers())
                self.assertEqual(response.status_code,502)
                self.assertNotIn('test-sensitive-weather-key',str(response.json))
                self.assertNotIn('https://weather.invalid',str(response.json))

    def test_notifications_hide_demo_expired_and_invalid_rows_without_repairing(self):
        for description,source,expiry in [('Demo','Demo seed data',None),('Expired','Manual',datetime.now(timezone.utc)-timedelta(hours=1)),('Current','Manual',None)]:
            alert=WeatherAlert('Storm',description,10,76,source=source,expires_at=expiry)
            db.session.add(alert);db.session.flush()
            db.session.add(PreparednessPing(alert_id=alert.alert_id,user_id=self.users['volunteer']))
        db.session.commit()
        response=self.client.get('/preparedness/my-pings',headers=self.headers('volunteer'))
        self.assertEqual(response.status_code,200)
        self.assertEqual([p['description'].split('. ',1)[-1] for p in response.json['pings']],['Current'])
        self.assertEqual(PreparednessPing.query.count(),3)

    def test_persistent_environment_secret_verifies_tokens_across_app_instances(self):
        from flask_jwt_extended import decode_token
        token=create_access_token(identity=str(self.users['volunteer']))
        second=self.make_app()
        with second.app_context():
            self.assertEqual(decode_token(token)['sub'],str(self.users['volunteer']))
            db.engine.dispose()

    def test_alert_validation_preserves_rows_and_expired_alert_cannot_notify(self):
        valid=dict(alert_type='Storm',severity='Watch',description='Fixture observation',
                   affected_lat=10,affected_lng=76,affected_radius_km=50)
        for invalid in [{'alert_type':'Fabricated'}, {'severity':'Severe'}, {'description':''},
                        {'affected_radius_km':-1}, {'affected_lat':100}]:
            response=self.client.post('/alerts',json=valid | invalid,headers=self.headers())
            self.assertEqual(response.status_code,400)
        self.assertEqual(WeatherAlert.query.count(),0)
        response=self.client.post('/alerts',json=valid,headers=self.headers())
        self.assertEqual(response.status_code,201)
        self.assertIn('not an official disaster warning',response.json['alert']['description'])
        alert=WeatherAlert.query.one()
        alert.expires_at=datetime.now(timezone.utc)-timedelta(hours=1)
        db.session.commit()
        self.assertEqual(self.client.put(f'/alerts/{alert.alert_id}/notify',headers=self.headers()).status_code,409)
        self.assertEqual(PreparednessPing.query.count(),0)

    def test_production_requires_durable_filesystem_paths(self):
        for overrides in [{'PERSISTENT_STORAGE_PATH':None},
                          {'PERSISTENT_STORAGE_PATH':self.storage.name,'UPLOAD_FOLDER':str(Path(self.storage.name).parent/'outside-private')},
                          {'PERSISTENT_STORAGE_PATH':self.storage.name}]:
            with self.assertRaises(RuntimeError):
                self.make_app(TESTING=False,**overrides)
        # Successful production startup uses only a brand-new database in this temporary root.
        with patch('limits.storage.RedisStorage.check',return_value=True):
            app=self.make_app(TESTING=False,PERSISTENT_STORAGE_PATH=self.storage.name,
                              RATELIMIT_STORAGE_URI='redis://127.0.0.1:6379/15',
                              SQLALCHEMY_DATABASE_URI='sqlite:///'+(Path(self.storage.name)/'isolated.db').as_posix())
        self.assertEqual(app.test_client().get('/health').status_code,200)
        with app.app_context():
            self.assertEqual(User.query.count(),0)
            db.session.remove();db.engine.dispose()

    def test_environment_wins_over_dotenv_and_render_forces_production_mode(self):
        import subprocess
        fixture=Path(self.storage.name)/'config_fixture'
        fixture.mkdir()
        (fixture/'config.py').write_text((Path(__file__).resolve().parents[1]/'config.py').read_text(),encoding='utf-8')
        (fixture/'.env').write_text('JWT_SECRET_KEY=dotenv-test-value\nAPP_ENV=development\n',encoding='utf-8')
        environment=os.environ.copy()
        environment.update(JWT_SECRET_KEY='external-test-value',RENDER='true')
        result=subprocess.run([sys.executable,'-c',"from config import Config; assert Config.JWT_SECRET_KEY=='external-test-value'; assert Config.APP_ENV=='production'"],cwd=fixture,env=environment,capture_output=True)
        self.assertEqual(result.returncode,0,'Environment precedence check failed')

    def test_demo_seed_refuses_to_reset_existing_records(self):
        from seed_demo import seed_demo_data
        before=User.query.count()
        with self.assertRaises(RuntimeError):
            seed_demo_data()
        self.app.config['APP_ENV']='development'
        with self.assertRaises(RuntimeError):
            seed_demo_data()
        self.assertEqual(User.query.count(),before)

    def test_report_uploads_validate_images_and_never_overwrite_same_client_filename(self):
        from PIL import Image
        def body():
            image=io.BytesIO();Image.new('RGB',(2,2),color='green').save(image,format='PNG');image.seek(0)
            return {'disaster_type':'Flood','description':'Fixture observation','latitude':'10','longitude':'76','images':(image,'same.png')}
        for role in ['reporter','volunteer']:
            self.assertEqual(self.client.post('/report-disaster',data=body(),headers=self.headers(role)).status_code,201)
        paths=list((Path(self.storage.name)/'reports').iterdir())
        self.assertEqual(len(paths),2)
        self.assertNotEqual(paths[0].name,paths[1].name)
        bad=body();bad['images']=(io.BytesIO(b'<script>invalid image</script>'),'same.png')
        self.assertEqual(self.client.post('/report-disaster',data=bad,headers=self.headers('reporter')).status_code,400)

    def test_unsupported_image_decoders_are_not_invoked_for_incidents_or_proofs(self):
        from PIL import XbmImagePlugin
        from werkzeug.datastructures import FileStorage
        from private_uploads import save_incident_image
        from sos_lifecycle import save_proof
        # A harmless header proves dispatch is restricted before parsing an unsupported format.
        header=b'#define demo_width 8\n#define demo_height 1\nstatic char demo_bits[] = {0};'
        def upload():
            return FileStorage(stream=io.BytesIO(header),filename='misleading.png')
        with patch.object(XbmImagePlugin.XbmImageFile,'_open',side_effect=AssertionError('Unsupported decoder invoked')) as decoder:
            self.assertIsNone(save_incident_image(upload(),'reports'))
            with self.assertRaises(ValueError):
                save_proof(upload())
            decoder.assert_not_called()

    def test_static_deployment_config_uses_free_cloud_backends(self):
        import tomllib
        import yaml  # Existing flasgger dependency; no extra package installation.
        root=Path(__file__).resolve().parents[2]
        netlify=tomllib.loads((root/'netlify.toml').read_text())
        self.assertEqual(netlify['build']['publish'],'dist')
        self.assertIn('build-netlify.cjs',netlify['build']['command'])
        render=yaml.safe_load((root/'render.yaml').read_text())['services'][0]
        self.assertEqual(render['rootDir'],'backend')
        self.assertIn('wsgi:application',render['startCommand'])
        self.assertIn('$PORT',render['startCommand'])
        variables={item['key']:item for item in render['envVars']}
        self.assertTrue(variables['JWT_SECRET_KEY']['generateValue'])
        self.assertTrue(variables['SECRET_KEY']['generateValue'])
        self.assertEqual(variables['APP_ENV']['value'],'production')
        self.assertEqual(variables['SEED_DEMO_DATA']['value'],'False')
        self.assertEqual(render['plan'],'free')
        self.assertNotIn('disk',render)
        self.assertEqual(variables['STORAGE_BACKEND']['value'],'supabase')
        for key in ('DATABASE_URL','SUPABASE_URL','SUPABASE_SECRET_KEY',
                    'SUPABASE_STORAGE_BUCKET','CORS_ORIGINS','RATELIMIT_STORAGE_URI'):
            self.assertTrue(variables[key]['sync'] is False)
