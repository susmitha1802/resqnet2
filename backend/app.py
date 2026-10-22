"""
ResQNet — Flask Application Entry Point

Architecture:
    routes/auth.py          → auth_bp          (/register, /login, /profile)
    routes/reports.py       → reports_bp       (/report-disaster, /reports, /report/<id>)
    routes/help_requests.py → help_bp          (/help-request, /help-requests, ...)
    routes/volunteers.py    → volunteers_bp    (/volunteer/*)
    routes/admin.py         → admin_bp         (/admin/*)
"""
import os
import hashlib
import hmac
from flask import Flask, jsonify, request
from flask_cors import CORS
from flask_jwt_extended import jwt_required, get_jwt_identity, verify_jwt_in_request
from flasgger import Swagger  # type: ignore[import-untyped]

from config import Config
from routes.flood import flood_bp
from extensions import db, jwt
from routes import auth_bp, reports_bp, help_bp, volunteers_bp, admin_bp, ngo_bp, contact_bp, alerts_bp, preparedness_bp, map_risk_bp


# ── Swagger / OpenAPI config ───────────────────────────────────────────────────
SWAGGER_CONFIG = {
    "headers": [],
    "specs": [
        {
            "endpoint": "apispec",
            "route":    "/apispec.json",
            "rule_filter": lambda rule: True,
            "model_filter": lambda tag: True,
        }
    ],
    "static_url_path": "/flasgger_static",
    "swagger_ui": True,
    "specs_route": "/apidocs",
}

