"""Fictional fixture for an isolated local staging database only."""
import argparse
from datetime import datetime, timedelta, timezone
import getpass
import os
from pathlib import Path
import secrets

import bcrypt
from flask import current_app
from PIL import Image, ImageDraw

from extensions import db
from models import (ContactMessage, DisasterReport, HelpRequest, PreparednessPing,
                    ReliefResource, ReliefTask, User, Volunteer, WeatherAlert)
from security import is_production
from sos_lifecycle import proof_directory, proof_file


TAG = '[DEMO] [resqnet2-seed-v1]'
STAGING_DB = Path(__file__).resolve().parent / 'instance' / 'demo_staging.db'
EMAILS = {
    'admin': 'admin@resqnet-demo.invalid',
    'ngo1': 'relief-one@resqnet-demo.invalid',
    'ngo2': 'relief-two@resqnet-demo.invalid',
    'vol1': 'volunteer-one@resqnet-demo.invalid',
    'vol2': 'volunteer-two@resqnet-demo.invalid',
    'vol3': 'volunteer-three@resqnet-demo.invalid',
    'reporter1': 'citizen-one@resqnet-demo.invalid',
    'reporter2': 'citizen-two@resqnet-demo.invalid',
}
EXPECTED = {User: 8, Volunteer: 3, DisasterReport: 3, HelpRequest: 5,
            ReliefTask: 2, ReliefResource: 4, WeatherAlert: 1,
            PreparednessPing: 3}


def _guard():
    if is_production(current_app.config) or current_app.config.get('RUNNING_ON_RENDER'):
        raise RuntimeError('Demo seeding and cleanup are disabled in production and on Render.')
    if current_app.config.get('STORAGE_BACKEND', 'local') != 'local':
        raise RuntimeError('Demo fixture requires isolated local private storage.')


def _counts():
    return {model: model.query.count() for model in (*EXPECTED, ContactMessage)}


def _intact():
    """Require the complete tagged fixture, with no unrelated records."""
    if any(model.query.count() != count for model, count in EXPECTED.items()):
        return False
    if ContactMessage.query.count():
        return False
    users = User.query.all()
    if {u.email for u in users} != set(EMAILS.values()) or any(not u.name.startswith('[DEMO] ') for u in users):
        return False
    if any(not r.description.startswith(TAG) for r in DisasterReport.query.all()):
        return False
    if any(not r.description or not r.description.startswith(TAG) for r in HelpRequest.query.all()):
        return False
    if any(not r.name.startswith(TAG) for r in ReliefResource.query.all()):
        return False
    if any(not t.completion_notes or not t.completion_notes.startswith(TAG) for t in ReliefTask.query.all()):
        return False
    alert = WeatherAlert.query.one()
    if alert.source != 'Demo seed data' or not alert.description.startswith(TAG):
        return False
    proof_tasks = [t for t in ReliefTask.query.all() if t.status == 'Completed']
    if (len(proof_tasks) != 1 or proof_tasks[0].verification_status != 'Approved'
            or proof_tasks[0].proof_image_path != 'task_proofs/demo-seed-v1.png'
            or not proof_file(proof_tasks[0].proof_image_path).is_file()):
        return False
    user_ids = {u.user_id for u in users}
    volunteer_ids = {v.volunteer_id for v in Volunteer.query.all()}
    request_ids = {r.request_id for r in HelpRequest.query.all()}
    return (all(v.user_id in user_ids for v in Volunteer.query.all())
            and all(r.user_id in user_ids for r in DisasterReport.query.all())
            and all(r.user_id in user_ids for r in HelpRequest.query.all())
            and all(t.volunteer_id in volunteer_ids and t.request_id in request_ids
                    and (t.verified_by_admin_id is None or t.verified_by_admin_id in user_ids)
                    for t in ReliefTask.query.all())
            and all(r.added_by in user_ids and (r.allocated_to is None or r.allocated_to in request_ids)
                    for r in ReliefResource.query.all())
            and all(p.alert_id == alert.alert_id and p.user_id in user_ids
                    for p in PreparednessPing.query.all()))


