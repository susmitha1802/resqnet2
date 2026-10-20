import math
import re
from datetime import datetime, timezone, timedelta
from flask import Blueprint, jsonify, request
from sqlalchemy import or_
from models import WeatherAlert, DisasterReport
from map_provenance import demo_alert, demo_incident

map_risk_bp = Blueprint('map_risk', __name__)

def haversine(lat1, lon1, lat2, lon2):
    R = 6371  # Earth radius in kilometers
    dlat = math.radians(lat2 - lat1)
    dlon = math.radians(lon2 - lon1)
    a = math.sin(dlat / 2)**2 + math.cos(math.radians(lat1)) * math.cos(math.radians(lat2)) * math.sin(dlon / 2)**2
    c = 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))
    return R * c

def count_recent_reports(lat, lng, radius_km):
    thirty_days_ago = datetime.now(timezone.utc) - timedelta(days=30)
    reports = DisasterReport.query.filter(DisasterReport.created_at >= thirty_days_ago).all()
    count = 0
    for r in reports:
        if demo_incident(r, 'report'):
            continue
        if r.latitude is not None and r.longitude is not None:
            dist = haversine(float(lat), float(lng), float(r.latitude), float(r.longitude))
            if dist <= float(radius_km):
                count += 1
    return count

def parse_weather_from_desc(description):
    wind_match = re.search(r'wind\s+([\d\.]+)\s*m/s', description)
    rain_match = re.search(r'rain\s+([\d\.]+)\s*mm', description)
    wind_ms = float(wind_match.group(1)) if wind_match else 0
    rain_mm = float(rain_match.group(1)) if rain_match else 0
    return wind_ms, rain_mm

def compute_risk_score(lat, lng, radius_km, severity, description):
    wind_ms, rain_mm = parse_weather_from_desc(description)
    
    base_score = 0
    if rain_mm > 70 and wind_ms > 16.6:
        base_score = 3
    elif rain_mm > 70:
        base_score = 2
    elif rain_mm > 10:
        base_score = 1
    else:
        if severity == 'Emergency': base_score = 3
        elif severity == 'Warning': base_score = 2
        elif severity == 'Watch': base_score = 1
        else: base_score = 0

    # Keyword boosts
    desc_lower = description.lower() if description else ""
    if 'heavy rain' in desc_lower or 'cyclone' in desc_lower or 'flood' in desc_lower or 'high wind' in desc_lower:
        base_score = max(base_score, 2)
        if 'cyclone' in desc_lower: 
            base_score = 3

    recent_reports = count_recent_reports(lat, lng, radius_km)
    report_bump = min(recent_reports // 5, 1)
    
    final_score = min(base_score + report_bump, 3)
    
    if final_score >= 3:   return "High"
    elif final_score >= 2: return "Medium"
    elif final_score >= 1: return "Low"
    else:                  return "Safe"

@map_risk_bp.route('/map/risk-zones', methods=['GET'])
def get_risk_zones():
    now = datetime.now(timezone.utc)
    active_alerts = WeatherAlert.query.filter(
        or_(WeatherAlert.expires_at == None, WeatherAlert.expires_at > now)
    ).all()
    
    zones = []
    for alert in active_alerts:
        is_demo = demo_alert(alert)
        if is_demo and request.args.get('include_demo') != '1':
            continue
        metadata = alert.to_dict()
        risk_level = compute_risk_score(float(alert.affected_lat), float(alert.affected_lng), float(alert.affected_radius_km), alert.severity, alert.description)
        zones.append({
            "alert_id": alert.alert_id,
            "alert_type": alert.alert_type,
            "severity": alert.severity,
            "risk_level": risk_level,
            "lat": float(alert.affected_lat),
            "lng": float(alert.affected_lng),
            "radius_km": alert.affected_radius_km,
            "description": metadata['description'],
            "source": metadata['source'],
            "is_demo": is_demo,
            "status": 'Demo scenario' if is_demo else 'Active alert',
            "risk_basis": 'Rule-based estimate; not an official warning or verified forecast',
            "issued_at": metadata['issued_at'],
            "expires_at": metadata['expires_at'],
        })
        
    return jsonify({"zones": zones})