SWAGGER_TEMPLATE = {
    "swagger": "2.0",
    "info": {
        "title":       "ResQNet API",
        "description": (
            "## ResQNet — Disaster Relief Coordination Platform\n\n"
            "Full REST API for managing disaster reports, help requests, volunteers, and admin operations.\n\n"
            "**Authentication:** Most endpoints require a JWT token. "
            "Call `POST /login` first, then pass the token as:\n"
            "`Authorization: Bearer <token>`"
        ),
        "version": "1.0.0",
        "contact": {"name": "ResQNet Team"},
    },
    "basePath": "/",
    "schemes":  ["http", "https"],
    "consumes": ["application/json"],
    "produces": ["application/json"],
    "securityDefinitions": {
        "BearerAuth": {
            "type": "apiKey",
            "name": "Authorization",
            "in":   "header",
            "description": "Enter: **Bearer &lt;token&gt;**",
        }
    },
    "tags": [
        {"name": "Auth",          "description": "Registration, login, and profile"},
        {"name": "Reports",       "description": "Disaster report submission and retrieval"},
        {"name": "Help Requests", "description": "SOS help request lifecycle"},
        {"name": "Volunteers",    "description": "Volunteer task management"},
        {"name": "Admin",         "description": "Admin dashboard and analytics"},
        {"name": "Map",           "description": "Live map data aggregation"},
    ],
    "paths": {
        # ── Health ────────────────────────────────────────────────────────────
        "/health": {
            "get": {
                "tags":    ["Map"],
                "summary": "Health check",
                "responses": {"200": {"description": "Server is up"}},
            }
        },
        # ── Auth ──────────────────────────────────────────────────────────────
        "/register": {
            "post": {
                "tags":    ["Auth"],
                "summary": "Register a new user",
                "parameters": [{
                    "in": "body", "name": "body", "required": True,
                    "schema": {
                        "type": "object",
                        "required": ["name", "email", "phone", "password"],
                        "properties": {
                            "name":         {"type": "string",  "example": "Priya Sharma"},
                            "email":        {"type": "string",  "example": "priya@example.com"},
                            "phone":        {"type": "string",  "description": "Contact information provided privately by the registrant"},
                            "password":     {"type": "string",  "description": "User-supplied private password"},
                            "role":         {"type": "string",  "enum": ["reporter","volunteer","ngo","admin"], "example": "reporter"},
                            "admin_secret_code": {"type": "string", "description": "Private operator-provided code; required only when role=admin"},
                            "org_name":     {"type": "string",  "example": "Relief India Foundation", "description": "Required when role=ngo"},
                            "org_type":     {"type": "string",  "example": "Disaster Relief NGO"},
                            "area":         {"type": "string",  "example": "Hyderabad"},
                            "skills":       {"type": "array",   "items": {"type": "string"}, "example": ["First Aid","Driving"]},
                            "location":     {"type": "string",  "example": "Chennai"},
                            "availability": {"type": "string",  "enum": ["available","unavailable"], "example": "available"},
                        }
                    }
                }],
                "responses": {
                    "201": {"description": "User registered — returns JWT token + user object"},
                    "400": {"description": "Validation error"},
                    "409": {"description": "Email already registered"},
                },
            }
        },
        "/login": {
            "post": {
                "tags":    ["Auth"],
                "summary": "Login and receive JWT token",
                "parameters": [{
                    "in": "body", "name": "body", "required": True,
                    "schema": {
                        "type": "object",
                        "required": ["email", "password"],
                        "properties": {
                            "email":    {"type": "string", "example": "priya@example.com"},
                            "password": {"type": "string", "description": "User-supplied private password"},
                        }
                    }
                }],
                "responses": {
                    "200": {"description": "JWT token + user object"},
                    "401": {"description": "Invalid credentials"},
                },
            }
        },
        "/profile": {
            "get": {
                "tags":     ["Auth"],
                "summary":  "Get logged-in user's profile",
                "security": [{"BearerAuth": []}],
                "responses": {
                    "200": {"description": "User profile object"},
                    "401": {"description": "Missing or invalid token"},
                },
            }
        },
        # ── Reports ───────────────────────────────────────────────────────────
        "/report-disaster": {
            "post": {
                "tags":        ["Reports"],
                "summary":     "Submit a new disaster report",
                "security":    [{"BearerAuth": []}],
                "consumes":    ["multipart/form-data"],
                "parameters":  [
                    {"in": "formData", "name": "disaster_type", "required": True,  "type": "string", "enum": ["Flood","Cyclone","Earthquake","Landslide","Fire"]},
                    {"in": "formData", "name": "description",   "required": True,  "type": "string"},
                    {"in": "formData", "name": "latitude",      "required": True,  "type": "number"},
                    {"in": "formData", "name": "longitude",     "required": True,  "type": "number"},
                    {"in": "formData", "name": "images",        "required": False, "type": "file"},
                ],
                "responses": {
                    "201": {"description": "Community report with an unvalidated rule-based severity estimate"},
                    "400": {"description": "Validation error"},
                },
            }
        },
        "/reports": {
            "get": {
                "tags":     ["Reports"],
                "summary":  "List recent disaster reports",
                "security": [{"BearerAuth": []}],
                "parameters": [
                    {"in": "query", "name": "type", "type": "string", "enum": ["Flood","Cyclone","Earthquake","Landslide","Fire"], "required": False},
                ],
                "responses": {
                    "200": {"description": "Array of disaster reports"},
                    "401": {"description": "Missing or invalid token"},
                },
            }
        },
        "/report/{report_id}": {
            "get": {
                "tags":     ["Reports"],
                "summary":  "Get a single disaster report by ID",
                "security": [{"BearerAuth": []}],
                "parameters": [{"in": "path", "name": "report_id", "required": True, "type": "integer"}],
                "responses": {
                    "200": {"description": "Report object"},
                    "401": {"description": "Missing or invalid token"},
                    "404": {"description": "Not found"},
                },
            }
        },
        # ── Help Requests ─────────────────────────────────────────────────────
        "/help-request": {
            "post": {
                "tags":     ["Help Requests"],
                "summary":  "Submit an SOS help request",
                "security": [{"BearerAuth": []}],
                "consumes": ["multipart/form-data"],
                "parameters": [
                    {"in": "formData", "name": "name",             "required": True,  "type": "string"},
                    {"in": "formData", "name": "contact",          "required": True,  "type": "string"},
                    {"in": "formData", "name": "request_type",     "required": True,  "type": "string", "enum": ["Food","Water","Medicine","Rescue","Shelter"]},
                    {"in": "formData", "name": "number_of_people", "required": False, "type": "integer"},
                    {"in": "formData", "name": "description",      "required": False, "type": "string"},
                    {"in": "formData", "name": "latitude",         "required": True,  "type": "number"},
                    {"in": "formData", "name": "longitude",        "required": True,  "type": "number"},
                    {"in": "formData", "name": "image",            "required": False, "type": "file"},
                ],
                "responses": {
                    "201": {"description": "SOS created with rule-based priority and duplicate checks"},
                    "400": {"description": "Validation error"},
                },
            }
        },
        "/help-requests": {
            "get": {
                "tags":     ["Help Requests"],
                "summary":  "List help requests (role-filtered)",
                "security": [{"BearerAuth": []}],
                "responses": {"200": {"description": "Array of help requests"}},
            }
        },
        "/help-request/{req_id}": {
            "get": {
                "tags":     ["Help Requests"],
                "summary":  "Get a single help request by ID",
                "security": [{"BearerAuth": []}],
                "parameters": [{"in": "path", "name": "req_id", "required": True, "type": "integer"}],
                "responses": {
                    "200": {"description": "Help request object"},
                    "404": {"description": "Not found"},
                },
            }
        },
        "/help-request/status": {
            "put": {
                "tags":     ["Help Requests"],
                "summary":  "Update help request status",
                "security": [{"BearerAuth": []}],
                "parameters": [{
                    "in": "body", "name": "body", "required": True,
                    "schema": {
                        "type": "object",
                        "properties": {
                            "request_id": {"type": "integer"},
                            "status":     {"type": "string", "enum": ["Pending","Accepted","En Route","On Site","Completed","Duplicate"]},
                        }
                    }
                }],
                "responses": {"200": {"description": "Updated request object"}},
            }
        },
        # ── Volunteers ────────────────────────────────────────────────────────
        "/volunteer/tasks": {
            "get": {
                "tags":     ["Volunteers"],
                "summary":  "Get tasks assigned to the logged-in volunteer",
                "security": [{"BearerAuth": []}],
                "responses": {"200": {"description": "Array of relief tasks"}},
            }
        },
        "/volunteer/accept-task": {
            "put": {
                "tags":     ["Volunteers"],
                "summary":  "Accept a pending help request",
                "security": [{"BearerAuth": []}],
                "parameters": [{
                    "in": "body", "name": "body", "required": True,
                    "schema": {
                        "type": "object",
                        "properties": {"request_id": {"type": "integer"}}
                    }
                }],
                "responses": {
                    "200": {"description": "Task created and request marked Accepted"},
                    "409": {"description": "Already on a task, or request not pending"},
                },
            }
        },
        "/volunteer/update-status": {
            "put": {
                "tags":     ["Volunteers"],
                "summary":  "Update volunteer availability",
                "security": [{"BearerAuth": []}],
                "parameters": [{
                    "in": "body", "name": "body", "required": True,
                    "schema": {
                        "type": "object",
                        "properties": {"status": {"type": "string", "enum": ["available","unavailable","on_task"]}}
                    }
                }],
                "responses": {"200": {"description": "Updated volunteer object"}},
            }
        },
        "/volunteer/complete-task": {
            "put": {
                "tags":     ["Volunteers"],
                "summary":  "Mark an active task as completed",
                "security": [{"BearerAuth": []}],
                "parameters": [{
                    "in": "body", "name": "body", "required": True,
                    "schema": {
                        "type": "object",
                        "properties": {"task_id": {"type": "integer"}}
                    }
                }],
                "responses": {"200": {"description": "Task marked completed"}},
            }
        },
        # ── Admin ─────────────────────────────────────────────────────────────
        "/admin/dashboard": {
            "get": {
                "tags":     ["Admin"],
                "summary":  "Admin dashboard stats",
                "security": [{"BearerAuth": []}],
                "responses": {"200": {"description": "Stats + recent high-priority requests"}},
            }
        },
        "/admin/analytics": {
            "get": {
                "tags":     ["Admin"],
                "summary":  "Analytics breakdown (by type, status, priority, day)",
                "security": [{"BearerAuth": []}],
                "responses": {"200": {"description": "Analytics data"}},
            }
        },
        "/admin/reports": {
            "get": {
                "tags":     ["Admin"],
                "summary":  "Paginated disaster reports (admin)",
                "security": [{"BearerAuth": []}],
                "parameters": [
                    {"in": "query", "name": "type",   "type": "string",  "required": False},
                    {"in": "query", "name": "limit",  "type": "integer", "required": False},
                    {"in": "query", "name": "offset", "type": "integer", "required": False},
                ],
                "responses": {"200": {"description": "Paginated reports"}},
            }
        },
        "/admin/requests": {
            "get": {
                "tags":     ["Admin"],
                "summary":  "Paginated help requests (admin)",
                "security": [{"BearerAuth": []}],
                "parameters": [
                    {"in": "query", "name": "priority", "type": "string",  "required": False},
                    {"in": "query", "name": "status",   "type": "string",  "required": False},
                    {"in": "query", "name": "limit",    "type": "integer", "required": False},
                    {"in": "query", "name": "offset",   "type": "integer", "required": False},
                ],
                "responses": {"200": {"description": "Paginated help requests"}},
            }
        },
        "/admin/volunteers": {
            "get": {
                "tags":     ["Admin"],
                "summary":  "List all volunteers (admin)",
                "security": [{"BearerAuth": []}],
                "responses": {"200": {"description": "Array of volunteers"}},
            }
        },
        # ── Map ───────────────────────────────────────────────────────────────
        "/map/data": {
            "get": {
                "tags":    ["Map"],
                "summary": "Aggregated live map data (requests + reports + volunteers)",
                "responses": {"200": {"description": "Map data payload"}},
            }
        },
    },
}