def seed_demo_data(password=None):
    """Seed once in one transaction. A rerun of the intact fixture is a no-op."""
    _guard()
    if any(_counts().values()):
        if _intact():
            return False
        raise RuntimeError('Database has other or changed records; no demo records were written.')
    password = password if password is not None else secrets.token_urlsafe(32)
    if not isinstance(password, str) or len(password) < 12:
        raise ValueError('DEMO_PASSWORD must have at least 12 characters.')
    hashed = bcrypt.hashpw(password.encode('utf-8'), bcrypt.gensalt()).decode('utf-8')
    now = datetime.now(timezone.utc)
    proof_path = proof_directory() / 'demo-seed-v1.png'
    if proof_path.exists() or proof_path.is_symlink():
        raise RuntimeError('A demo proof filename already exists; seeding refused.')
    try:
        def account(key, name, role, **kwargs):
            return User(name='[DEMO] ' + name, email=EMAILS[key], phone='0000000000',
                        password=hashed, role=role, **kwargs)

        u = {
            'admin': account('admin', 'Staging Administrator', 'admin'),
            'ngo1': account('ngo1', 'River Relief Collective', 'ngo', location='[DEMO] River Relief Collective'),
            'ngo2': account('ngo2', 'Community Supply Group', 'ngo', location='[DEMO] Community Supply Group'),
            'vol1': account('vol1', 'Asha Volunteer', 'volunteer', skills='[DEMO] First aid', location='17.4421, 78.4497'),
            'vol2': account('vol2', 'Ravi Volunteer', 'volunteer', skills='[DEMO] Transport', location='17.4391, 78.4477', availability='unavailable'),
            'vol3': account('vol3', 'Meera Volunteer', 'volunteer', skills='[DEMO] Logistics', location='17.4451, 78.4527', availability='unavailable'),
            'reporter1': account('reporter1', 'Citizen One', 'reporter'),
            'reporter2': account('reporter2', 'Citizen Two', 'reporter'),
        }
        db.session.add_all(u.values()); db.session.flush()

        v = {
            'vol1': Volunteer(user_id=u['vol1'].user_id, availability_status='available'),
            'vol2': Volunteer(user_id=u['vol2'].user_id, availability_status='on_task', assigned_tasks=1),
            'vol3': Volunteer(user_id=u['vol3'].user_id, availability_status='unavailable', completed_tasks=1),
        }
        for key, lat, lng in [('vol1', 17.4421, 78.4497), ('vol2', 17.4391, 78.4477), ('vol3', 17.4451, 78.4527)]:
            v[key].last_location_lat, v[key].last_location_lng = lat, lng
        db.session.add_all(v.values()); db.session.flush()

        alert = WeatherAlert(source='Demo seed data', alert_type='Flood', severity='Watch',
                             description=f'{TAG} Exercise bulletin only. No current hazard or forecast is asserted.',
                             affected_lat=17.4401, affected_lng=78.4487, affected_radius_km=10,
                             expires_at=now + timedelta(days=2))
        db.session.add(alert); db.session.flush()
        pings = [PreparednessPing(alert_id=alert.alert_id, user_id=u[key].user_id)
                 for key in ('ngo1', 'vol1', 'vol2')]
        pings[0].status, pings[0].acknowledged_at = 'Acknowledged', now
        db.session.add_all(pings)

        db.session.add_all([
            DisasterReport(user_id=u['reporter1'].user_id, disaster_type='Flood', latitude=17.4431,
                           longitude=78.4500, severity='Moderate Damage',
                           description=f'{TAG} Fictional street-water observation; unverified.'),
            DisasterReport(user_id=u['reporter2'].user_id, disaster_type='Flood', latitude=17.4300,
                           longitude=78.4400, severity='Moderate Damage',
                           description=f'{TAG} Fictional bridge-area observation; unverified.'),
            DisasterReport(user_id=u['reporter1'].user_id, disaster_type='Fire', latitude=17.4500,
                           longitude=78.4350, severity='Low Damage',
                           description=f'{TAG} Fictional electrical-fire report; unverified.'),
        ])

        def sos(owner, kind, lat, lng, priority, people, status, note, duplicate=False):
            return HelpRequest(user_id=u[owner].user_id, name=u[owner].name, contact='0000000000',
                               request_type=kind, latitude=lat, longitude=lng,
                               priority_level=priority, number_of_people=people, status=status,
                               is_duplicate=duplicate, description=f'{TAG} {note}')

        requests = [
            sos('reporter1', 'Rescue', 17.4435, 78.4505, 'High', 3, 'Pending', 'Fictional request; no dispatch occurred.'),
            sos('reporter2', 'Food', 17.4320, 78.4420, 'Medium', 5, 'Pending', 'Fictional food request.'),
            sos('reporter1', 'Medicine', 17.4440, 78.4510, 'High', 1, 'En Route', 'Fictional progress for testing.'),
            sos('reporter2', 'Water', 17.4480, 78.4580, 'Low', 2, 'Completed', 'Fictional completed request.'),
            sos('reporter2', 'Shelter', 17.4350, 78.4450, 'Medium', 2, 'Duplicate', 'Fictional duplicate example.', True),
        ]
        db.session.add_all(requests); db.session.flush()
        active = ReliefTask(volunteer_id=v['vol2'].volunteer_id, request_id=requests[2].request_id,
                            status='En Route', completion_notes=f'{TAG} Fictional active assignment.')
        completed = ReliefTask(volunteer_id=v['vol3'].volunteer_id, request_id=requests[3].request_id,
                               status='Completed', verification_status='Approved',
                               verified_by_admin_id=u['admin'].user_id,
                               proof_image_path='task_proofs/demo-seed-v1.png',
                               completion_notes=f'{TAG} Fictional approval of a synthetic proof card.')
        completed.completed_at = now - timedelta(hours=8)
        db.session.add_all([active, completed])

        def resource(owner, name, category, quantity, unit, location, allocated=None):
            return ReliefResource(name=f'{TAG} {name}', category=category, quantity=quantity, unit=unit,
                                  location=f'[DEMO] {location}', added_by=u[owner].user_id,
                                  allocated_to=requests[allocated].request_id if allocated is not None else None,
                                  allocated_at=now if allocated is not None else None)

        db.session.add_all([
            resource('ngo1', 'Bottled water', 'Water', 200, 'Liters', 'Staging depot A'),
            resource('ngo2', 'Medical kits', 'Medicine', 25, 'Boxes', 'Staging depot B', 2),
            resource('ngo1', 'Life jackets', 'Rescue', 20, 'Units', 'Staging depot A'),
            resource('ngo2', 'Food packets', 'Food', 75, 'Packets', 'Staging depot B', 3),
        ])
        proof_path.parent.mkdir(parents=True, exist_ok=True)
        image = Image.new('RGB', (420, 120), color=(12, 34, 55))
        ImageDraw.Draw(image).text((20, 48), 'DEMO ONLY - NO REAL RESCUE', fill=(255, 255, 255))
        image.save(proof_path, format='PNG')
        db.session.commit()
    except Exception:
        db.session.rollback()
        proof_path.unlink(missing_ok=True)
        raise
    return True


