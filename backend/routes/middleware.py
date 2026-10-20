"""
ResQNet — Auth Middleware
Reusable decorators for JWT authentication and role-based authorization.

Usage:
    @require_auth          → any logged-in user
    @require_role('admin') → exact single role
    @require_any_role(['volunteer', 'ngo'])  → any of the listed roles
"""
from functools import wraps
from flask import jsonify
from flask_jwt_extended import jwt_required, get_jwt_identity

from extensions import db
from models import User


def _get_current_user() -> User | None:
    """Fetch the current user from DB using JWT identity."""
    try:
        uid = int(get_jwt_identity())
        return db.session.get(User, uid)
    except Exception:
        return None


def _error(message: str, status: int = 403):
    return jsonify({'success': False, 'message': message}), status


# ── require_auth ───────────────────────────────────────────────────────────────
def require_auth(fn):
    """
    Decorator: requires a valid JWT token.
    Returns 401 if missing or invalid.
    """
    @wraps(fn)
    @jwt_required()
    def wrapper(*args, **kwargs):
        if not _get_current_user():
            return _error('Invalid session identity', 401)
        return fn(*args, **kwargs)
    return wrapper


# ── require_role ───────────────────────────────────────────────────────────────
def require_role(role: str):
    """
    Decorator factory: requires a valid JWT token AND the user must have
    exactly the specified role.

    Example:
        @require_role('admin')
        def my_view(): ...
    """
    def decorator(fn):
        @wraps(fn)
        @jwt_required()
        def wrapper(*args, **kwargs):
            user = _get_current_user()
            if not user:
                return _error('Invalid session identity', 401)
            if user.role != role:
                return _error(
                    f'Access denied. This endpoint requires the "{role}" role. '
                    f'Your role is "{user.role}".',
                    403
                )
            return fn(*args, **kwargs)
        return wrapper
    return decorator


# ── require_any_role ───────────────────────────────────────────────────────────
def require_any_role(roles: list[str]):
    """
    Decorator factory: requires a valid JWT AND user role must be in `roles`.

    Example:
        @require_any_role(['admin', 'ngo'])
        def my_view(): ...
    """
    def decorator(fn):
        @wraps(fn)
        @jwt_required()
        def wrapper(*args, **kwargs):
            user = _get_current_user()
            if not user:
                return _error('Invalid session identity', 401)
            if user.role not in roles:
                allowed = ', '.join(f'"{r}"' for r in roles)
                return _error(
                    f'Access denied. This endpoint requires one of: {allowed}. '
                    f'Your role is "{user.role}".',
                    403
                )
            return fn(*args, **kwargs)
        return wrapper
    return decorator
