"""
ResQNet — Weather Alert Routes
GET  /alerts                  — list active alerts
POST /alerts                  — admin creates manual alert
POST /alerts/fetch            — admin triggers OpenWeatherMap pull
PUT  /alerts/<id>/notify      — admin sends preparedness pings to nearby volunteers+NGOs
GET  /alerts/<id>/responses   — see ping acknowledgements
GET  /preparedness/my-pings   — volunteer/NGO sees their pings
PUT  /preparedness/ping/<id>  — volunteer/NGO acknowledges or marks unavailable
"""
import os, math, urllib.request, json
from datetime import datetime, timezone
from flask import Blueprint, request, jsonify
from flask_jwt_extended import jwt_required, get_jwt_identity
from routes.middleware import require_role
from extensions import db
from models import User, WeatherAlert, PreparednessPing
from map_provenance import demo_alert, demo_alert_filter
from sqlalchemy import or_

alerts_bp = Blueprint('alerts', __name__)

DEFAULT_LAT = 20.5937
DEFAULT_LNG = 78.9629
OWM_KEY = os.getenv('OPENWEATHER_API_KEY', '')


def _coordinates():
    lat = float(request.args.get('lat', DEFAULT_LAT))
    lng = float(request.args.get('lng', DEFAULT_LNG))
    if not math.isfinite(lat) or not math.isfinite(lng) or not -90 <= lat <= 90 or not -180 <= lng <= 180:
        raise ValueError('Invalid coordinates')
    return lat, lng

def _haversine_km(lat1, lng1, lat2, lng2):
    R = 6371
    dlat = math.radians(lat2 - lat1)
    dlng = math.radians(lng2 - lng1)
    a = math.sin(dlat/2)**2 + math.cos(math.radians(lat1))*math.cos(math.radians(lat2))*math.sin(dlng/2)**2
    return R * 2 * math.asin(math.sqrt(a))

def _users_in_radius(lat, lng, radius_km):
    users = User.query.filter(User.role.in_(['volunteer','ngo'])).all()
    result = []
    for u in users:
        if u.location:
            try:
                parts = u.location.split(',')
                ulat, ulng = float(parts[0]), float(parts[1])
                if _haversine_km(lat, lng, ulat, ulng) <= radius_km:
                    result.append(u)
            except:
                pass
    return result

# ── GET /alerts ────────────────────────────────────────────────────────────────
@alerts_bp.route('/alerts', methods=['GET'])
def list_alerts():
    query = WeatherAlert.query.filter(or_(WeatherAlert.expires_at.is_(None),
        WeatherAlert.expires_at > datetime.now(timezone.utc)))
    if request.args.get('include_demo') != '1':
        query = query.filter(~demo_alert_filter(WeatherAlert))
    alerts = query.order_by(WeatherAlert.issued_at.desc()).limit(20).all()
    return jsonify({'success': True, 'alerts': [a.to_dict() for a in alerts]}), 200

# ── POST /alerts ───────────────────────────────────────────────────────────────
@alerts_bp.route('/alerts', methods=['POST'])
@jwt_required()
def create_alert():
    uid = get_jwt_identity()
    user = User.query.get(uid)
    if not user or user.role != 'admin':
        return jsonify({'success': False, 'message': 'Admin only'}), 403
    data = request.get_json() or {}
    if (data.get('alert_type', 'Other') not in {'Cyclone', 'Flood', 'Heatwave', 'Storm', 'Earthquake', 'Other'}
            or data.get('severity', 'Watch') not in {'Watch', 'Warning', 'Emergency'}
            or not isinstance(data.get('description'), str) or not data['description'].strip()
            or len(data['description']) > 4000):
        return jsonify(success=False, message='A valid alert type, severity and description are required.'), 400
    try:
        lat = float(data.get('affected_lat', DEFAULT_LAT)); lng = float(data.get('affected_lng', DEFAULT_LNG))
        radius = data.get('affected_radius_km', 50)
        if not math.isfinite(lat) or not math.isfinite(lng) or not -90 <= lat <= 90 or not -180 <= lng <= 180:
            raise ValueError()
        if type(radius) is not int or not 1 <= radius <= 500:
            raise ValueError()
    except (TypeError, ValueError):
        return jsonify(success=False, message='Valid coordinates and a radius from 1 to 500 km are required.'), 400
    alert = WeatherAlert(
        alert_type         = data.get('alert_type', 'Other'),
        description        = data.get('description', ''),
        affected_lat       = lat,
        affected_lng       = lng,
        severity           = data.get('severity', 'Watch'),
        source             = 'Manual',
        affected_radius_km = radius,
    )
    db.session.add(alert)
    db.session.commit()
    return jsonify({'success': True, 'alert': alert.to_dict()}), 201