def cleanup_demo_data():
    """Only delete the complete seed fixture; abort on mixed or changed data."""
    _guard()
    if not any(_counts().values()):
        return False
    if not _intact():
        raise RuntimeError('Staging data is mixed or changed; cleanup refused without deleting records.')
    try:
        for model in (PreparednessPing, ReliefResource, ReliefTask, DisasterReport,
                      HelpRequest, WeatherAlert, Volunteer, User):
            for row in model.query.all():
                db.session.delete(row)
        db.session.commit()
    except Exception:
        db.session.rollback()
        raise
    proof_file('task_proofs/demo-seed-v1.png').unlink(missing_ok=True)
    return True


def set_demo_password(password):
    """Set one private password for only the intact local demo accounts."""
    _guard()
    if not _intact():
        raise RuntimeError('Demo fixture is absent or changed; password update refused.')
    if not isinstance(password, str) or len(password) < 12:
        raise ValueError('DEMO_PASSWORD must have at least 12 characters.')
    hashed = bcrypt.hashpw(password.encode('utf-8'), bcrypt.gensalt()).decode('utf-8')
    try:
        for user in User.query.all():
            user.password = hashed
        db.session.commit()
    except Exception:
        db.session.rollback()
        raise


def _staging_app():
    if os.getenv('RENDER', '').lower() == 'true' or os.getenv('APP_ENV', '').lower() == 'production':
        raise RuntimeError('The demo command cannot run in a production or Render environment.')
    STAGING_DB.parent.mkdir(parents=True, exist_ok=True)
    from app import create_app
    from config import Config

    class DemoConfig(Config):
        APP_ENV = 'testing'
        RUNNING_ON_RENDER = False
        DEBUG = False
        SEED_DEMO_DATA = False
        DEMO_MODE = True
        STORAGE_BACKEND = 'local'
        UPLOAD_FOLDER = str(STAGING_DB.parent / 'demo_uploads')
        SQLALCHEMY_DATABASE_URI = 'sqlite:///' + STAGING_DB.as_posix()
        SQLALCHEMY_ENGINE_OPTIONS = {}
        RATELIMIT_STORAGE_URI = 'memory://'
        TRUSTED_PROXY_HOPS = 0
        PROXY_DIAGNOSTIC_ENABLED = False

    return create_app(DemoConfig)


def main():
    parser = argparse.ArgumentParser(description='Manage isolated local sample data.')
    parser.add_argument('action', choices=('seed', 'cleanup', 'status', 'serve', 'set-password'))
    args = parser.parse_args()
    app = _staging_app()
    if args.action == 'serve':
        app.run(host='127.0.0.1', port=5001, debug=False, use_reloader=False)
        return
    with app.app_context():
        if args.action == 'seed':
            password = os.getenv('DEMO_PASSWORD') or getpass.getpass('Demo password (12+ characters): ')
            print('Created demo records.' if seed_demo_data(password) else 'Demo records already present.')
        elif args.action == 'set-password':
            password = os.getenv('DEMO_PASSWORD') or getpass.getpass('New demo password (12+ characters): ')
            set_demo_password(password)
            print('Updated only the eight staging demo account passwords.')
        elif args.action == 'cleanup':
            print('Removed demo records.' if cleanup_demo_data() else 'Staging database is empty.')
        else:
            print('Intact demo fixture.' if _intact() else 'Demo fixture absent or changed.')
        print('Staging database:', STAGING_DB)


if __name__ == '__main__':
    main()
