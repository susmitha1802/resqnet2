"""Explicit demo provenance, including exact fingerprints of the legacy seed."""
from sqlalchemy import and_, or_
LEGACY_FLOOD_TEXT = 'Severe flash flooding expected in the Hyderabad region over the next 48 hours.'
LEGACY_REPORTS = {
    ('reporter1@resqnet.com', 'Major street flooding, water levels rising fast.', 17.4431, 78.45),
    ('reporter2@resqnet.com', 'River overflow near the main bridge.', 17.43, 78.44),
    ('vol1@resqnet.com', 'Electrical fire due to short circuit from rain.', 17.45, 78.435),
}
LEGACY_REQUESTS = {
    ('reporter1@resqnet.com', 'Alice Brown', 'Rescue', 17.4435, 78.4505),
    ('reporter2@resqnet.com', 'Bob White', 'Food', 17.432, 78.442),
    ('reporter1@resqnet.com', 'Alice Brown', 'Medicine', 17.444, 78.451),
    ('vol3@resqnet.com', 'Local Clinic', 'Water', 17.448, 78.458),
    ('reporter2@resqnet.com', 'Shelter Seeker', 'Shelter', 17.435, 78.445),
}


def demo_alert(alert):
    explicit = ((alert.source or '').lower().startswith(('demo', 'sample'))
                or (alert.description or '').startswith('[DEMO]'))
    legacy = (alert.source == 'OpenWeatherMap' and alert.description == LEGACY_FLOOD_TEXT
              and alert.alert_type == 'Flood' and alert.severity == 'Emergency'
              and float(alert.affected_lat) == 17.4401 and float(alert.affected_lng) == 78.4487
              and alert.affected_radius_km == 50)
    return explicit or legacy


def demo_alert_filter(model):
    """Equivalent SQL predicate so bounded alert lists filter before LIMIT."""
    return or_(model.source.ilike('demo%'), model.source.ilike('sample%'),
               model.description.like('[DEMO]%'), and_(
        model.source == 'OpenWeatherMap', model.description == LEGACY_FLOOD_TEXT,
        model.alert_type == 'Flood', model.severity == 'Emergency',
        model.affected_lat == 17.4401, model.affected_lng == 78.4487, model.affected_radius_km == 50))


def demo_incident(record, kind):
    if (record.description or '').startswith('[DEMO]'):
        return True
    email = record.user.email if record.user else None
    if (email or '').endswith('@resqnet-demo.invalid') and record.user.name.startswith('[DEMO] '):
        return True
    coords = (round(float(record.latitude), 6), round(float(record.longitude), 6))
    if kind == 'report':
        return (email, record.description, *coords) in LEGACY_REPORTS
    return not record.description and (email, record.name, record.request_type, *coords) in LEGACY_REQUESTS
