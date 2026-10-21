"""Bounded public guidance chat. No database lookup or workflow mutation."""
import json
import re
import socket
from urllib.error import HTTPError, URLError
from urllib.request import HTTPRedirectHandler, Request, build_opener

from flask import Blueprint, current_app, jsonify, request

chat_bp = Blueprint('chat', __name__)
GROQ_ENDPOINT = 'https://api.groq.com/openai/v1/chat/completions'
MAX_BODY = 16_384
MAX_HISTORY = 8
MAX_MESSAGE = 1_000
SYSTEM_PROMPT = (
    'You are ResQNet guidance for a community disaster preparedness and emergency '
    'assistance website. Citizens can register, submit an SOS or community disaster '
    'report, and track their own requests. Volunteers can accept eligible SOS tasks, '
    'update progress and submit proof; an admin reviews proof before completion. '
    'NGOs can manage resources. The map includes role-limited incident information. '
    'Flood Intelligence shows historical, unvalidated candidate flooding and potential '
    'exposure, not current or confirmed conditions. You have no tools, account access, '
    'live weather, official alerts, incident status, or ability to submit SOS, dispatch '
    'rescue, contact responders, or verify any event. Never claim any such action '
    'occurred. Do not invent emergency numbers, forecasts, flood predictions, or '
    'incident facts. For immediate danger, advise contacting local emergency services '
    'and using the ResQNet SOS form, then checking its actual confirmation. Keep answers '
    'brief and practical; say when information is unavailable or unverified.'
)
ACTION_CLAIM = re.compile(
    r'\b(?:submitted|filed|created|sent|dispatched|assigned|accepted|completed|contacted|alerted)\b'
    r'.{0,80}\b(?:SOS|request|rescue|volunteer|help|emergency services)\b|'
    r'\b(?:SOS|request|rescue|volunteer|help|emergency services)\b'
    r'.{0,80}\b(?:submitted|filed|created|sent|dispatched|assigned|accepted|completed|contacted|alerted)\b',
    re.IGNORECASE | re.DOTALL)
SAFE_ACTION_REPLY = (
    'This chat cannot submit an SOS, dispatch rescue, or confirm a request status. '
    'For immediate danger, contact local emergency services. Use the ResQNet SOS '
    'form and check its own confirmation and tracking page.'
)


class _NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def _open_groq(upstream):
    # Do not forward the server-only Authorization header to a redirect target.
    return build_opener(_NoRedirect()).open(upstream, timeout=12)


def _http_error_category(error):
    """Classify bounded provider metadata; never retain its message or response body."""
    status = error.code if isinstance(error.code, int) else 0
    if status == 401:
        return 'invalid_credentials'
    if status == 429:
        return 'rate_limited'

    headers = error.headers or {}
    content_type = (headers.get('Content-Type') or '').split(';', 1)[0].lower()
    code = None
    if content_type == 'application/json':
        try:
            raw = error.read(4_097)
            if len(raw) <= 4_096:
                body = json.loads(raw)
                detail = body.get('error') if isinstance(body, dict) else None
                if isinstance(detail, dict) and isinstance(detail.get('code'), str):
                    code = detail['code']
        except (ValueError, TypeError, UnicodeError, OSError):
            pass

    if code in {'model_not_found', 'model_decommissioned'} and status in {400, 404, 422}:
        return 'invalid_model'
    if code in {'model_permission_blocked_org', 'model_permission_blocked_project'} and status == 403:
        return 'model_permission_denied'
    if status == 403:
        return 'edge_access_denied' if headers.get('CF-Ray') and content_type != 'application/json' else 'access_denied'
    if status in {400, 404, 422}:
        return 'invalid_upstream_request'
    if status == 498 or status >= 500:
        return 'provider_unavailable'
    return 'upstream_error'


@chat_bp.post('/api/chat')
def chat():
    request.max_content_length = MAX_BODY
    if request.content_length is not None and request.content_length > MAX_BODY:
        return jsonify(success=False, message='Chat request is too large.'), 413
    body = request.get_json(silent=True)
    if not isinstance(body, dict) or set(body) != {'message', 'history'}:
        return jsonify(success=False, message='Message and history are required.'), 400
    message, history = body['message'], body['history']
    if (not isinstance(message, str) or not message.strip() or len(message) > MAX_MESSAGE
            or not isinstance(history, list) or len(history) > MAX_HISTORY):
        return jsonify(success=False, message='Invalid chat message or history.'), 400
    messages = [{'role': 'system', 'content': SYSTEM_PROMPT}]
    for item in history:
        if (not isinstance(item, dict) or set(item) != {'role', 'content'}
                or item['role'] not in ('user', 'assistant')
                or not isinstance(item['content'], str) or not item['content'].strip()
                or len(item['content']) > MAX_MESSAGE):
            return jsonify(success=False, message='Invalid chat history.'), 400
        messages.append({'role': item['role'], 'content': item['content'].strip()})
    messages.append({'role': 'user', 'content': message.strip()})

    key = current_app.config.get('GROQ_API_KEY', '')
    model = current_app.config.get('GROQ_MODEL', '')
    if not key or not isinstance(model, str) or not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9._/-]{0,100}', model):
        return jsonify(success=False, message='Chat service is not configured.'), 503
    payload = json.dumps({'model': model, 'messages': messages,
                          'max_completion_tokens': 400, 'temperature': 0.2}).encode('utf-8')
    upstream = Request(GROQ_ENDPOINT, data=payload, method='POST', headers={
        'Authorization': f'Bearer {key}', 'Content-Type': 'application/json',
        'User-Agent': 'ResQNet/1.0'})
    try:
        with _open_groq(upstream) as response:
            raw = response.read(65_537)
        if len(raw) > 65_536:
            raise ValueError('Oversized completion')
        result = json.loads(raw)
        reply = result['choices'][0]['message']['content']
        if not isinstance(reply, str) or not reply.strip() or len(reply) > 4_000:
            raise ValueError('Invalid completion')
        if ACTION_CLAIM.search(reply):
            reply = SAFE_ACTION_REPLY
    except HTTPError as exc:
        status = exc.code if isinstance(exc.code, int) else 0
        category = _http_error_category(exc)
        current_app.logger.warning('Groq chat upstream status=%d category=%s', status, category)
        if exc.code == 429:
            return jsonify(success=False, message='Chat is busy. Please retry shortly.'), 429
        return jsonify(success=False, message='Chat service is unavailable. Please retry.'), 503
    except (URLError, socket.timeout, TimeoutError):
        return jsonify(success=False, message='Chat service timed out or is unavailable.'), 503
    except (ValueError, KeyError, IndexError, TypeError, UnicodeError):
        return jsonify(success=False, message='Chat service returned an unusable response.'), 502
    response = jsonify(success=True, reply=reply.strip())
    response.headers['Cache-Control'] = 'private, no-store'
    return response
