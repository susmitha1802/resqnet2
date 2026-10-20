"""
ResQNet — Flask Extensions (shared instances)

Uses Flask-SQLAlchemy 3.x recommended pattern:
  - DeclarativeBase subclass as model_class gives Pylance/Pyright
    full type visibility into all model constructors and attributes.
"""
from flask_sqlalchemy import SQLAlchemy
from flask_jwt_extended import JWTManager
from sqlalchemy.orm import DeclarativeBase


class Base(DeclarativeBase):
    """Typed declarative base — enables Pylance to resolve model constructors."""
    pass


db  = SQLAlchemy(model_class=Base)
jwt = JWTManager()


@jwt.user_lookup_loader
def authenticated_database_user(_header, payload):
    """All jwt_required routes reject deleted or malformed identities."""
    from models import User
    from flask import current_app
    from security import is_production, is_demo_account
    identity = payload.get('sub')
    if (not isinstance(identity, str) or len(identity) > 10
            or not identity.isascii() or not identity.isdecimal()):
        return None
    uid = int(identity)
    user = db.session.get(User, uid) if 0 < uid <= 2147483647 else None
    if user and is_production(current_app.config) and is_demo_account(user):
        return None
    return user
