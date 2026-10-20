"""
ResQNet — Disaster Reports Routes Blueprint
POST /report-disaster
GET  /reports
GET  /report/<id>
"""
import os
from flask import Blueprint, request, jsonify, current_app
from flask_jwt_extended import jwt_required, get_jwt_identity
from werkzeug.utils import secure_filename

from access import report_view
from routes.middleware import require_auth, _get_current_user
from extensions import db
from models import DisasterReport
from ai.severity import classify_severity

reports_bp = Blueprint('reports', __name__)


def _success(data=None, message='OK', status=200):
    return jsonify({'success': True, 'message': message, **(data or {})}), status


def _error(message='Error', status=400):
    return jsonify({'success': False, 'message': message}), status


def _save_file(file_obj, subfolder: str) -> str | None:
    from private_uploads import save_incident_image
    return save_incident_image(file_obj, subfolder)


# ── POST /report-disaster ──────────────────────────────────────────────────────
@reports_bp.route('/report-disaster', methods=['POST'])
@require_auth
def report_disaster():
    uid  = int(get_jwt_identity())
    data = request.form

    disaster_type = data.get('disaster_type', '').strip()
    description   = data.get('description', '').strip()
    latitude      = data.get('latitude')
    longitude     = data.get('longitude')

    if not all([disaster_type, description, latitude, longitude]):
        return _error('disaster_type, description, latitude, and longitude are required')

    if len(description) > 2000:
        return _error('Description must be 2000 characters or fewer')

    # Save image (first file if multiple)
    img_path = None
    if 'images' in request.files:
        img_path = _save_file(request.files['images'], 'reports')
        if not img_path:
            return _error('Uploaded image format is not supported or file is invalid', 400)

    severity = classify_severity(image_path=img_path, disaster_type=disaster_type)

    report = DisasterReport(
        user_id                 = uid,
        disaster_type           = disaster_type,
        description             = description,
        image_path              = img_path,
        predicted_disaster_type = disaster_type,
        prediction_confidence   = None,
        severity                = severity,
        latitude                = float(latitude),  # type: ignore
        longitude               = float(longitude), # type: ignore
    )
    db.session.add(report)
    db.session.commit()

    return _success(
        {
            'report':   report_view(report, _get_current_user()),
            'severity': severity,
            'ai_note':  None,
        },
        'Disaster report submitted successfully',
        201
    )


# ── GET /reports ───────────────────────────────────────────────────────────────
@reports_bp.route('/reports', methods=['GET'])
@require_auth
def get_reports():
    disaster_type = request.args.get('type')
    query = DisasterReport.query.order_by(DisasterReport.created_at.desc())
    user = _get_current_user()
    if user.role == 'reporter':
        query = query.filter_by(user_id=user.user_id)
    if disaster_type:
        query = query.filter_by(disaster_type=disaster_type)
    reports = query.limit(100).all()
    return _success({'reports': [report_view(r, _get_current_user()) for r in reports], 'total': len(reports)})


# ── GET /report/<id> ───────────────────────────────────────────────────────────
@reports_bp.route('/report/<int:report_id>', methods=['GET'])
@require_auth
def get_report(report_id):
    report = db.get_or_404(DisasterReport, report_id)
    user = _get_current_user()
    if user.role == 'reporter' and report.user_id != user.user_id:
        return _error('You do not have permission to view this report', 403)
    return _success({'report': report_view(report, _get_current_user())})