# ── GET /weather/live ──────────────────────────────────────────────────────────
@alerts_bp.route('/weather/live', methods=['GET'])
def live_weather():
    try:
        lat, lng = _coordinates()
    except (TypeError, ValueError):
        return jsonify(success=False, message='Valid latitude and longitude are required.'), 400
    owm_key = os.getenv('OPENWEATHER_API_KEY', '')
    if not owm_key:
        return jsonify({'success': False, 'message': 'Weather service is not configured.'}), 503

    try:
        cur_url = f'https://api.openweathermap.org/data/2.5/weather?lat={lat}&lon={lng}&appid={owm_key}&units=metric'
        req = urllib.request.Request(cur_url, headers={'User-Agent': 'Mozilla/5.0'})
        with urllib.request.urlopen(req, timeout=8) as response:
            cur_resp = json.loads(response.read().decode('utf-8'))
        
        fc_url = f'https://api.openweathermap.org/data/2.5/forecast?lat={lat}&lon={lng}&appid={owm_key}&units=metric'
        req_fc = urllib.request.Request(fc_url, headers={'User-Agent': 'Mozilla/5.0'})
        with urllib.request.urlopen(req_fc, timeout=8) as response_fc:
            fc_data = json.loads(response_fc.read().decode('utf-8'))
        
        daily = {}
        for item in fc_data.get('list', []):
            dt_txt = item.get('dt_txt', '').split(' ')[0]
            if dt_txt not in daily:
                daily[dt_txt] = item
        forecast_list = list(daily.values())[:5]

        return jsonify({
            'success': True, 
            'current': cur_resp,
            'forecast': forecast_list
        }), 200
    except Exception:
        return jsonify({'success': False, 'message': 'Weather provider unavailable. Please retry.'}), 502

