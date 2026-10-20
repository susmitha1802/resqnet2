"""
ResQNet — Help Requests Routes Blueprint
POST /help-request          — submit SOS (reporter only)
GET  /help-requests         — list requests (role-filtered)
GET  /help-request/<id>     — get single request
PUT  /help-request/status   — update status (volunteer/admin/ngo)
"""
import os
from flask import Blueprint, request, jsonify, current_app
from flask_jwt_extended import get_jwt_identity
from werkzeug.utils import secure_filename
from sqlalchemy import update
from sqlalchemy.exc import SQLAlchemyError
from sos_lifecycle import TransitionConflict, transition, ACTIVE_TASK_STATES

from access import request_view, can_view_private_request
from extensions import db
from models import User, HelpRequest, Volunteer, ReliefTask
from ai.priority  import predict_priority
from ai.duplicate import detect_duplicate
from ai.severity  import classify_severity
from routes.middleware import require_role, require_any_role

help_bp = Blueprint('help_requests', __name__)


def _success(data=None, message='OK', status=200):
    return jsonify({'success': True, 'message': message, **(data or {})}), status


def _error(message='Error', status=400):
    return jsonify({'success': False, 'message': message}), status


def _save_file(file_obj, subfolder: str) -> str | None:
    from private_uploads import save_incident_image
    return save_incident_image(file_obj, subfolder)


# ── POST /help-request ─────────────────────────────────────────────────────────
@help_bp.route('/help-request', methods=['POST'])
@require_role('reporter')   # Only reporters can submit help requests
def create_help_request():
    uid  = int(get_jwt_identity())
    data = request.form

    name         = data.get('name', '').strip()
    contact      = data.get('contact', '').strip()
    request_type = data.get('request_type', '').strip()
    people_raw   = data.get('number_of_people', '1')
    description  = data.get('description', '').strip()

    lat_val = data.get('latitude')
    lng_val = data.get('longitude')
    if lat_val is None or lng_val is None:
        return _error('Invalid latitude, longitude, or number_of_people')

    try:
        latitude  = float(lat_val)
        longitude = float(lng_val)
        people    = max(1, int(people_raw))
    except (TypeError, ValueError):
        return _error('Invalid latitude, longitude, or number_of_people')

    if not all([name, contact, request_type]):
        return _error('name, contact, and request_type are required')

    if len(name) > 100:
        return _error('Name must be 100 characters or fewer')
    if len(description) > 2000:
        return _error('Description must be 2000 characters or fewer')

    valid_types = ('Food', 'Water', 'Medicine', 'Rescue', 'Shelter')
    if request_type not in valid_types:
        return _error(f'request_type must be one of {valid_types}')

    # ── AI: Priority Prediction ──────────────────────────────────────────────
    priority = predict_priority(request_type, people)

    # ── AI: Duplicate Detection ──────────────────────────────────────────────
    active_requests = HelpRequest.query.filter(
        HelpRequest.status.in_(['Pending', 'Accepted'])
    ).all()
    is_dup = detect_duplicate(
        {'request_type': request_type, 'latitude': latitude, 'longitude': longitude},
        active_requests
    )

    # ── Upload image ─────────────────────────────────────────────────────────
    img_path = None
    if 'image' in request.files:
        img_path = _save_file(request.files['image'], 'requests')

    # ── AI: Damage Severity (if image provided) ───────────────────────────────
    severity = classify_severity(image_path=img_path) if img_path else None

    # ── Persist ───────────────────────────────────────────────────────────────
    req = HelpRequest(
        user_id          = uid,
        name             = name,
        contact          = contact,
        request_type     = request_type,
        priority_level   = priority,
        number_of_people = people,
        description      = description,
        image_path       = img_path,
        is_duplicate     = is_dup,
        status           = 'Duplicate' if is_dup else 'Pending',
        latitude         = latitude,
        longitude        = longitude,
    )
    db.session.add(req)
    db.session.commit()

    return _success(
        {
            'request': req.to_dict(),
            'ai': {
                'priority':     priority,
                'is_duplicate': is_dup,
                'severity':     severity,
            }
        },
        'Help request submitted successfully',
        201
    )


