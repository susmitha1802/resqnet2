"""
ResQNet — Volunteer Routes Blueprint
GET /volunteer/tasks           — get assigned tasks (volunteer only)
PUT /volunteer/accept-task     — accept a pending request (volunteer only)
PUT /volunteer/update-status   — update availability (volunteer only)
PUT /volunteer/complete-task   — complete an active task (volunteer only)
"""
from flask import Blueprint, request, jsonify, send_file
from flask_jwt_extended import get_jwt_identity
from sqlalchemy import update
from sqlalchemy.exc import SQLAlchemyError

from extensions import db
from models import HelpRequest, Volunteer, ReliefTask, User
from routes.middleware import require_role, require_any_role
from sos_lifecycle import (TransitionConflict, transition, ensure_active,
                           save_proof, proof_file, ACTIVE_TASK_STATES)

volunteers_bp = Blueprint('volunteers', __name__)


def _success(data=None, message='OK', status=200):
    return jsonify({'success': True, 'message': message, **(data or {})}), status


def _error(message='Error', status=400):
    return jsonify({'success': False, 'message': message}), status

def _get_volunteer(uid: int) -> Volunteer | None:
    """Helper — return volunteer record for the current user or None."""
    return Volunteer.query.filter_by(user_id=uid).first()


# ── GET /volunteer/tasks ───────────────────────────────────────────────────────
@volunteers_bp.route('/volunteer/tasks', methods=['GET'])
@require_role('volunteer')
def get_volunteer_tasks():
    uid = int(get_jwt_identity())
    vol = _get_volunteer(uid)
    if not vol:
        return _error('You are not registered as a volunteer', 403)

    tasks = (
        ReliefTask.query
        .filter_by(volunteer_id=vol.volunteer_id)
        .order_by(ReliefTask.assigned_at.desc())
        .all()
    )
    return _success({'tasks': [t.to_dict() for t in tasks], 'total': len(tasks)})


# ── PUT /volunteer/accept-task ─────────────────────────────────────────────────
@volunteers_bp.route('/volunteer/accept-task', methods=['PUT'])
@require_role('volunteer')
def accept_task():
    uid  = int(get_jwt_identity())
    data = request.get_json(silent=True) or {}
    req_id = data.get('request_id')

    if type(req_id) is not int or req_id <= 0:
        return _error('request_id must be a positive integer')

    vol = _get_volunteer(uid)
    if not vol:
        return _error('You are not registered as a volunteer', 403)

    req = db.get_or_404(HelpRequest, req_id)
    if req.status != 'Pending':
        return _error(f'Request is no longer available (current status: {req.status})', 409)

    active_task = ReliefTask.query.filter(
        ReliefTask.volunteer_id == vol.volunteer_id,
        ReliefTask.status.in_(['Assigned', 'En Route', 'On Site', 'Proof Submitted'])
    ).first()
    if active_task:
        return _error('You already have an active task. Complete it before accepting a new one.', 409)
    if vol.availability_status != 'available':
        return _error('Set your availability to available before accepting a task.', 409)

    # Claim both records conditionally in one transaction. A stale page or
    # simultaneous acceptance must not create a second assignment.
    claimed_volunteer = db.session.execute(
        update(Volunteer).where(
            Volunteer.volunteer_id == vol.volunteer_id,
            Volunteer.availability_status == 'available'
        ).values(availability_status='on_task', assigned_tasks=Volunteer.assigned_tasks + 1)
    ).rowcount
    claimed_request = db.session.execute(
        update(HelpRequest).where(
            HelpRequest.request_id == req_id, HelpRequest.status == 'Pending'
        ).values(status='Accepted')
    ).rowcount if claimed_volunteer == 1 else 0
    if claimed_volunteer != 1 or claimed_request != 1:
        db.session.rollback()
        return _error('Request or volunteer is no longer available. Refresh and try again.', 409)

    task = ReliefTask(volunteer_id=vol.volunteer_id, request_id=req_id, status='Assigned')

    db.session.add(task)
    db.session.commit()

    return _success({'task': task.to_dict(), 'request': req.to_dict()}, 'Task accepted successfully')


