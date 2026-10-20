"""Dry-run by default. Repair only known legacy enum errors, without deleting records."""
import argparse
from datetime import datetime, timezone
from pathlib import Path
import sqlite3

from flask import Flask
from sqlalchemy import text
from config import Config
from extensions import db


def repair_plan(connection):
    plan = []
    for (request_id,) in connection.execute(text(
        "SELECT request_id FROM help_requests WHERE CAST(status AS TEXT) = 'Proof Submitted'"
    )):
        tasks = connection.execute(text(
            "SELECT status, verification_status FROM relief_tasks WHERE request_id = :id "
            "AND CAST(status AS TEXT) IN ('Assigned','En Route','On Site','Proof Submitted')"
        ), {'id': request_id}).all()
        if tasks != [('Proof Submitted', 'Pending')]:
            raise ValueError(f'Request {request_id} needs manual reconciliation; no repairs applied.')
        plan.append(('help_requests', 'request_id', request_id, 'status', 'Proof Submitted', 'On Site'))
    for (task_id,) in connection.execute(text(
        "SELECT task_id FROM relief_tasks WHERE CAST(verification_status AS TEXT) = 'Verified' "
        "AND CAST(status AS TEXT) = 'Completed'"
    )):
        # Legacy demo data had no stored proof/admin approval. Do not invent approval.
        plan.append(('relief_tasks', 'task_id', task_id, 'verification_status', 'Verified', 'Pending'))
    return plan


def apply_plan(connection, plan):
    for table, key, identity, column, old, new in plan:
        result = connection.execute(text(
            f'UPDATE {table} SET {column} = :new WHERE {key} = :id AND CAST({column} AS TEXT) = :old'
        ), {'new': new, 'id': identity, 'old': old})
        if result.rowcount != 1:
            raise ValueError('Legacy data changed during repair; transaction must be rolled back.')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--apply', action='store_true')
    args = parser.parse_args()
    app = Flask(__name__, instance_path=str(Path(__file__).resolve().parent / 'instance'))
    app.config.from_object(Config)
    db.init_app(app)
    with app.app_context():
        with db.engine.connect() as connection:
            plan = repair_plan(connection)
        for table, _, identity, column, old, new in plan:
            print(f'{table} #{identity}: {column} {old!r} -> {new!r}')
        if not args.apply:
            print(f'Dry run: {len(plan)} repairs. No records changed.')
            return
        if plan and db.engine.dialect.name == 'sqlite':
            database = Path(db.engine.url.database).resolve()
            backup = database.with_name(database.name + '.sos-' + datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ') + '.bak')
            with sqlite3.connect(str(database)) as source, sqlite3.connect(str(backup)) as destination:
                source.backup(destination)
            print(f'SQLite backup: {backup}')
        with db.engine.begin() as connection:
            if repair_plan(connection) != plan:
                raise ValueError('Data changed since planning; rerun the repair.')
            apply_plan(connection, plan)
        print(f'Applied {len(plan)} data-only repairs; no schema changes.')


if __name__ == '__main__':
    main()
