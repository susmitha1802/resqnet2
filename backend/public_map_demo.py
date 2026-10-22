"""Three fictional map exercises stored separately from operational incident feeds.

The CLI is a deliberate maintenance command. Flask startup never calls it.
"""
import argparse
import os
from pathlib import Path
from urllib.parse import urlsplit

from dotenv import load_dotenv
from sqlalchemy import create_engine, func, select
from sqlalchemy.engine import make_url
from sqlalchemy.exc import ArgumentError
from sqlalchemy.orm import Session

from models import PreparednessPing, WeatherAlert


TAG = '[DEMO] [resqnet2-public-map-v1]'
SOURCE = 'Demo seed data'
NOTICE = 'FICTIONAL DEMO location. Not an observed incident, active alert, or forecast.'
SCENARIOS = (
    ('Coastal preparedness exercise', 17.686800, 83.218500),
    ('Road access exercise', 17.720000, 83.295000),
    ('Shelter coordination exercise', 17.755000, 83.345000),
)


def _description(title):
    return f'{TAG} {title}. {NOTICE}'


def _rows(session):
    return list(session.scalars(select(WeatherAlert).where(
        WeatherAlert.description.like(TAG + '%')).order_by(WeatherAlert.alert_id)))


def _intact(rows):
    actual = {(row.description, float(row.affected_lat), float(row.affected_lng)) for row in rows}
    expected = {(_description(title), lat, lng) for title, lat, lng in SCENARIOS}
    return (len(rows) == len(SCENARIOS) and actual == expected
            and all(row.source == SOURCE and row.alert_type == 'Other'
                    and row.severity == 'Watch' and row.affected_radius_km == 1
                    and row.expires_at is None and row.notified_at is None for row in rows))


def seed_map_demo(session):
    """Add only the tagged exercise rows; refuse partial or edited fixtures."""
    rows = _rows(session)
    if rows:
        if not _intact(rows):
            raise RuntimeError('Demo map fixture is incomplete or changed; no records written.')
        return False
    session.add_all(WeatherAlert('Other', _description(title), lat, lng,
                                 severity='Watch', source=SOURCE, affected_radius_km=1)
                    for title, lat, lng in SCENARIOS)
    session.flush()
    return True


def cleanup_map_demo(session):
    """Remove only intact tagged rows, never real alerts or responder acknowledgements."""
    rows = _rows(session)
    if not rows:
        return False
    if not _intact(rows):
        raise RuntimeError('Demo map fixture is incomplete or changed; cleanup refused.')
    ids = [row.alert_id for row in rows]
    if session.scalar(select(func.count()).select_from(PreparednessPing).where(
            PreparednessPing.alert_id.in_(ids))):
        raise RuntimeError('Demo map fixture has acknowledgements; cleanup refused.')
    for row in rows:
        session.delete(row)
    session.flush()
    return True


def configured_engine():
    """Require the exact matching Supabase project and TLS without revealing URL values."""
    raw = os.environ.get('RESQNET_DEMO_DATABASE_URL', '')
    project = urlsplit(os.environ.get('SUPABASE_URL', ''))
    try:
        database = make_url(raw)
        project_ref = (project.hostname or '').removesuffix('.supabase.co')
        direct = database.host == f'db.{project_ref}.supabase.co' and database.username == 'postgres'
        pooled = (database.host or '').endswith('.pooler.supabase.com') and database.username == f'postgres.{project_ref}'
        valid = (project.scheme == 'https' and project.hostname == f'{project_ref}.supabase.co'
                 and project.port in (None, 443)
                 and not (project.path or project.query or project.fragment or project.username or project.password)
                 and database.drivername == 'postgresql+psycopg' and (direct or pooled)
                 and database.port == 5432 and database.database == 'postgres'
                 and bool(database.password) and database.query.get('sslmode') in {'require', 'verify-full'})
    except (ValueError, TypeError, ArgumentError):
        valid = False
    if not valid:
        raise RuntimeError('Matching Supabase project URL and TLS Session Pooler database URL are required.')
    return create_engine(raw, pool_pre_ping=True, connect_args={'connect_timeout': 8})


def main():
    parser = argparse.ArgumentParser(description='Manage fictional public map exercise markers.')
    parser.add_argument('action', choices=('status', 'seed', 'cleanup'))
    args = parser.parse_args()
    load_dotenv(Path(__file__).with_name('.env.demo-map'), override=False)
    try:
        engine = configured_engine()
        with Session(engine) as session, session.begin():
            rows = _rows(session)
            if args.action == 'status':
                result = 'Demo map fixture: ' + ('absent' if not rows else
                         'intact (3 scenarios)' if _intact(rows) else 'incomplete or changed')
            elif args.action == 'seed':
                result = ('Created three fictional map scenarios.' if seed_map_demo(session)
                          else 'Three fictional map scenarios already present.')
            else:
                result = ('Removed only the three fictional map scenarios.' if cleanup_map_demo(session)
                          else 'No fictional map scenarios present.')
        engine.dispose()
        print(result)
    except Exception:
        # SQLAlchemy exceptions can embed connection URLs. Never print them here.
        raise SystemExit('Demo map command failed; no connection details were printed.') from None


if __name__ == '__main__':
    main()
