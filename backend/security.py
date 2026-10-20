"""Runtime deployment guards; never logs or changes secret/account values."""
from pathlib import Path
import secrets
from urllib.parse import urlsplit
from sqlalchemy.engine import make_url


DEMO_ACCOUNT_EMAILS = frozenset({
    'admin@resqnet.com', 'redcross@resqnet.com', 'globalrelief@resqnet.com',
    'vol1@resqnet.com', 'vol2@resqnet.com', 'vol3@resqnet.com',
    'reporter1@resqnet.com', 'reporter2@resqnet.com',
    'user@demo.com', 'vol@demo.com', 'ngo@demo.com', 'admin@demo.com',
    'redcross.vizag@demo.com', 'lions.vizag@demo.com', 'hamstech.vizag@demo.com',
    'giet.relief@demo.com', 'rotary.vizag@demo.com', 'helpage.vizag@demo.com',
    'ravi.vol@demo.com', 'priya.vol@demo.com', 'kiran.vol@demo.com',
})


def is_production(config):
    return config.get('APP_ENV') == 'production'


def is_demo_account(user):
    return user.email.lower() in DEMO_ACCOUNT_EMAILS


def validate_runtime_config(app):
    config = app.config
    if config.get('APP_ENV', 'development') not in ('development', 'production', 'testing'):
        raise RuntimeError('APP_ENV must be development, testing, or production.')
    if not is_production(config):
        for key in ('SECRET_KEY', 'JWT_SECRET_KEY'):
            if not config.get(key):
                config[key] = secrets.token_urlsafe(48)
        return
    for key in ('SECRET_KEY', 'JWT_SECRET_KEY'):
        value = config.get(key)
        if not isinstance(value, str) or len(value) < 32 or value.startswith(('your_', 'change-', 'resqnet-secret-')):
            raise RuntimeError(f'Production requires a persistent, strong {key} environment value.')
    admin_code = config.get('ADMIN_SECRET_CODE')
    if admin_code and (not isinstance(admin_code, str) or len(admin_code) < 32):
        raise RuntimeError('Production ADMIN_SECRET_CODE must be strong or unset to disable admin registration.')
    if config.get('DEBUG') or config.get('SEED_DEMO_DATA'):
        raise RuntimeError('Production requires DEBUG=False and SEED_DEMO_DATA=False.')
    origins = config.get('CORS_ORIGINS', [])
    if not origins or isinstance(origins, str):
        raise RuntimeError('Production requires an explicit CORS_ORIGINS allowlist.')
    for origin in origins:
        parsed = urlsplit(origin)
        if (parsed.scheme != 'https' or not parsed.hostname or '*' in origin
                or parsed.path or parsed.query or parsed.fragment or parsed.username):
            raise RuntimeError('Production CORS_ORIGINS must contain exact HTTPS origins.')
    if not config.get('TESTING'):
        storage = config.get('PERSISTENT_STORAGE_PATH')
        if not storage or not Path(storage).is_absolute():
            raise RuntimeError('Production requires an absolute PERSISTENT_STORAGE_PATH for private uploads.')
        root = Path(storage).resolve()
        uploads = Path(config['UPLOAD_FOLDER']).resolve()
        if not uploads.is_relative_to(root):
            raise RuntimeError('Production UPLOAD_FOLDER must be on persistent storage.')
        database = make_url(config['SQLALCHEMY_DATABASE_URI'])
        if database.drivername.startswith('sqlite') and (
            not database.database or not Path(database.database).is_absolute()
            or not Path(database.database).resolve().is_relative_to(root)
        ):
            raise RuntimeError('Production SQLite must be on persistent storage.')