# ── PUT /volunteer/update-status ───────────────────────────────────────────────
@volunteers_bp.route('/volunteer/update-status', methods=['PUT'])
@require_role('volunteer')
def update_volunteer_status():
    uid  = int(get_jwt_identity())
    data = request.get_json(silent=True) or {}
    status = data.get('status', '').strip()

    valid = ('available', 'unavailable', 'on_task')
    if status not in valid:
        return _error(f'status must be one of {valid}')

    vol = _get_volunteer(uid)
    if not vol:
        return _error('You are not registered as a volunteer', 403)

    active = ReliefTask.query.filter(ReliefTask.volunteer_id == vol.volunteer_id,
                                     ReliefTask.status.in_(ACTIVE_TASK_STATES)).first()
    if active and status != 'on_task':
        return _error('Finish your assigned task and admin verification before changing availability.', 409)
    vol.availability_status = status
    db.session.commit()
    return _success({'volunteer': vol.to_dict()}, 'Availability updated')


# ── PUT /volunteer/update-location ─────────────────────────────────────────────
@volunteers_bp.route('/volunteer/update-location', methods=['PUT'])
@require_role('volunteer')
def update_volunteer_location():
    uid  = int(get_jwt_identity())
    data = request.get_json(silent=True) or {}
    lat  = data.get('latitude')
    lng  = data.get('longitude')

    if lat is None or lng is None:
        return _error('latitude and longitude are required')

    vol = _get_volunteer(uid)
    if not vol:
        return _error('You are not registered as a volunteer', 403)

    vol.last_location_lat = lat
    vol.last_location_lng = lng
    db.session.commit()
    return _success({'volunteer': vol.to_dict()}, 'Location updated')


# ── POST /volunteer/upload-proof/<task_id> ──────────────────────────────────
@volunteers_bp.route('/volunteer/upload-proof/<int:task_id>', methods=['POST'])
@require_role('volunteer')
def upload_proof(task_id):
    uid  = int(get_jwt_identity())
    data = request.form
    notes = data.get('notes', '')

    vol = _get_volunteer(uid)
    if not vol:
        return _error('You are not registered as a volunteer', 403)

    task = ReliefTask.query.filter_by(
        task_id=task_id, volunteer_id=vol.volunteer_id
    ).first_or_404()

    if task.status not in ('Assigned', 'En Route', 'On Site'):
        return _error('Only an active task can submit proof; pending or completed proof cannot be resubmitted.', 409)
    if len(notes) > 2000:
        return _error('Completion notes must be 2000 characters or fewer.')
    saved = None
    try:
        ensure_active(task)
        saved = save_proof(request.files.get('proof_image'))
        transition(task, 'Proof Submitted', 'On Site', proof_image_path=saved,
                   completion_notes=notes, verification_status='Pending', verified_by_admin_id=None)
        db.session.commit()
    except (TransitionConflict, ValueError, OSError, SQLAlchemyError) as exc:
        db.session.rollback()
        if saved:
            proof_file(saved).unlink(missing_ok=True)
        if isinstance(exc, TransitionConflict):
            return _error(str(exc), 409)
        if isinstance(exc, ValueError):
            return _error(str(exc), 400)
        return _error('Proof could not be saved. No task progress was changed; please retry.', 503)
    return _success({
        'task': task.to_dict()
    }, 'Proof uploaded successfully. Pending Admin verification.')


@volunteers_bp.get('/volunteer/tasks/<int:task_id>/proof')
@require_any_role(['admin', 'volunteer'])
def view_proof(task_id):
    task = db.get_or_404(ReliefTask, task_id)
    user = db.session.get(User, int(get_jwt_identity()))
    if user.role != 'admin' and task.volunteer.user_id != user.user_id:
        return _error('Access denied', 403)
    path = proof_file(task.proof_image_path)
    if path is None or not path.is_file():
        return _error('Proof image is unavailable', 404)
    response = send_file(path, mimetype='image/png' if path.suffix.lower() == '.png' else 'image/jpeg',
                         download_name='proof' + path.suffix.lower(), conditional=False)
    response.headers['Cache-Control'] = 'private, no-store'
    response.headers['X-Content-Type-Options'] = 'nosniff'
    return response
