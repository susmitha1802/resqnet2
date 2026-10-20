"""
ResQNet — Duplicate Request Detection
"""
import math
from datetime import datetime, timedelta, timezone


def haversine(lat1: float, lng1: float, lat2: float, lng2: float) -> float:
    """
    Calculate great-circle distance (km) between two GPS coordinates.
    """
    R = 6371.0
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlam = math.radians(lng2 - lng1)
    a = math.sin(dphi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(dlam / 2) ** 2
    return R * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))


def detect_duplicate(
    new_request: dict,
    existing_requests,
    location_radius_km: float = 0.5,
    time_window_minutes: int = 60
) -> bool:
    """
    Returns True if a sufficiently similar request already exists.

    Duplicate criteria (ALL must match):
      - Same request_type
      - Within location_radius_km distance
      - Submitted within the last time_window_minutes minutes
    """
    # `created_at` columns are always written as UTC (see models.py), but
    # depending on the DB driver they may round-trip as naive datetimes
    # (no tzinfo) even though the value itself is UTC. Comparing a naive
    # and an aware datetime raises TypeError, so the cutoff is kept naive
    # here and every `req.created_at` is normalized to naive-UTC before
    # comparison, regardless of whether the driver preserved tzinfo.
    cutoff = datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(minutes=time_window_minutes)
    new_lat  = float(new_request['latitude'])
    new_lng  = float(new_request['longitude'])
    new_type = new_request['request_type']

    for req in existing_requests:
        if req.request_type != new_type:
            continue
        req_created_at = req.created_at
        if req_created_at and req_created_at.tzinfo is not None:
            req_created_at = req_created_at.astimezone(timezone.utc).replace(tzinfo=None)
        if req_created_at and req_created_at < cutoff:
            continue
        dist = haversine(new_lat, new_lng, float(req.latitude), float(req.longitude))
        if dist <= location_radius_km:
            return True
    return False
