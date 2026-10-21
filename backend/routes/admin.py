"""
ResQNet — Admin Routes Blueprint
GET /admin/dashboard   — dashboard stats (admin only)
GET /admin/analytics   — analytics breakdown (admin only)
GET /admin/reports     — paginated disaster reports (admin only)
GET /admin/requests    — paginated help requests (admin only)
GET /admin/volunteers  — list all volunteers (admin only)
GET /admin/users       — list all users with roles (admin only)
"""
from flask import Blueprint, request, jsonify
from flask_jwt_extended import get_jwt_identity
from sqlalchemy import func, update
from sqlalchemy.exc import SQLAlchemyError
from datetime import datetime, timedelta, timezone

from extensions import db
from models import User, HelpRequest, DisasterReport, Volunteer, ReliefTask, ReliefResource
from access import request_view, report_view
from routes.middleware import require_role
from sos_lifecycle import TransitionConflict, transition, proof_available, ACTIVE_TASK_STATES

admin_bp = Blueprint('admin', __name__)


def _success(data=None, message='OK', status=200):
    return jsonify({'success': True, 'message': message, **(data or {})}), status


def _error(message='Error', status=400):
    return jsonify({'success': False, 'message': message}), status


# ── GET /admin/dashboard ───────────────────────────────────────────────────────
@admin_bp.route('/admin/dashboard', methods=['GET'])
@require_role('admin')
def admin_dashboard():
    stats = {
        'total_requests':    HelpRequest.query.count(),
        'high_priority':     HelpRequest.query.filter_by(priority_level='High').count(),
        'active_volunteers': Volunteer.query.filter_by(availability_status='available').count(),
        'busy_volunteers':   Volunteer.query.filter_by(availability_status='on_task').count(),
        'completed_tasks':   ReliefTask.query.filter_by(status='Completed').count(),
        'completed':         HelpRequest.query.filter_by(status='Completed').count(),
        'pending':           HelpRequest.query.filter_by(status='Pending').count(),
        'accepted':          HelpRequest.query.filter_by(status='Accepted').count(),
        'duplicate':         HelpRequest.query.filter_by(is_duplicate=True).count(),
        'disaster_reports':  DisasterReport.query.count(),
        'total_volunteers':  Volunteer.query.count(),
        'total_victims':     User.query.filter_by(role='reporter').count(),
        'total_ngos':        User.query.filter_by(role='ngo').count(),
        'relief_tasks':      ReliefTask.query.count(),
    }

    recent_high = (
        HelpRequest.query
        .filter_by(priority_level='High', status='Pending')
        .order_by(HelpRequest.created_at.desc())
        .limit(5).all()
    )

    return _success({
        'stats':       stats,
        'recent_high': [request_view(r, db.session.get(User, int(get_jwt_identity()))) for r in recent_high],
    })


# ── GET /admin/analytics ───────────────────────────────────────────────────────
@admin_bp.route('/admin/analytics', methods=['GET'])
@require_role('admin')
def admin_analytics():
    by_type = (
        db.session.query(HelpRequest.request_type, func.count(HelpRequest.request_id))
        .group_by(HelpRequest.request_type).all()
    )
    by_status = (
        db.session.query(HelpRequest.status, func.count(HelpRequest.request_id))
        .group_by(HelpRequest.status).all()
    )
    by_priority = (
        db.session.query(HelpRequest.priority_level, func.count(HelpRequest.request_id))
        .group_by(HelpRequest.priority_level).all()
    )
    by_disaster = (
        db.session.query(DisasterReport.disaster_type, func.count(DisasterReport.report_id))
        .group_by(DisasterReport.disaster_type).all()
    )

    # Users by role breakdown
    by_role = (
        db.session.query(User.role, func.count(User.user_id))
        .group_by(User.role).all()
    )

    # DateTime columns store UTC without a timezone. SQLite CAST(... AS DATE)
    # returns the year as an integer, which SQLAlchemy's Date decoder rejects.
    # date() groups by the full calendar date on SQLite and PostgreSQL.
    seven_days_ago = datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(days=7)
    day = func.date(HelpRequest.created_at).label('day')
    by_day = (
        db.session.query(
            day,
            func.count(HelpRequest.request_id)
        )
        .filter(HelpRequest.created_at >= seven_days_ago)
        .group_by(day).order_by(day).all()
    )

    return _success({
        'by_type':     {t: c for t, c in by_type},
        'by_status':   {s: c for s, c in by_status},
        'by_priority': {p: c for p, c in by_priority},
        'by_disaster': {d: c for d, c in by_disaster},
        'by_role':     {r: c for r, c in by_role},
        'by_day':      [{'day': str(d), 'count': c} for d, c in by_day],
    })


# ── GET /admin/reports ─────────────────────────────────────────────────────────
@admin_bp.route('/admin/reports', methods=['GET'])
@require_role('admin')
def admin_reports():
    dtype  = request.args.get('type')
    limit  = min(int(request.args.get('limit', 100)), 500)
    offset = int(request.args.get('offset', 0))

    query = DisasterReport.query.order_by(DisasterReport.created_at.desc())
    if dtype:
        query = query.filter_by(disaster_type=dtype)

    total   = query.count()
    reports = query.offset(offset).limit(limit).all()

    return _success({'reports': [report_view(r, r.user) for r in reports], 'total': total,
                     'limit': limit, 'offset': offset})


