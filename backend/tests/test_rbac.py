"""RBAC regression checks; all accounts and records are memory-only."""
from datetime import timedelta
import bcrypt
from flask_jwt_extended import create_access_token
import test_map_provenance as map_tests
from extensions import db
from models import User, Volunteer, HelpRequest, ReliefResource


import unittest


class RBACTests(unittest.TestCase):
    tearDown = map_tests.MapProvenanceTests.tearDown
    def setUp(self):
        map_tests.MapProvenanceTests.setUp(self)
        self.accounts = {}
        self.tokens = {}
        password = bcrypt.hashpw(b'isolated-test-password', bcrypt.gensalt(rounds=4)).decode()
        for key, role in [('reporter', 'reporter'), ('other', 'reporter'),
                          ('volunteer', 'volunteer'), ('ngo', 'ngo'),
                          ('ngo2', 'ngo'), ('admin', 'admin')]:
            user = User(name='Test', email=key+'@test.invalid', phone='test', password=password, role=role)
            db.session.add(user)
            db.session.flush()
            if role == 'volunteer':
                db.session.add(Volunteer(user_id=user.user_id))
            self.accounts[key] = user
            self.tokens[key] = create_access_token(identity=str(user.user_id))
        self.sos = HelpRequest(user_id=self.accounts['reporter'].user_id, name='PRIVATE_NAME',
                               contact='PRIVATE_CONTACT', request_type='Rescue',
                               description='PRIVATE_DESCRIPTION', latitude=12.345678, longitude=76.543219)
        self.resource = ReliefResource(name='Test', category='Food', quantity=1, unit='packs',
                                       location='Test', added_by=self.accounts['ngo'].user_id)
        db.session.add_all([self.sos, self.resource]); db.session.commit()

    def headers(self, key):
        return {'Authorization': 'Bearer '+self.tokens[key]} if key else {}

    def test_ngo_resources_are_owner_scoped(self):
        result = self.client.get('/ngo/resources', headers=self.headers('ngo2'))
        self.assertNotIn(self.resource.resource_id, [r['resource_id'] for r in result.json['resources']])
        result = self.client.put('/ngo/allocate', headers=self.headers('ngo2'),
                                 json={'resource_id': self.resource.resource_id, 'request_id': self.sos.request_id})
        self.assertEqual(result.status_code, 404)
        self.assertIsNone(db.session.get(ReliefResource, self.resource.resource_id).allocated_to)
        own = self.client.put('/ngo/allocate', headers=self.headers('ngo'),
                              json={'resource_id': self.resource.resource_id, 'request_id': self.sos.request_id})
        self.assertEqual(own.status_code, 200)
        self.assertNotIn('contact', own.json['request'])
        self.assertEqual(self.client.put('/ngo/allocate', headers=self.headers('ngo'),
                         json={'resource_id': self.resource.resource_id, 'request_id': self.sos.request_id}).status_code, 409)

    def test_resource_creator_cannot_be_impersonated(self):
        response = self.client.post('/ngo/resources', headers=self.headers('ngo2'), json={
            'name': 'Supplies', 'quantity': 1, 'added_by': self.accounts['ngo'].user_id})
        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.json['resource']['added_by'], self.accounts['ngo2'].user_id)

    def test_public_map_never_exposes_private_fields(self):
        result = self.client.get('/map/data').json
        self.assertEqual(result['requests'], [])
        self.assertEqual(result['reports'], [])
        self.assertEqual(result['volunteers'], [])
        shared = self.client.get('/map/data', headers=self.headers('volunteer')).json
        record = next(r for r in shared['requests'] if r['request_id'] == self.sos.request_id)
        for key in ['name', 'contact', 'description', 'user_id', 'image_path']:
            self.assertNotIn(key, record)
        self.assertNotEqual(record['latitude'], float(self.sos.latitude))
        for vol in shared['volunteers']:
            self.assertNotIn('user_name', vol)
            self.assertNotIn('user_id', vol)

    def test_reporter_report_ownership_and_coordinator_redaction(self):
        from models import DisasterReport
        report = DisasterReport(user_id=self.accounts['reporter'].user_id, disaster_type='Flood',
                                description='PRIVATE_DESCRIPTION', latitude=12.345678, longitude=76.543219)
        db.session.add(report); db.session.commit()
        foreign = self.client.get('/reports', headers=self.headers('other')).json['reports']
        self.assertNotIn(report.report_id, [r['report_id'] for r in foreign])
        self.assertEqual(self.client.get(f'/report/{report.report_id}', headers=self.headers('other')).status_code, 403)
        preview = self.client.get(f'/report/{report.report_id}', headers=self.headers('volunteer')).json['report']
        self.assertNotIn('description', preview)
        self.assertNotIn('user_name', preview)
        self.assertNotEqual(preview['latitude'], float(report.latitude))

    def test_pending_sos_preview_and_cross_account_access(self):
        self.assertEqual(self.client.get(f'/help-request/{self.sos.request_id}', headers=self.headers('other')).status_code, 403)
        preview = self.client.get('/help-requests', headers=self.headers('volunteer')).json
        item = next(r for r in preview['requests'] if r['request_id'] == self.sos.request_id)
        self.assertNotIn('contact', item)
        accepted = self.client.put('/volunteer/accept-task', headers=self.headers('volunteer'), json={'request_id': self.sos.request_id})
        self.assertEqual(accepted.status_code, 200)
        self.assertEqual(self.client.get(f'/help-request/{self.sos.request_id}', headers=self.headers('volunteer')).json['request']['contact'], 'PRIVATE_CONTACT')

    def test_ngo_cannot_progress_volunteer_task(self):
        self.client.put('/volunteer/accept-task', headers=self.headers('volunteer'), json={'request_id': self.sos.request_id})
        result = self.client.put('/help-request/status', headers=self.headers('ngo'), json={'request_id': self.sos.request_id, 'status': 'En Route'})
        self.assertEqual(result.status_code, 403)

    def test_alert_responses_admin_only(self):
        for role in ['reporter', 'volunteer', 'ngo']:
            self.assertEqual(self.client.get('/alerts/1/responses', headers=self.headers(role)).status_code, 403)

    def test_preparedness_ownership_and_duplicate_response(self):
        from models import PreparednessPing, WeatherAlert
        alert = WeatherAlert('Storm', 'Current fixture advisory', 10, 76, source='Manual')
        db.session.add(alert); db.session.flush()
        ping = PreparednessPing(alert_id=alert.alert_id,
                                user_id=self.accounts['volunteer'].user_id)
        db.session.add(ping); db.session.commit()
        self.assertEqual(self.client.put(f'/preparedness/ping/{ping.ping_id}',
                         headers=self.headers('ngo'), json={'status': 'Acknowledged'}).status_code, 403)
        self.assertEqual(self.client.put(f'/preparedness/ping/{ping.ping_id}',
                         headers=self.headers('volunteer'), json={'status': 'Acknowledged'}).status_code, 200)
        self.assertEqual(self.client.put(f'/preparedness/ping/{ping.ping_id}',
                         headers=self.headers('volunteer'), json={'status': 'Unavailable'}).status_code, 409)

    def test_invalid_legacy_ping_does_not_break_authorized_reads_or_mutate_data(self):
        from models import PreparednessPing, WeatherAlert
        from sqlalchemy import text
        alert = WeatherAlert('Storm', 'Current fixture advisory', 10, 76, source='Manual')
        db.session.add(alert); db.session.flush()
        ping = PreparednessPing(alert_id=alert.alert_id,
                                user_id=self.accounts['volunteer'].user_id)
        db.session.add(ping); db.session.commit()
        ping_id = ping.ping_id
        db.session.execute(text("UPDATE preparedness_pings SET status='Pending' WHERE ping_id=:id"), {'id': ping_id})
        db.session.commit()
        self.assertEqual(self.client.get('/preparedness/my-pings', headers=self.headers('volunteer')).json['pings'], [])
        self.assertEqual(self.client.get('/alerts/1/responses', headers=self.headers('admin')).status_code, 200)
        self.assertEqual(self.client.put(f'/preparedness/ping/{ping_id}', headers=self.headers('volunteer'), json={'status': 'Acknowledged'}).status_code, 404)
        self.assertEqual(db.session.execute(text('SELECT status FROM preparedness_pings WHERE ping_id=:id'), {'id': ping_id}).scalar(), 'Pending')

    def test_login_profile_and_non_authoritative_claims(self):
        for role in ['reporter', 'volunteer', 'ngo', 'admin']:
            response = self.client.post('/login', json={'email': role+'@test.invalid', 'password': 'isolated-test-password', 'role': 'admin'})
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.json['user']['role'], role)
            profile = self.client.get('/profile', headers={'Authorization': 'Bearer '+response.json['token']})
            self.assertEqual(profile.json['user']['role'], role)
        token = create_access_token(identity=str(self.accounts['reporter'].user_id), additional_claims={'role': 'admin'})
        self.assertEqual(self.client.get('/admin/users', headers={'Authorization': 'Bearer '+token}).status_code, 403)

    def test_missing_invalid_expired_and_deleted_identity(self):
        for token in [None, 'invalid', create_access_token(identity=str(self.accounts['admin'].user_id), expires_delta=timedelta(seconds=-1)), create_access_token(identity='invalid'), create_access_token(identity='999999')]:
            headers = {'Authorization': 'Bearer '+token} if token else {}
            self.assertIn(self.client.get('/profile', headers=headers).status_code, [401, 422])

    def test_public_endpoint_matrix(self):
        from unittest.mock import patch
        import os
        for role in [None, 'reporter', 'volunteer', 'ngo', 'admin']:
            for path in ['/health', '/public/stats', '/map/data', '/map/risk-zones', '/alerts', '/ngo/locations']:
                with self.subTest(role=role, path=path):
                    self.assertEqual(self.client.get(path, headers=self.headers(role)).status_code, 200)
            self.assertEqual(self.client.post('/contact', json={}, headers=self.headers(role)).status_code, 400)
            with patch.dict(os.environ, {'OPENWEATHER_API_KEY': ''}):
                self.assertEqual(self.client.get('/weather/live', headers=self.headers(role)).status_code, 503)
        self.assertEqual(self.client.get('/map/data', headers={'Authorization': 'Bearer invalid'}).status_code, 422)

    def test_admin_registration_requires_configured_secret_and_seed_is_protected(self):
        self.assertEqual(self.client.post('/seed-demo-users').status_code, 401)
        with self.app.app_context():
            self.app.config['ADMIN_SECRET_CODE'] = None
            response = self.client.post('/register', json={'name': 'Test', 'email': 'new@test.invalid', 'phone': 'test', 'password': 'test-password', 'role': 'admin', 'admin_secret_code': ''})
            self.assertEqual(response.status_code, 403)

    def test_registration_all_roles_and_invalid_role(self):
        self.app.config['ADMIN_SECRET_CODE'] = 'isolated-registration-code'
        for role in ['reporter', 'volunteer', 'ngo', 'admin']:
            response = self.client.post('/register', json={
                'name': 'Test', 'email': 'new-'+role+'@test.invalid', 'phone': 'test',
                'password': 'isolated-password', 'role': role,
                'admin_secret_code': 'isolated-registration-code'})
            self.assertEqual(response.status_code, 201)
            self.assertEqual(response.json['user']['role'], role)
        self.assertEqual(self.client.post('/register', json={'name': 'Test', 'email': 'invalid@test.invalid', 'phone': 'test', 'password': 'test-password', 'role': 'superadmin'}).status_code, 400)

    def test_endpoint_role_matrix(self):
        """Allowed roles reach validation; denied roles never reach handlers."""
        all_roles = {'reporter', 'volunteer', 'ngo', 'admin'}
        cases = [
            ('GET', '/profile', all_roles),
            ('GET', '/help-requests', all_roles),
            ('GET', '/help-request/999999', all_roles),
            ('POST', '/help-request', {'reporter'}),
            ('GET', '/reports', all_roles), ('GET', '/report/999999', all_roles),
            ('POST', '/report-disaster', all_roles),
            ('PUT', '/help-request/status', {'volunteer', 'admin'}),
            ('GET', '/volunteer/tasks', {'volunteer'}),
            ('PUT', '/volunteer/accept-task', {'volunteer'}),
            ('PUT', '/volunteer/update-status', {'volunteer'}),
            ('PUT', '/volunteer/update-location', {'volunteer'}),
            ('POST', '/volunteer/upload-proof/999999', {'volunteer'}),
            ('GET', '/volunteer/tasks/999999/proof', {'volunteer', 'admin'}),
            ('GET', '/ngo/dashboard', {'ngo'}), ('GET', '/ngo/resources', {'ngo'}),
            ('POST', '/ngo/resources', {'ngo'}), ('GET', '/ngo/requests', {'ngo'}),
            ('PUT', '/ngo/allocate', {'ngo'}),
            ('GET', '/preparedness/my-pings', {'volunteer', 'ngo'}),
            ('PUT', '/preparedness/ping/999999', {'volunteer', 'ngo'}),
            ('GET', '/preparedness/summary', {'admin'}),
            ('POST', '/alerts', {'admin'}), ('POST', '/alerts/fetch', {'admin'}),
            ('PUT', '/alerts/999999/notify', {'admin'}),
            ('GET', '/alerts/999999/responses', {'admin'}),
            ('GET', '/admin/dashboard', {'admin'}), ('GET', '/admin/analytics', {'admin'}),
            ('GET', '/admin/reports', {'admin'}), ('GET', '/admin/requests', {'admin'}),
            ('GET', '/admin/volunteers', {'admin'}), ('GET', '/admin/users', {'admin'}),
            ('GET', '/admin/pending-verifications', {'admin'}),
            ('PUT', '/admin/verify-task/999999', {'admin'}),
            ('PUT', '/admin/report/999999/override', {'admin'}),
            ('GET', '/admin/contact-messages', {'admin'}),
            ('PUT', '/admin/contact-messages/999999/read', {'admin'}),
            ('DELETE', '/admin/contact-messages/999999', {'admin'}),
            ('POST', '/seed-demo-users', {'admin'}),
        ]
        # Avoid upstream weather calls even when testing admin access.
        from unittest.mock import patch
        with patch('routes.alerts.OWM_KEY', ''):
            for method, path, allowed in cases:
                for role in [None, *sorted(all_roles)]:
                    with self.subTest(method=method, path=path, role=role):
                        response = self.client.open(path, method=method, json={}, headers=self.headers(role))
                        if role is None:
                            self.assertEqual(response.status_code, 401)
                        elif role not in allowed:
                            self.assertEqual(response.status_code, 403)
                        else:
                            self.assertNotEqual(response.status_code, 401)
                            if path != '/alerts/fetch':  # Missing weather key returns existing 500.
                                self.assertNotEqual(response.status_code, 500)
                            if path != '/seed-demo-users':
                                self.assertNotEqual(response.status_code, 403)
