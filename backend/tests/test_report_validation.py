"""Report writes use isolated memory data and temporary uploads, never real records."""
import io
from pathlib import Path
import sys
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from PIL import Image
from sqlalchemy.exc import SQLAlchemyError

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app import create_app
from extensions import db
from flask_jwt_extended import create_access_token
from models import DisasterReport, User


class ReportValidationTests(unittest.TestCase):
    def setUp(self):
        self.storage = TemporaryDirectory(prefix='resqnet-report-validation-')
        config = type('ReportTestConfig', (), dict(
            TESTING=True, PROPAGATE_EXCEPTIONS=False, APP_ENV='testing', DEBUG=False,
            SEED_DEMO_DATA=False, RATELIMIT_ENABLED=False,
            SECRET_KEY='isolated-report-test-session-secret',
            JWT_SECRET_KEY='isolated-report-test-signing-secret',
            SQLALCHEMY_DATABASE_URI='sqlite:///:memory:',
            SQLALCHEMY_TRACK_MODIFICATIONS=False,
            UPLOAD_FOLDER=self.storage.name, CORS_ORIGINS=[]))
        self.app = create_app(config)
        self.log_patch = patch.object(self.app.logger, 'disabled', True)
        self.log_patch.start()
        self.context = self.app.app_context()
        self.context.push()
        self.client = self.app.test_client()
        self.users = {}
        for role in ['reporter', 'volunteer', 'ngo', 'admin']:
            user = User(name='Fixture', email=role+'@test.invalid', phone='test',
                        password='unused', role=role)
            db.session.add(user)
            db.session.flush()
            self.users[role] = user.user_id
        folder = Path(self.storage.name) / 'reports'
        folder.mkdir()
        self.original_image = folder / 'existing.png'
        self.original_image.write_bytes(self.image().getvalue())
        report = DisasterReport(user_id=self.users['reporter'], disaster_type='Flood',
                                description='Existing fixture observation', latitude=10, longitude=76,
                                image_path=str(self.original_image), predicted_disaster_type='Flood')
        db.session.add(report)
        db.session.commit()
        self.report_id = report.report_id
        self.original = report.to_dict()

    def tearDown(self):
        db.session.remove()
        db.engine.dispose()
        self.context.pop()
        self.log_patch.stop()
        self.storage.cleanup()

    @staticmethod
    def image():
        data = io.BytesIO()
        Image.new('RGB', (2, 2), 'white').save(data, format='PNG')
        data.seek(0)
        return data

    def headers(self, role='admin'):
        return {'Authorization': 'Bearer '+create_access_token(identity=str(self.users[role]))}

    def body(self, disaster_type='Flood', **overrides):
        return dict(disaster_type=disaster_type, description='New fixture observation',
                    latitude='12.97', longitude='77.59',
                    images=(self.image(), 'new.png')) | overrides

    def create(self, **overrides):
        return self.client.post('/report-disaster', headers=self.headers('reporter'),
                                data=self.body(**overrides))

    def assert_unchanged_and_readable(self):
        db.session.expire_all()
        self.assertEqual(DisasterReport.query.count(), 1)
        self.assertEqual(db.session.get(DisasterReport, self.report_id).to_dict(), self.original)
        self.assertEqual(set(Path(self.storage.name).rglob('*.png')), {self.original_image})
        self.assertEqual(self.original_image.read_bytes(), self.image().getvalue())
        for path in ['/reports', '/map/data', '/admin/reports']:
            with self.subTest(feed=path):
                result = self.client.get(path, headers=self.headers())
                self.assertEqual(result.status_code, 200)
                self.assertTrue(result.json['success'])
                self.assertEqual([r['report_id'] for r in result.json['reports']], [self.report_id])

    def test_creation_rejects_unknown_empty_and_missing_types_before_upload(self):
        for value in ['Unknown', '', '   ', 'null', '42', '["Flood"]', '{"type":"Flood"}']:
            with self.subTest(value=value):
                result = self.create(disaster_type=value)
                self.assertEqual(result.status_code, 400)
                self.assertFalse(result.json['success'])
                self.assert_unchanged_and_readable()
        data = self.body()
        del data['disaster_type']
        self.assertEqual(self.client.post('/report-disaster', data=data,
                         headers=self.headers('reporter')).status_code, 400)
        self.assert_unchanged_and_readable()

    def test_creation_rejects_null_and_wrong_json_types(self):
        # Creation's existing contract is multipart form data, not JSON input.
        for value in [None, True, 42, 1.5, ['Flood'], {'type': 'Flood'}]:
            with self.subTest(value=value):
                result = self.client.post('/report-disaster', headers=self.headers('reporter'),
                    json={'disaster_type': value, 'description': 'Fixture', 'latitude': 10, 'longitude': 76})
                self.assertEqual(result.status_code, 400)
                self.assert_unchanged_and_readable()

    def test_override_rejects_invalid_types_without_changing_original(self):
        for value in ['Unknown', '', '   ', None, True, 42, 1.5, ['Flood'], {'type': 'Flood'}]:
            with self.subTest(value=value):
                result = self.client.put(f'/admin/report/{self.report_id}/override',
                    headers=self.headers(), json={'disaster_type': value})
                self.assertEqual(result.status_code, 400)
                self.assertFalse(result.json['success'])
                self.assert_unchanged_and_readable()

    def test_override_rejects_missing_type_and_non_object_json(self):
        for body in [{}, None, True, 42, 'Flood', ['Flood']]:
            with self.subTest(body=body):
                result = self.client.put(f'/admin/report/{self.report_id}/override',
                                         headers=self.headers(), json=body)
                self.assertEqual(result.status_code, 400)
                self.assert_unchanged_and_readable()

    def test_valid_creation_preserves_all_roles_and_supported_enum_values(self):
        cases = [('reporter', value) for value in ['Flood', 'Cyclone', 'Earthquake', 'Landslide', 'Fire']]
        cases += [(role, 'Flood') for role in ['volunteer', 'ngo', 'admin']]
        for role, value in cases:
            with self.subTest(role=role, value=value):
                result = self.client.post('/report-disaster', headers=self.headers(role),
                                           data=self.body(disaster_type=' '+value+' '))
                self.assertEqual(result.status_code, 201)
                self.assertEqual(result.json['report']['disaster_type'], value)
                self.assertEqual(result.json['report']['predicted_disaster_type'], value)
                self.assertIsNone(result.json['report']['prediction_confidence'])
                self.assertIsNone(result.json['ai_note'])
                self.assertNotIn('image_path', result.json['report'])
                saved = db.session.get(DisasterReport, result.json['report']['report_id'])
                self.assertTrue(Path(saved.image_path).is_file())
                self.assertEqual(saved.user_id, self.users[role])

    def test_valid_creation_without_image_and_missing_override_record(self):
        body = self.body()
        del body['images']
        result = self.client.post('/report-disaster', headers=self.headers('reporter'), data=body)
        self.assertEqual(result.status_code, 201)
        self.assertIsNone(db.session.get(DisasterReport, result.json['report']['report_id']).image_path)
        self.assertEqual(self.client.put('/admin/report/9999/override', headers=self.headers(),
                                         json={'disaster_type': 'Fire'}).status_code, 404)

    def test_valid_override_only_changes_reported_type(self):
        for value in ['Flood', 'Cyclone', 'Earthquake', 'Landslide', 'Fire']:
            result = self.client.put(f'/admin/report/{self.report_id}/override',
                                     headers=self.headers(), json={'disaster_type': value})
            self.assertEqual(result.status_code, 200)
            db.session.expire_all()
            self.assertEqual(db.session.get(DisasterReport, self.report_id).to_dict(),
                             self.original | {'disaster_type': value, 'ai_mismatch': value != 'Flood'})

    def test_authorization_is_preserved(self):
        self.assertEqual(self.client.post('/report-disaster', data=self.body()).status_code, 401)
        self.assertEqual(self.client.put(f'/admin/report/{self.report_id}/override',
                                         json={'disaster_type': 'Fire'}).status_code, 401)
        for role in ['reporter', 'volunteer', 'ngo']:
            self.assertEqual(self.client.put(f'/admin/report/{self.report_id}/override',
                headers=self.headers(role), json={'disaster_type': 'Fire'}).status_code, 403)
        self.assert_unchanged_and_readable()

    def test_create_database_failures_roll_back_and_remove_only_new_upload(self):
        for operation in ['flush', 'commit']:
            with self.subTest(operation=operation), patch.object(db.session, operation,
                    side_effect=SQLAlchemyError('private database detail')), patch.object(
                    db.session, 'rollback', wraps=db.session.rollback) as rollback:
                result = self.create()
                self.assertEqual(result.status_code, 503)
                self.assertFalse(result.json['success'])
                self.assertNotIn('private database detail', str(result.json))
                rollback.assert_called_once()
            self.assert_unchanged_and_readable()

    def test_override_database_failures_roll_back_original(self):
        for operation in ['flush', 'commit']:
            with self.subTest(operation=operation), patch.object(db.session, operation,
                    side_effect=SQLAlchemyError('private database detail')), patch.object(
                    db.session, 'rollback', wraps=db.session.rollback) as rollback:
                result = self.client.put(f'/admin/report/{self.report_id}/override',
                                         headers=self.headers(), json={'disaster_type': 'Fire'})
                self.assertEqual(result.status_code, 503)
                self.assertNotIn('private database detail', str(result.json))
                rollback.assert_called_once()
            self.assert_unchanged_and_readable()

    def test_invalid_coordinate_conversion_does_not_save_an_upload(self):
        result = self.create(latitude='not-a-coordinate')
        self.assertEqual(result.status_code, 400)
        self.assert_unchanged_and_readable()

    def test_partial_image_write_failure_is_cleaned_up(self):
        def fail_after_write(upload, destination, *args, **kwargs):
            Path(destination).write_bytes(b'partial fixture image')
            raise OSError('private filesystem detail')
        with patch('werkzeug.datastructures.FileStorage.save', fail_after_write):
            result = self.create()
        self.assertEqual(result.status_code, 503)
        self.assertNotIn('private filesystem detail', str(result.json))
        self.assert_unchanged_and_readable()


if __name__ == '__main__':
    unittest.main()
