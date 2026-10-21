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
    hops = config.get('TRUSTED_PROXY_HOPS', 0)
    if type(hops) is not int or not 0 <= hops <= 5:
        raise RuntimeError('TRUSTED_PROXY_HOPS must be an integer from 0 to 5.')
    if config.get('RUNNING_ON_RENDER') and hops == 0:
        raise RuntimeError('Render requires a verified TRUSTED_PROXY_HOPS setting for client rate limits.')
    origins = config.get('CORS_ORIGINS', [])
    if not origins or isinstance(origins, str):
        raise RuntimeError('Production requires an explicit CORS_ORIGINS allowlist.')
    for origin in origins:
        parsed = urlsplit(origin)
        if (parsed.scheme != 'https' or not parsed.hostname or '*' in origin
                or parsed.path or parsed.query or parsed.fragment or parsed.username):
            raise RuntimeError('Production CORS_ORIGINS must contain exact HTTPS origins.')
    if not config.get('TESTING'):
        if config.get('RATELIMIT_ENABLED') is False:
            raise RuntimeError('Production rate limiting cannot be disabled.')
        rate_uri = config.get('RATELIMIT_STORAGE_URI', '')
        parsed_rate = urlsplit(rate_uri)
        if parsed_rate.scheme not in {'redis', 'rediss'} or not parsed_rate.hostname:
            raise RuntimeError('Production requires Redis-compatible RATELIMIT_STORAGE_URI; memory counters are not allowed.')
        storage = config.get('PERSISTENT_STORAGE_PATH')
        if not storage or not Path(storage).is_absolute():
            raise RuntimeError('Production requires an absolute PERSISTENT_STORAGE_PATH for private uploads.')
        root = Path(storage).resolve()
        if config.get('RUNNING_ON_RENDER') and not root.is_mount():
            raise RuntimeError('Render PERSISTENT_STORAGE_PATH must be an attached disk mount, not an ephemeral directory.')
        uploads = Path(config['UPLOAD_FOLDER']).resolve()
        if not uploads.is_relative_to(root):
            raise RuntimeError('Production UPLOAD_FOLDER must be on persistent storage.')
        if any(not (uploads / folder).resolve().is_relative_to(uploads)
               for folder in ('requests', 'reports', 'task_proofs')):
            raise RuntimeError('Private upload subdirectories cannot resolve outside UPLOAD_FOLDER.')
        database = make_url(config['SQLALCHEMY_DATABASE_URI'])
        if database.drivername != 'sqlite':
            raise RuntimeError('This deployment supports mounted SQLite only; another database requires a reviewed driver and migration.')
        if database.drivername.startswith('sqlite') and (
            not database.database or not Path(database.database).is_absolute()
            or not Path(database.database).resolve().is_relative_to(root)
        ):
            raise RuntimeError('Production SQLite must be on persistent storage.')
