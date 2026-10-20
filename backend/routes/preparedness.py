from datetime import datetime, timezone
from flask import Blueprint, request, jsonify
from flask_jwt_extended import jwt_required, get_jwt_identity
from extensions import db
from models import User, PreparednessPing, Volunteer, WeatherAlert
from routes.middleware import require_any_role
from map_provenance import demo_alert, demo_alert_filter
from sqlalchemy import or_, update

preparedness_bp = Blueprint('preparedness', __name__)

@preparedness_bp.route('/preparedness/my-pings', methods=['GET'])
@jwt_required()
@require_any_role(['volunteer', 'ngo'])
def get_my_pings():
    uid = get_jwt_identity()
    # Legacy demo rows may contain 'Pending', which is not in the model enum.
    # Exclude invalid records without silently migrating them during a read.
    pings = PreparednessPing.query.filter_by(user_id=uid).join(WeatherAlert).filter(
        PreparednessPing.status.in_(['Sent', 'Acknowledged', 'Unavailable']),
        ~demo_alert_filter(WeatherAlert),
        or_(WeatherAlert.expires_at.is_(None), WeatherAlert.expires_at > datetime.now(timezone.utc))
    ).order_by(PreparednessPing.sent_at.desc()).all()
    
    result = []
    pending_count = 0
    for ping in pings:
        if ping.status == 'Sent':
            pending_count += 1
        
        alert = ping.alert
        ping_dict = ping.to_dict()
        if alert:
            ping_dict.update({
                'alert_type': alert.alert_type,
                'severity': alert.severity,
                'description': alert.to_dict()['description'],
                'expires_at': alert.expires_at.isoformat() + 'Z' if alert.expires_at else None,
                'affected_lat': float(alert.affected_lat),
                'affected_lng': float(alert.affected_lng)
            })
        result.append(ping_dict)
        
    return jsonify({
        'success': True,
        'pings': result,
        'pending_count': pending_count
    }), 200

@preparedness_bp.route('/preparedness/ping/<int:ping_id>', methods=['PUT'])
@jwt_required()
@require_any_role(['volunteer', 'ngo'])
def respond_to_ping(ping_id):
    uid = get_jwt_identity()
    ping = PreparednessPing.query.filter_by(ping_id=ping_id).filter(
        PreparednessPing.status.in_(['Sent', 'Acknowledged', 'Unavailable'])
    ).first_or_404()
    
    if str(ping.user_id) != str(uid):
        return jsonify({'success': False, 'message': 'Forbidden'}), 403
    if demo_alert(ping.alert) or (ping.alert.expires_at and ping.alert.expires_at.replace(tzinfo=timezone.utc) <= datetime.now(timezone.utc)):
        return jsonify(success=False, message='This advisory is a demo or has expired.'), 409
        
    if ping.status != 'Sent':
        return jsonify({'success': False, 'message': 'Ping already responded to'}), 409
        
    data = request.get_json() or {}
    new_status = data.get('status')
    
    if new_status not in ('Acknowledged', 'Unavailable'):
        return jsonify({'success': False, 'message': 'Invalid status'}), 400
        
    changed = db.session.execute(update(PreparednessPing).where(
        PreparednessPing.ping_id == ping_id, PreparednessPing.user_id == int(uid), PreparednessPing.status == 'Sent'
    ).values(status=new_status, acknowledged_at=datetime.now(timezone.utc))).rowcount
    if changed != 1:
        db.session.rollback()
        return jsonify(success=False, message='Ping already responded to'), 409
    db.session.commit()
    
    return jsonify({'success': True, 'message': 'Ping responded successfully'}), 200

@preparedness_bp.route('/preparedness/summary', methods=['GET'])
@jwt_required()
@require_any_role(['admin'])
def preparedness_summary():
    vols_ready = Volunteer.query.filter_by(availability_status='available').count()
    vols_busy = Volunteer.query.filter_by(availability_status='on_task').count()
    vols_offline = Volunteer.query.filter_by(availability_status='unavailable').count()
    
    ngos_ready = User.query.filter_by(role='ngo', availability='available').count()
    ngos_offline = User.query.filter_by(role='ngo', availability='unavailable').count()
    
    return jsonify({
        'success': True,
        'volunteers': {
            'ready': vols_ready,
            'busy': vols_busy,
            'offline': vols_offline
        },
        'ngos': {
            'ready': ngos_ready,
            'offline': ngos_offline
        }
    }), 200