# ── App Factory ────────────────────────────────────────────────────────────────
def create_app(config_class=Config) -> Flask:
    app = Flask(__name__)
    app.config.from_object(config_class)
    from security import validate_runtime_config
    validate_runtime_config(app)

    # Cloud production never writes private evidence to Render's temporary disk.
    if app.config.get('STORAGE_BACKEND', 'local') == 'local':
        os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)

    # ── Extensions ────────────────────────────────────────────────────────────
    db.init_app(app)
    jwt.init_app(app)
    CORS(app, resources={r"/*": {"origins": app.config.get('CORS_ORIGINS', [])}},
         allow_headers=['Content-Type', 'Authorization'], supports_credentials=False)

    @app.after_request
    def private_response_headers(response):
        response.headers['X-Content-Type-Options'] = 'nosniff'
        response.headers['Referrer-Policy'] = 'no-referrer'
        if (request.headers.get('Authorization') or request.path.startswith('/admin/')
                or request.path in {'/login', '/register', '/profile', '/api/chat'}):
            response.headers['Cache-Control'] = 'private, no-store'
        return response

    # ── Swagger UI ────────────────────────────────────────────────────────────
    Swagger(app, config=SWAGGER_CONFIG, template=SWAGGER_TEMPLATE)

    # ── Register Blueprints ───────────────────────────────────────────────────
    app.register_blueprint(auth_bp)
    app.register_blueprint(reports_bp)
    app.register_blueprint(help_bp)
    app.register_blueprint(volunteers_bp)
    app.register_blueprint(admin_bp)
    app.register_blueprint(ngo_bp)
    app.register_blueprint(contact_bp)
    app.register_blueprint(alerts_bp)
    app.register_blueprint(preparedness_bp)
    app.register_blueprint(map_risk_bp)
    app.register_blueprint(flood_bp)
    from routes.geocode import geocode_bp
    app.register_blueprint(geocode_bp)
    from routes.chat import chat_bp
    app.register_blueprint(chat_bp)

    if app.config.get('PROXY_DIAGNOSTIC_ENABLED'):
        from routes.middleware import require_role

        @app.get('/admin/proxy-diagnostic')
        @require_role('admin')
        def proxy_diagnostic():
            # A stable comparison code, never a client IP or forwarded header.
            address = (request.remote_addr or '').encode('utf-8')
            key = app.config['SECRET_KEY'].encode('utf-8')
            code = hmac.new(key, b'resqnet-proxy-diagnostic\0' + address,
                            hashlib.sha256).hexdigest()[:24]
            response = jsonify(success=True, client_code=code,
                               trusted_proxy_hops=app.config['TRUSTED_PROXY_HOPS'])
            response.headers['Cache-Control'] = 'no-store'
            return response

    from rate_limits import init_rate_limiting
    init_rate_limiting(app)

    # ── Create Tables ─────────────────────────────────────────────────────────
    with app.app_context():
        if (app.config.get('APP_ENV') == 'production' and not app.testing
                and app.config.get('STORAGE_BACKEND') == 'supabase'):
            from supabase_storage import check_private_bucket
            check_private_bucket()
        from database import initialize_database
        initialize_database()
        from models import User
        if app.config.get('SEED_DEMO_DATA', False) and User.query.count() == 0:
            try:
                from seed_demo import seed_demo_data
                seed_demo_data()
                print("Database was empty. Automatically seeded demo data.")
            except Exception as e:
                print(f"Failed to auto-seed database: {e}")

    # ── Global Routes ─────────────────────────────────────────────────────────

    @app.route('/health', methods=['GET'])
    def health():
        """Health-check endpoint."""
        return jsonify({
            'status':  'ok',
            'app':     'ResQNet',
            'version': '1.0.0',
        })

    @app.route('/map/data', methods=['GET'])
    def map_data():
        """Aggregated data for the live map page."""
        from models import HelpRequest, DisasterReport, Volunteer, ReliefTask
        from sqlalchemy.orm import joinedload
        from map_provenance import demo_incident

        # Eager load user to prevent N+1 queries in Volunteer.to_dict()
        map_volunteers = Volunteer.query.options(
            joinedload(Volunteer.user)
        ).filter(
            Volunteer.last_location_lat.isnot(None),
            Volunteer.last_location_lng.isnot(None)
        ).all()

        total_volunteers = Volunteer.query.count()

        # Get requests without eager loading tasks because lazy='dynamic' doesn't support it
        requests = HelpRequest.query.filter(
            HelpRequest.status.in_(['Pending', 'Accepted', 'En Route', 'On Site'])
        ).all()

        from access import request_view, report_view
        from routes.middleware import _get_current_user
        verify_jwt_in_request(optional=True)
        viewer = _get_current_user() if get_jwt_identity() is not None else None
        if get_jwt_identity() is not None and viewer is None:
            return jsonify(success=False, message='Invalid session identity'), 401
        include_demo = request.args.get('include_demo') == '1' or app.config.get('DEMO_MODE', False)
        requests = [r for r in requests if include_demo or not demo_incident(r, 'request')]
        requests_data = [request_view(r, viewer) for r in requests]

        reports = DisasterReport.query.order_by(
            DisasterReport.created_at.desc()
        ).limit(50).all()
        reports = [r for r in reports if include_demo or not demo_incident(r, 'report')]

        # Total active incidents = active requests + recent disaster reports
        total_active = len(requests) + len(reports)
        # There is no incident-publication approval field in the current schema.
        # Anonymous users receive aggregate counts, not private incident records.
        if viewer is None:
            requests_data, reports, map_volunteers = [], [], []
        elif viewer.role == 'reporter':
            requests_data = [request_view(r, viewer) for r in requests if r.user_id == viewer.user_id]
            reports = [r for r in reports if r.user_id == viewer.user_id]

        return jsonify({
            'success':          True,
            'demo_mode':        bool(app.config.get('DEMO_MODE', False)),
            'visibility':       'aggregate-only' if viewer is None else 'authorized',
            'requests':         requests_data,
            'reports':          [report_view(r, viewer) for r in reports],
            'volunteers':       [v.to_dict() if viewer and (viewer.role == 'admin' or viewer.user_id == v.user_id) else {
                'volunteer_id': v.volunteer_id, 'availability_status': v.availability_status,
                'last_location_lat': round(float(v.last_location_lat), 2),
                'last_location_lng': round(float(v.last_location_lng), 2),
                'location_precision': 'approximate (0.01 degree grid)'
            } for v in map_volunteers],
            'total_volunteers': total_volunteers,
            'total_active':     total_active,
        })

    @app.route('/map/demo-scenarios', methods=['GET'])
    def map_demo_scenarios():
        """Expose only the complete, fixed fictional map fixture; no incident data."""
        from public_map_demo import NOTICE, SCENARIOS, _intact, _rows
        rows = _rows(db.session)
        scenarios = ([{'title': title, 'latitude': lat, 'longitude': lng,
                       'notice': NOTICE, 'is_demo': True}
                      for title, lat, lng in SCENARIOS] if _intact(rows) else [])
        response = jsonify(success=True, scenarios=scenarios)
        response.headers['Cache-Control'] = 'no-store'
        return response

    @app.route('/public/stats', methods=['GET'])
    def public_stats():
        """Public homepage statistics."""
        from models import HelpRequest, Volunteer, ReliefTask
        
        # Requests Handled = total requests in system
        total_requests = HelpRequest.query.count()
        
        # Active Volunteers = currently available
        active_vols = Volunteer.query.filter_by(availability_status='available').count()
        total_volunteers = Volunteer.query.count()
        
        # Completed = total resolved requests
        completed_reqs = HelpRequest.query.filter_by(status='Completed').count()
        active_reqs = HelpRequest.query.filter(HelpRequest.status.in_(
            ['Pending', 'Accepted', 'En Route', 'On Site'])).count()
        
        return jsonify({
            'success': True,
            'demo_mode': bool(app.config.get('DEMO_MODE', False)),
            'stats': {
                'total_requests': total_requests,
                'active_requests': active_reqs,
                'active_volunteers': active_vols,
                'total_volunteers': total_volunteers,
                'completed': completed_reqs
            }
        })

    # ── JWT Error Handlers ────────────────────────────────────────────────────

    @jwt.unauthorized_loader
    def missing_token(reason):
        return jsonify({'success': False, 'message': f'Missing token: {reason}'}), 401

    @jwt.invalid_token_loader
    def invalid_token(reason):
        return jsonify({'success': False, 'message': f'Invalid token: {reason}'}), 422

    @jwt.expired_token_loader
    def expired_token(jwt_header, jwt_payload):
        return jsonify({'success': False, 'message': 'Token has expired'}), 401

    # ── Generic Error Handlers ────────────────────────────────────────────────

    @app.errorhandler(404)
    def not_found(e):
        return jsonify({'success': False, 'message': 'Resource not found'}), 404

    @app.errorhandler(405)
    def method_not_allowed(e):
        return jsonify({'success': False, 'message': 'Method not allowed'}), 405

    @app.errorhandler(500)
    def server_error(e):
        return jsonify({'success': False, 'message': 'Internal server error'}), 500

    return app


# ── Entry Point ────────────────────────────────────────────────────────────────
if __name__ == '__main__':
    application = create_app()
    application.run(host='0.0.0.0', port=5000, debug=application.config.get('DEBUG', False))
