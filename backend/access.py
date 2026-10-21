"""Privacy projections for shared assistance and map information.

Exact SOS details belong to the requester, assigned volunteer and admins.
Shared previews contain coarse coordinates and structured fields only. Free text
may itself contain contact information, so it is not part of a shared preview.
"""
from models import ReliefTask, Volunteer


def can_view_private_request(user, req):
    if user is None:
        return False
    if user.role == 'admin' or req.user_id == user.user_id:
        return True
    return user.role == 'volunteer' and ReliefTask.query.join(Volunteer).filter(
        ReliefTask.request_id == req.request_id, Volunteer.user_id == user.user_id
    ).first() is not None


def request_view(req, user=None):
    if can_view_private_request(user, req):
        data = req.to_dict()
        data.pop('image_path', None)
        if user.role == 'admin' or req.user_id == user.user_id:
            data['image_url'] = f'/help-request/{req.request_id}/image' if req.image_path else None
        return data
    data = req.to_dict()
    allowed = {'request_id', 'request_type', 'priority_level', 'number_of_people',
               'status', 'progress_status', 'latitude', 'longitude', 'created_at',
               'updated_at', 'source', 'is_demo'}
    data = {k: v for k, v in data.items() if k in allowed}
    data.update(latitude=round(float(req.latitude), 2), longitude=round(float(req.longitude), 2),
                location_precision='approximate (0.01 degree grid)')
    return data


def report_view(report, user=None):
    data = report.to_dict()
    if user and (user.role == 'admin' or user.user_id == report.user_id):
        # Stored uploads are private filesystem paths, not browser URLs.
        data.pop('image_path', None)
        data['image_url'] = f'/report/{report.report_id}/image' if report.image_path else None
        return data
    allowed = {'report_id', 'disaster_type', 'severity', 'latitude', 'longitude',
               'created_at', 'source', 'status', 'is_demo'}
    data = {k: v for k, v in data.items() if k in allowed}
    data.update(latitude=round(float(report.latitude), 2), longitude=round(float(report.longitude), 2),
                location_precision='approximate (0.01 degree grid)')
    return data