# ── GET /admin/requests ────────────────────────────────────────────────────────
@admin_bp.route('/admin/requests', methods=['GET'])
@require_role('admin')
def admin_requests():
    priority = request.args.get('priority')
    status   = request.args.get('status')
    limit    = min(int(request.args.get('limit', 100)), 500)
    offset   = int(request.args.get('offset', 0))

    query = HelpRequest.query.order_by(HelpRequest.created_at.desc())
    if priority:
        query = query.filter_by(priority_level=priority)
    if status:
        query = query.filter_by(status=status)

    total    = query.count()
    requests = query.offset(offset).limit(limit).all()

    return _success({'requests': [request_view(r, r.user) for r in requests], 'total': total,
                     'limit': limit, 'offset': offset})


# ── GET /admin/volunteers ──────────────────────────────────────────────────────
@admin_bp.route('/admin/volunteers', methods=['GET'])
@require_role('admin')
def admin_volunteers():
    volunteers = Volunteer.query.all()
    return _success({'volunteers': [v.to_dict() for v in volunteers], 'total': len(volunteers)})


# ── GET /admin/users ───────────────────────────────────────────────────────────
@admin_bp.route('/admin/users', methods=['GET'])
@require_role('admin')
def admin_users():
    """List all registered users with their roles."""
    role_filter = request.args.get('role')
    query = User.query.order_by(User.created_at.desc())
    if role_filter:
        query = query.filter_by(role=role_filter)
    users = query.all()
    return _success({
        'users': [u.to_dict() for u in users],
        'total': len(users),
    })


@admin_bp.route('/admin/resources', methods=['GET'])
@require_role('admin')
def admin_resources():
    """Read-only inventory and allocation overview for coordinators."""
    try:
        limit = int(request.args.get('limit', 100))
        offset = int(request.args.get('offset', 0))
    except ValueError:
        return _error('Invalid resource page')
    if not 1 <= limit <= 500 or offset < 0:
        return _error('Invalid resource page')
    resources = ReliefResource.query.order_by(ReliefResource.added_at.desc(),
                                              ReliefResource.resource_id.desc()).offset(offset).limit(limit).all()
    return _success({'resources': [{**r.to_dict(),
                                   'ngo_name': r.added_by_user.location or r.added_by_user.name}
                                  for r in resources], 'total': ReliefResource.query.count(),
                     'limit': limit, 'offset': offset})


# ── GET /admin/pending-verifications ───────────────────────────────────────────
@admin_bp.route('/admin/pending-verifications', methods=['GET'])
@require_role('admin')
def pending_verifications():
    tasks = ReliefTask.query.filter_by(verification_status='Pending', status='Proof Submitted').all()
    return _success({'verifications': [t.to_dict() for t in tasks]})


# ── PUT /admin/verify-task/<task_id> ───────────────────────────────────────────
@admin_bp.route('/admin/verify-task/<int:task_id>', methods=['PUT'])
@require_role('admin')
def verify_task(task_id):
    uid  = int(get_jwt_identity())
    data = request.get_json(silent=True) or {}
    action = data.get('action') # 'Approve' or 'Reject'

    task = ReliefTask.query.get_or_404(task_id)

    if action not in ('Approve', 'Reject'):
        return _error('Invalid action')
    if task.status != 'Proof Submitted' or task.verification_status != 'Pending':
        return _error('Task is not awaiting proof verification. Refresh the review list.', 409)
    if action == 'Approve':
        try:
            available = proof_available(task.proof_image_path)
        except OSError:
            return _error('Proof storage is unavailable. Please retry.', 503)
        if not available:
            return _error('Proof image is unavailable. Completion cannot be approved without stored proof.', 409)
    try:
        approved = action == 'Approve'
        transition(task, 'Completed' if approved else 'On Site', 'Completed' if approved else 'On Site',
                   verification_status='Approved' if approved else 'Rejected', verified_by_admin_id=int(uid),
                   completed_at=datetime.now(timezone.utc) if approved else None)
        other_active = ReliefTask.query.filter(
            ReliefTask.volunteer_id == task.volunteer_id, ReliefTask.task_id != task.task_id,
            ReliefTask.status.in_(ACTIVE_TASK_STATES)
        ).first()
        values = {'availability_status': 'available' if approved and not other_active else 'on_task'}
        if approved:
            values['completed_tasks'] = Volunteer.completed_tasks + 1
        db.session.execute(update(Volunteer).where(Volunteer.volunteer_id == task.volunteer_id).values(**values))
        task.volunteer.user.availability = 'available' if approved and not other_active else 'unavailable'
        db.session.commit()
    except (TransitionConflict, SQLAlchemyError) as exc:
        db.session.rollback()
        return _error(str(exc) if isinstance(exc, TransitionConflict) else 'Review could not be saved. Please retry.',
                      409 if isinstance(exc, TransitionConflict) else 503)
    return _success({'task': task.to_dict()}, f'Task {action.lower()}d successfully')


# ── PUT /admin/report/<report_id>/override ─────────────────────────────────────
@admin_bp.route('/admin/report/<int:report_id>/override', methods=['PUT'])
@require_role('admin')
def override_report(report_id):
    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        return _error('A JSON object with disaster_type is required')
    new_type = data.get('disaster_type')
    valid_types = DisasterReport.__table__.c.disaster_type.type.enums
    if not isinstance(new_type, str) or new_type.strip() not in valid_types:
        return _error('disaster_type must be one of: ' + ', '.join(valid_types))

    try:
        report = db.get_or_404(DisasterReport, report_id)
        report.disaster_type = new_type.strip()
        db.session.flush()
        report_data = report_view(report, report.user)
        db.session.commit()
    except SQLAlchemyError:
        db.session.rollback()
        return _error('Report override could not be saved. Please retry.', 503)
    return _success({'report': report_data}, 'Report overridden successfully')
