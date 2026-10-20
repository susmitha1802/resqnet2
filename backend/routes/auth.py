"""
ResQNet — Auth Routes Blueprint
POST /register  — create account (reporter / volunteer / ngo / admin)
POST /login     — authenticate and receive JWT
GET  /profile   — get current user profile
POST /seed-demo-users — (DEBUG only) seed demo accounts into DB
"""
import os
import hmac
import secrets
import bcrypt
from flask import Blueprint, request, jsonify, current_app
from flask_jwt_extended import create_access_token, jwt_required, get_jwt_identity

from extensions import db
from models import User, Volunteer
from routes.middleware import require_auth, require_role
from security import is_production, is_demo_account, DEMO_ACCOUNT_EMAILS

auth_bp = Blueprint('auth', __name__)

# Admin secret code (set ADMIN_SECRET_CODE in .env to override)
ADMIN_SECRET_CODE = os.getenv('ADMIN_SECRET_CODE')

VALID_ROLES = ('reporter', 'volunteer', 'ngo', 'admin')


def _success(data=None, message='OK', status=200):
    return jsonify({'success': True, 'message': message, **(data or {})}), status


def _error(message='Error', status=400):
    return jsonify({'success': False, 'message': message}), status


# ── POST /register ─────────────────────────────────────────────────────────────
@auth_bp.route('/register', methods=['POST'])
def register():
    data = request.get_json(silent=True) or {}

    name     = data.get('name', '').strip()
    email    = data.get('email', '').strip().lower()
    phone    = data.get('phone', '').strip()
    password = data.get('password', '')
    role     = data.get('role', 'reporter').strip().lower()

    # ── Validation ─────────────────────────────────────────────────────────────
    if not all([name, email, phone, password]):
        return _error('All fields are required (name, email, phone, password)')
    if len(name) > 100:
        return _error('Name must be 100 characters or fewer')
    if len(password) < 6:
        return _error('Password must be at least 6 characters')
    if role not in VALID_ROLES:
        return _error(f'Invalid role. Must be one of: {", ".join(VALID_ROLES)}')
    if is_production(current_app.config) and email in DEMO_ACCOUNT_EMAILS:
        return _error('This address is reserved for local demo data.', 400)
    if User.query.filter_by(email=email).first():
        return _error('Email already registered', 409)

    # ── Admin secret code check ─────────────────────────────────────────────────
    if role == 'admin':
        provided_code = data.get('admin_secret_code', '').strip()
        configured_code = current_app.config.get('ADMIN_SECRET_CODE', ADMIN_SECRET_CODE)
        if not configured_code or not hmac.compare_digest(provided_code, configured_code):
            return _error('Invalid admin secret code. Admin registration is restricted.', 403)

    # ── Hash password ──────────────────────────────────────────────────────────
    hashed = bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode()

    # ── Create user ────────────────────────────────────────────────────────────
    import json
    user = User(name=name, email=email, phone=phone, password=hashed, role=role)

    if role == 'volunteer':
        user.skills       = json.dumps(data.get('skills', []))
        user.location     = data.get('location', '')
        user.availability = data.get('availability', 'available')

    if role == 'ngo':
        # Store NGO org name in the location field, skills stores org type
        user.location = data.get('org_name', '').strip()
        user.skills   = json.dumps({'org_type': data.get('org_type', 'NGO'), 'area': data.get('area', '')})

    db.session.add(user)
    db.session.flush()   # get user_id before commit

    if role == 'volunteer':
        vol = Volunteer(user_id=user.user_id)
        db.session.add(vol)

    db.session.commit()

    token = create_access_token(identity=str(user.user_id))
    return _success(
        {'token': token, 'user': user.to_dict()},
        'Account created successfully',
        201
    )


# ── POST /login ────────────────────────────────────────────────────────────────
@auth_bp.route('/login', methods=['POST'])
def login():
    data = request.get_json(silent=True) or {}

    email    = data.get('email', '').strip().lower()
    password = data.get('password', '')

    if not email or not password:
        return _error('Email and password are required')

    user = User.query.filter_by(email=email).first()
    if user and is_production(current_app.config) and is_demo_account(user):
        return _error('Invalid email or password', 401)
    if not user or not bcrypt.checkpw(password.encode(), user.password.encode()):
        return _error('Invalid email or password', 401)

    token = create_access_token(identity=str(user.user_id))
    return _success({
        'token': token,
        'role':  user.role,       # Explicit role field for easy frontend use
        'user':  user.to_dict()
    })


# ── GET /profile ───────────────────────────────────────────────────────────────
@auth_bp.route('/profile', methods=['GET'])
@require_auth
def get_profile():
    uid  = int(get_jwt_identity())
    user = db.get_or_404(User, uid)
    return _success({'user': user.to_dict()})


# ── POST /seed-demo-users (DEBUG ONLY) ────────────────────────────────────────
@auth_bp.route('/seed-demo-users', methods=['POST'])
@require_role('admin')
def seed_demo_users():
    """Explicit development-only fixtures; credentials are never returned."""
    if is_production(current_app.config):
        return _error('Not found', 404)
    import json
    if not current_app.config.get('DEBUG', False) or not current_app.config.get('SEED_DEMO_DATA', False):
        return _error('Seed endpoint is only available in DEBUG mode', 403)

    # Synthetic local fixtures only; no personal/organization contacts.
    demo_users = [{'name': 'Demo reporter', 'email': 'user@demo.com', 'phone': 'not-provided', 'role': 'reporter'}, {'name': 'Demo volunteer', 'email': 'vol@demo.com', 'phone': 'not-provided', 'role': 'volunteer'}, {'name': 'Demo ngo', 'email': 'ngo@demo.com', 'phone': 'not-provided', 'role': 'ngo'}, {'name': 'Demo admin', 'email': 'admin@demo.com', 'phone': 'not-provided', 'role': 'admin'}]

    created = []
    skipped = []

    for u in demo_users:
        if User.query.filter_by(email=u['email']).first():
            skipped.append(u['email'])
            continue

        hashed = bcrypt.hashpw(secrets.token_urlsafe(32).encode(), bcrypt.gensalt()).decode()
        user = User(
            name=u['name'],
            email=u['email'],
            phone=u['phone'],
            password=hashed,
            role=u['role'],
            skills=u.get('skills'),
            location=u.get('location'),
        )
        db.session.add(user)
        db.session.flush()

        if u['role'] == 'volunteer':
            vol = Volunteer(user_id=user.user_id)
            db.session.add(vol)

        created.append(u['email'])

    db.session.commit()

    return _success({
        'created': created,
        'skipped': skipped,

    }, f'Seeded {len(created)} users (skipped {len(skipped)} existing)')
