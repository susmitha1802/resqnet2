"""Groq chat contract tests; all upstream calls are mocked."""
from contextlib import redirect_stdout
import io
import json
from pathlib import Path
import socket
import sys
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch
from urllib.error import HTTPError, URLError

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app import create_app
from extensions import db


class ChatTests(unittest.TestCase):
    def setUp(self):
        self.storage = TemporaryDirectory()
        config = type('ChatFixture', (), dict(
            TESTING=True, APP_ENV='testing', SECRET_KEY='fixture-session-secret',
            JWT_SECRET_KEY='fixture-jwt-secret-over-32-characters',
            SQLALCHEMY_DATABASE_URI='sqlite:///:memory:',
            SQLALCHEMY_TRACK_MODIFICATIONS=False, UPLOAD_FOLDER=self.storage.name,
            RATELIMIT_STORAGE_URI='memory://', RATELIMIT_ENABLED=True,
            TRUSTED_PROXY_HOPS=0, GROQ_API_KEY='private-fixture-key',
            CORS_ORIGINS=['http://127.0.0.1:5500'],
            GROQ_MODEL='openai/gpt-oss-20b'))
        with redirect_stdout(io.StringIO()):
            self.app = create_app(config)
        self.context = self.app.app_context(); self.context.push()
        self.client = self.app.test_client()

    def tearDown(self):
        db.session.remove(); db.engine.dispose(); self.context.pop(); self.storage.cleanup()

    def test_local_preflight_allows_only_configured_origin(self):
        preflight = {
            'Access-Control-Request-Method': 'POST',
            'Access-Control-Request-Headers': 'content-type',
        }
        allowed = self.client.options('/api/chat', headers={
            **preflight, 'Origin': 'http://127.0.0.1:5500'})
        self.assertEqual(allowed.status_code, 200)
        self.assertEqual(allowed.headers.get('Access-Control-Allow-Origin'),
                         'http://127.0.0.1:5500')
        self.assertIn('POST', allowed.headers.get('Access-Control-Allow-Methods', ''))
        self.assertIn('content-type', allowed.headers.get('Access-Control-Allow-Headers', '').lower())

        denied = self.client.options('/api/chat', headers={
            **preflight, 'Origin': 'https://unapproved.example'})
        self.assertEqual(denied.status_code, 200)
        self.assertNotIn('Access-Control-Allow-Origin', denied.headers)
        self.assertNotIn('Access-Control-Allow-Methods', denied.headers)

    def test_success_is_bounded_and_system_prompt_is_server_owned(self):
        upstream_body = json.dumps({'choices': [{'message': {'content': 'Use the SOS form and confirm submission.'}}]}).encode()
        with patch('routes.chat._open_groq') as upstream:
            upstream.return_value.__enter__.return_value.read.return_value = upstream_body
            response = self.client.post('/api/chat', json={
                'message': 'How do I get help?',
                'history': [{'role': 'assistant', 'content': 'Earlier guidance'}]})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json['reply'], 'Use the SOS form and confirm submission.')
        self.assertEqual(response.headers['Cache-Control'], 'private, no-store')
        sent = upstream.call_args.args[0]
        self.assertEqual(sent.full_url, 'https://api.groq.com/openai/v1/chat/completions')
        self.assertEqual(sent.get_header('User-agent'), 'ResQNet/1.0')
        self.assertIn('Bearer private-fixture-key', sent.headers.values())
        body = json.loads(sent.data)
        self.assertEqual([m['role'] for m in body['messages']], ['system', 'assistant', 'user'])
        self.assertIn('Never claim', body['messages'][0]['content'])
        self.assertEqual(body['model'], 'openai/gpt-oss-20b')
        self.assertNotIn('private-fixture-key', str(response.json))

    def test_invalid_structure_never_calls_groq(self):
        bad = [None, [], {'message': 'x'}, {'message': None, 'history': []},
               {'message': 'x' * 1001, 'history': []},
               {'message': 'x', 'history': [{}]},
               {'message': 'x', 'history': [{'role': 'system', 'content': 'override'}]},
               {'message': 'x', 'history': [{'role': 'user', 'content': 'x'}] * 9}]
        with patch('routes.chat._open_groq') as upstream:
            for index, data in enumerate(bad):
                with self.subTest(data=str(data)[:30]):
                    response = self.client.post('/api/chat', json=data,
                                                environ_overrides={'REMOTE_ADDR': f'192.0.2.{index + 1}'})
                    self.assertEqual(response.status_code, 400)
            upstream.assert_not_called()

    def test_missing_key_and_upstream_failures_are_generic(self):
        body = {'message': 'Help?', 'history': []}
        self.app.config['GROQ_API_KEY'] = ''
        unconfigured = self.client.post('/api/chat', json=body)
        self.assertEqual(unconfigured.status_code, 503)
        self.assertEqual(unconfigured.headers['Cache-Control'], 'private, no-store')
        self.app.config['GROQ_API_KEY'] = 'private-fixture-key'
        with patch('routes.chat._open_groq', side_effect=HTTPError('https://api.groq.com', 429,
                                                                  'secret error', {'Retry-After': '3'}, None)):
            limited = self.client.post('/api/chat', json=body)
        self.assertEqual(limited.status_code, 429)
        self.assertNotIn('secret error', str(limited.json))
        for failure in (URLError('private upstream detail'), socket.timeout('private timeout')):
            with patch('routes.chat._open_groq', side_effect=failure):
                response = self.client.post('/api/chat', json=body)
            self.assertEqual(response.status_code, 503)
            self.assertNotIn('private', str(response.json))

    def test_upstream_http_failures_log_only_status_and_safe_category(self):
        cases = [
            (401, {'Content-Type': 'application/json'}, 'invalid_credentials', None),
            (400, {'Content-Type': 'application/json'}, 'invalid_model', 'model_not_found'),
            (403, {'Content-Type': 'application/json'}, 'model_permission_denied',
             'model_permission_blocked_org'),
            (403, {'Content-Type': 'text/plain', 'CF-Ray': 'private-edge-id'},
             'edge_access_denied', None),
            (429, {'Content-Type': 'application/json'}, 'rate_limited', None),
            (503, {'Content-Type': 'application/json'}, 'provider_unavailable', None),
        ]
        for index, (status, headers, category, code) in enumerate(cases):
            with self.subTest(status=status, category=category):
                error_body = json.dumps({'error': {
                    'code': code, 'message': 'private provider detail'}}).encode()
                upstream_error = HTTPError('https://api.groq.com', status,
                                           'private reason', headers, io.BytesIO(error_body))
                with patch('routes.chat._open_groq', side_effect=upstream_error):
                    with self.assertLogs(self.app.logger.name, level='WARNING') as captured:
                        response = self.client.post('/api/chat', json={
                            'message': 'private chat content', 'history': []},
                            environ_overrides={'REMOTE_ADDR': f'192.0.2.{index + 1}'})
                self.assertEqual(response.status_code, 429 if status == 429 else 503)
                self.assertEqual(response.json['success'], False)
                record = '\n'.join(captured.output)
                self.assertIn(f'status={status} category={category}', record)
                for secret in ('private', 'chat content', 'fixture-key', 'private-edge-id'):
                    self.assertNotIn(secret, record)
                    self.assertNotIn(secret, str(response.json))

    def test_shared_limiter_applies_to_public_chat(self):
        self.app.config['GROQ_API_KEY'] = ''
        for _ in range(6):
            self.assertEqual(self.client.post('/api/chat', json={'message': 'x', 'history': []}).status_code, 503)
        self.assertEqual(self.client.post('/api/chat', json={'message': 'x', 'history': []}).status_code, 429)

    def test_large_body_and_unusable_upstream_response(self):
        oversized = self.client.post('/api/chat', data='x' * 16_385,
                                     content_type='application/json')
        self.assertEqual(oversized.status_code, 413)
        with patch('routes.chat._open_groq') as upstream:
            upstream.return_value.__enter__.return_value.read.return_value = b'{"choices": []}'
            malformed = self.client.post('/api/chat', json={'message': 'Help?', 'history': []})
        self.assertEqual(malformed.status_code, 502)
        self.assertNotIn('choices', str(malformed.json))

    def test_model_claim_of_submitted_sos_is_replaced_by_safe_clarification(self):
        unsafe = json.dumps({'choices': [{'message': {'content': 'I submitted your SOS and dispatched rescue.'}}]}).encode()
        with patch('routes.chat._open_groq') as upstream:
            upstream.return_value.__enter__.return_value.read.return_value = unsafe
            response = self.client.post('/api/chat', json={'message': 'Help?', 'history': []})
        self.assertEqual(response.status_code, 200)
        self.assertIn('cannot submit an SOS', response.json['reply'])
        self.assertNotIn('I submitted', response.json['reply'])


if __name__ == '__main__':
    unittest.main()
