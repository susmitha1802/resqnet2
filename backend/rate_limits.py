"""Request abuse controls; production counters must be shared and fail closed."""
from flask import request, jsonify
from functools import wraps
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address
from redis.exceptions import RedisError
from werkzeug.middleware.proxy_fix import ProxyFix


def init_rate_limiting(app):
    hops = app.config.get('TRUSTED_PROXY_HOPS', 0)
    if hops:
        # Trust only the operator-verified -For chain, never forwarded Host/Port.
        app.wsgi_app = ProxyFix(app.wsgi_app, x_for=hops, x_proto=0)
    uri = app.config.get('RATELIMIT_STORAGE_URI', 'memory://')
    limiter = Limiter(
        get_remote_address, default_limits=[lambda: ('120 per minute' if request.method == 'GET' else '60 per minute')],
        default_limits_exempt_when=lambda: request.method in {'HEAD', 'OPTIONS'} or request.endpoint == 'health',
        storage_uri=uri, storage_options=(dict(socket_connect_timeout=2, socket_timeout=2)
                                         if uri.startswith(('redis://', 'rediss://')) else {}),
        key_prefix='resqnet', headers_enabled=True, retry_after='delta-seconds',
        swallow_errors=False, in_memory_fallback_enabled=False,
        enabled=app.config.get('RATELIMIT_ENABLED', not app.testing),
    )
    limiter.init_app(app)
    app.extensions['resqnet_limiter'] = limiter

    def app_local_view(view):
        # Decorators attach state: never mutate shared Blueprint functions across app factories.
        @wraps(view, updated=())
        def invoke(*args, **kwargs):
            return view(*args, **kwargs)
        return invoke
    for endpoint, limit, methods in [
        ('auth.login', '10 per minute', ['POST']),
        ('auth.register', '5 per hour', ['POST']),
        ('help_requests.create_help_request', '10 per minute', ['POST']),
        ('reports.report_disaster', '10 per minute', ['POST']),
        ('contact.submit_contact', '5 per hour', ['POST']),
        ('volunteers.upload_proof', '10 per minute', ['POST']),
        ('alerts.live_weather', '30 per minute', ['GET']),
        ('alerts.fetch_owm_alerts', '10 per minute', ['POST']),
        ('geocode.geocode', '1 per second', ['GET']),
    ]:
        view = app.view_functions.get(endpoint)
        if view is None:
            raise RuntimeError(f'Rate-limit endpoint is missing: {endpoint}')
        app.view_functions[endpoint] = limiter.limit(limit, methods=methods,
            key_func=(lambda: 'nominatim-global') if endpoint == 'geocode.geocode' else None)(app_local_view(view))

    @app.errorhandler(429)
    def too_many_requests(_error):
        return jsonify(success=False, message='Too many requests. Please retry later.'), 429

    @app.errorhandler(RedisError)
    def rate_store_unavailable(_error):
        # No fallback that would allow an uncounted mutation or leak the Redis URL.
        return jsonify(success=False, message='Request protection unavailable. Please retry later.'), 503

    if app.config.get('APP_ENV') == 'production' and not app.testing:
        try:
            healthy = limiter.storage.check()
        except Exception:
            healthy = False
        if not healthy:
            raise RuntimeError('Production rate-limit storage is unavailable; startup refused.') from None
    return limiter
