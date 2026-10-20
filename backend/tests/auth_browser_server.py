"""Temporary real Flask auth API for the browser check; never uses Config/real DB."""
from contextlib import redirect_stdout
import io
import json
from pathlib import Path
import secrets
import sys
import threading
from tempfile import TemporaryDirectory

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app import create_app
from werkzeug.serving import make_server, WSGIRequestHandler


class QuietHandler(WSGIRequestHandler):
    def log(self, *_args, **_kwargs):
        pass


if __name__ == '__main__':
    with TemporaryDirectory(prefix='resqnet-auth-browser-') as uploads:
        class TestConfig:
            TESTING = True
            DEBUG = False
            CORS_ORIGINS = [r'^http://127\.0\.0\.1:\d+$']
            SEED_DEMO_DATA = False
            SQLALCHEMY_DATABASE_URI = 'sqlite:///:memory:'
            SQLALCHEMY_TRACK_MODIFICATIONS = False
            JWT_SECRET_KEY = secrets.token_urlsafe(48)
            ADMIN_SECRET_CODE = 'isolated-browser-registration-only'
            UPLOAD_FOLDER = uploads
            ALLOWED_EXTENSIONS = {'png', 'jpg', 'jpeg'}
        with redirect_stdout(io.StringIO()):
            app = create_app(TestConfig)
        server = make_server('127.0.0.1', 0, app, request_handler=QuietHandler)
        print(json.dumps({'origin': f'http://127.0.0.1:{server.server_port}'}), flush=True)
        def stop_on_input():
            sys.stdin.readline()
            server.shutdown()
        threading.Thread(target=stop_on_input, daemon=True).start()
        try:
            server.serve_forever()
        finally:
            server.server_close()