# ── POST /alerts/fetch ─────────────────────────────────────────────────────────
@alerts_bp.route('/alerts/fetch', methods=['POST'])
@jwt_required()
def fetch_owm_alerts():
    uid = get_jwt_identity()
    user = User.query.get(uid)
    if not user or user.role != 'admin':
        return jsonify({'success': False, 'message': 'Admin only'}), 403
    
    owm_key = os.getenv('OPENWEATHER_API_KEY', '')
    if not owm_key:
        return jsonify({'success': False, 'message': 'Weather service is not configured.'}), 503

    try:
        lat, lng = _coordinates()
    except (TypeError, ValueError):
        return jsonify(success=False, message='Valid latitude and longitude are required.'), 400
    url = f'https://api.openweathermap.org/data/2.5/weather?lat={lat}&lon={lng}&appid={owm_key}&units=metric'
    try:
        req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
        with urllib.request.urlopen(req, timeout=8) as response:
            data = json.loads(response.read().decode('utf-8'))
        
        fc_url = f'https://api.openweathermap.org/data/2.5/forecast?lat={lat}&lon={lng}&appid={owm_key}&units=metric'
        req_fc = urllib.request.Request(fc_url, headers={'User-Agent': 'Mozilla/5.0'})
        with urllib.request.urlopen(req_fc, timeout=8) as response_fc:
            fc_data = json.loads(response_fc.read().decode('utf-8'))
    except Exception:
        return jsonify({'success': False, 'message': 'Weather provider unavailable. Please retry.'}), 502

    weather_main = data.get('weather', [{}])[0].get('main', '').lower()
    weather_desc = data.get('weather', [{}])[0].get('description', 'Weather alert')
    temp = data.get('main', {}).get('temp', 0)
    wind = data.get('wind', {}).get('speed', 0)
    rain = data.get('rain', {}).get('1h', 0)

    alert_type = 'Other'
    severity = 'Watch'

    if 'thunder' in weather_main or 'storm' in weather_main:
        alert_type, severity = 'Storm', 'Warning'
    elif 'rain' in weather_main or rain > 50:
        alert_type, severity = 'Flood', 'Watch'
    elif temp > 42:
        alert_type, severity = 'Heatwave', 'Warning'
    elif wind > 20:
        alert_type, severity = 'Cyclone', 'Watch'
    else:
        max_rain = 0
        max_wind = 0
        for item in fc_data.get('list', [])[:16]:
            f_rain = item.get('rain', {}).get('3h', 0) / 3.0
            f_wind = item.get('wind', {}).get('speed', 0)
            max_rain = max(max_rain, f_rain)
            max_wind = max(max_wind, f_wind)
        
        if max_rain > 70 or max_wind > 16.6:
            if max_rain > 70 and max_wind > 16.6:
                alert_type, severity = 'Cyclone', 'Watch'
                weather_desc = 'Forecast: Heavy Rain & High Winds'
            elif max_rain > 70:
                alert_type, severity = 'Flood', 'Watch'
                weather_desc = 'Forecast: Heavy Rain Warning'
            else:
                alert_type, severity = 'Storm', 'Watch'
                weather_desc = 'Forecast: High Wind Warning'
        else:
            return jsonify({'success': True, 'message': 'No alert threshold reached in this weather response. Ground conditions remain unconfirmed.'}), 200

    alert = WeatherAlert(
        alert_type=alert_type,
        description=f'OWM: {weather_desc}, temp {temp}°C, wind {wind}m/s, rain {rain}mm',
        affected_lat=lat,
        affected_lng=lng,
        severity=severity,
        source='OpenWeatherMap',
    )
    db.session.add(alert)
    db.session.commit()
    return jsonify({'success': True, 'alert': alert.to_dict()}), 201

# ── PUT /alerts/<id>/notify ────────────────────────────────────────────────────
@alerts_bp.route('/alerts/<int:alert_id>/notify', methods=['PUT'])
@jwt_required()
def notify_responders(alert_id):
    uid = get_jwt_identity()
    user = User.query.get(uid)
    if not user or user.role != 'admin':
        return jsonify({'success': False, 'message': 'Admin only'}), 403
    alert = WeatherAlert.query.get_or_404(alert_id)
    if demo_alert(alert):
        return jsonify({'success': False, 'message': 'Demo alerts cannot send live preparedness notifications.'}), 409
    if alert.expires_at and alert.expires_at.replace(tzinfo=timezone.utc) <= datetime.now(timezone.utc):
        return jsonify(success=False, message='Expired alerts cannot notify responders.'), 409
    nearby = _users_in_radius(float(alert.affected_lat), float(alert.affected_lng), alert.affected_radius_km)
    count = 0
    for u in nearby:
        exists = db.session.query(PreparednessPing.ping_id).filter_by(alert_id=alert_id, user_id=u.user_id).first()
        if not exists:
            db.session.add(PreparednessPing(alert_id=alert_id, user_id=u.user_id))
            count += 1
    alert.notified_at = datetime.now(timezone.utc)
    db.session.commit()
    return jsonify({'success': True, 'pings_sent': count}), 200

# ── GET /alerts/<id>/responses ─────────────────────────────────────────────────
@alerts_bp.route('/alerts/<int:alert_id>/responses', methods=['GET'])
@require_role('admin')
def alert_responses(alert_id):
    pings = PreparednessPing.query.filter_by(alert_id=alert_id).filter(
        PreparednessPing.status.in_(['Sent', 'Acknowledged', 'Unavailable'])
    ).all()
    return jsonify({'success': True, 'responses': [p.to_dict() for p in pings]}), 200
