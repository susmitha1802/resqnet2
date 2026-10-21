"""Initialize only empty schemas; existing incompatible schemas require review."""
from sqlalchemy import inspect
from extensions import db


def initialize_database():
    inspector = inspect(db.engine)
    present = set(inspector.get_table_names())
    if present:
        for table in db.metadata.sorted_tables:
            if table.name not in present or not {c.name for c in table.columns}.issubset(
                    {c['name'] for c in inspector.get_columns(table.name)}):
                raise RuntimeError('Database schema is incompatible. Back up data and review migrations before startup.')
        return  # No DDL, migration, seed or record update on an existing database.
    db.create_all()