# ── GET /help-requests ─────────────────────────────────────────────────────────
@help_bp.route('/help-requests', methods=['GET'])
@require_any_role(['reporter', 'volunteer', 'ngo', 'admin'])
def get_help_requests():
    uid  = int(get_jwt_identity())
    user = db.get_or_404(User, uid)

    if user.role == 'admin':
        # Admins see ALL requests
        reqs = HelpRequest.query.order_by(HelpRequest.created_at.desc()).all()

    elif user.role in ('volunteer', 'ngo'):
        # Volunteers and NGOs see all pending requests sorted by priority
        from sqlalchemy import case as sa_case
        priority_order = sa_case(
            (HelpRequest.priority_level == 'High',   1),
            (HelpRequest.priority_level == 'Medium', 2),
            else_=3
        )
        reqs = (
            HelpRequest.query
            .filter_by(status='Pending')
            .order_by(priority_order, HelpRequest.created_at.asc())
            .all()
        )

    else:
        # Reporters see only their own requests
        reqs = (
            HelpRequest.query
            .filter_by(user_id=uid)
            .order_by(HelpRequest.created_at.desc())
            .all()
        )

    return _success({'requests': [request_view(r, user) for r in reqs], 'total': len(reqs)})


# ── GET /help-request/<id> ─────────────────────────────────────────────────────
@help_bp.route('/help-request/<int:req_id>', methods=['GET'])
@require_any_role(['reporter', 'volunteer', 'ngo', 'admin'])
def get_help_request(req_id):
    uid  = int(get_jwt_identity())
    user = db.get_or_404(User, uid)
    req  = db.get_or_404(HelpRequest, req_id)

    # Reporters are owner-scoped. Volunteers may preview pending SOS records
    # and view their own assignments. NGO coordination uses redacted previews.
    if (user.role == 'reporter' and req.user_id != uid) or (
        user.role == 'volunteer' and req.status != 'Pending' and not can_view_private_request(user, req)
    ):
        return _error('You do not have permission to view this request', 403)

    return _success({'request': request_view(req, user)})


# ── PUT /help-request/status ───────────────────────────────────────────────────
@help_bp.route('/help-request/status', methods=['PUT'])
@require_any_role(['volunteer', 'admin'])  # Reporters cannot change status
def update_request_status():
    uid  = int(get_jwt_identity())
    user = db.get_or_404(User, uid)
    data   = request.get_json(silent=True) or {}
    req_id = data.get('request_id')
    status = data.get('status', '').strip()

    valid_statuses = ('Pending', 'Accepted', 'En Route', 'On Site', 'Completed', 'Duplicate')
    if status not in valid_statuses:
        return _error(f'status must be one of {valid_statuses}')

    if type(req_id) is not int or req_id <= 0:
        return _error('request_id must be a positive integer')
    if status == 'Completed':
        return _error('Completion requires admin approval through the task proof review endpoint.', 403)
    req = db.get_or_404(HelpRequest, req_id)
    tasks = ReliefTask.query.filter(ReliefTask.request_id == req_id,
                                    ReliefTask.status.in_(ACTIVE_TASK_STATES)).all()
    task = tasks[0] if len(tasks) == 1 else None
    if user.role == 'volunteer' and (task is None or task.volunteer.user_id != uid):
        return _error('You can only update your active assigned request.', 403)
    try:
        if task:
            expected = {'Assigned': 'En Route', 'En Route': 'On Site'}
            if status != expected.get(task.status):
                return _error('Allowed progress is Accepted → En Route → On Site. Use proof upload and admin review for completion.', 409)
            transition(task, status, status)
        elif not tasks and user.role == 'admin' and (req.status, status) in {
            ('Pending', 'Duplicate'), ('Duplicate', 'Pending')
        }:
            changed = db.session.execute(update(HelpRequest).where(
                HelpRequest.request_id == req_id, HelpRequest.status == req.status
            ).values(status=status)).rowcount
            if changed != 1:
                raise TransitionConflict('Request changed. Refresh and try again.')
        else:
            return _error('This request cannot make that transition. Acceptance requires a volunteer assignment.', 409)
        db.session.commit()
    except (TransitionConflict, SQLAlchemyError) as exc:
        db.session.rollback()
        return _error(str(exc) if isinstance(exc, TransitionConflict) else 'Progress could not be saved. Please retry.',
                      409 if isinstance(exc, TransitionConflict) else 503)
    return _success({'request': req.to_dict()}, 'Status updated')
