"""Linux-only Gunicorn gate using temporary SQLite/uploads and isolated test Redis.

Set SMOKE_REDIS_URL privately to a dedicated test instance. Never use production Redis.
No service is deployed; no existing database is opened; Redis is never flushed.
"""
import hashlib
import json
import os
from pathlib import Path
import secrets
import socket
import sqlite3
import subprocess
import sys
from tempfile import TemporaryDirectory
import time
import urllib.error
import urllib.request


def main():
    if sys.platform != 'linux':
        raise SystemExit('This gate requires Linux; Gunicorn was not tested on this platform.')
    redis_url = os.environ.get('SMOKE_REDIS_URL')
    if not redis_url:
        raise SystemExit('Set SMOKE_REDIS_URL privately to an isolated test Redis instance.')
    backend = Path(__file__).resolve().parents[1]
    with TemporaryDirectory(prefix='resqnet-gunicorn-') as folder:
        root = Path(folder)
        env = os.environ.copy()
        env.update(APP_ENV='production',RENDER='false',FLASK_DEBUG='False',SEED_DEMO_DATA='False',
            SECRET_KEY=secrets.token_urlsafe(48),JWT_SECRET_KEY=secrets.token_urlsafe(48),ADMIN_SECRET_CODE='',
            DATABASE_URL='sqlite:///'+(root/'isolated.db').as_posix(),PERSISTENT_STORAGE_PATH=str(root),
            UPLOAD_FOLDER=str(root/'uploads'),RATELIMIT_STORAGE_URI=redis_url,TRUSTED_PROXY_HOPS='0',
            CORS_ORIGINS='https://resqnet1-2026.netlify.app',OPENWEATHER_API_KEY='',FLOOD_API_BASE_URL='')
        before = None
        for restart in range(2):
            with socket.socket() as reserved:
                reserved.bind(('127.0.0.1',0));port=reserved.getsockname()[1]
            with (root/'gunicorn.log').open('ab') as log:
                process = subprocess.Popen([sys.executable,'-m','gunicorn','--bind',f'127.0.0.1:{port}',
                    '--workers','1','--threads','4','--worker-class','gthread','--timeout','90','wsgi:application'],
                    cwd=backend,env=env,stdout=log,stderr=log)
                try:
                    origin=f'http://127.0.0.1:{port}'
                    for _ in range(60):
                        if process.poll() is not None:
                            raise RuntimeError('Gunicorn exited before health succeeded; no deployment performed.')
                        try:
                            with urllib.request.urlopen(origin+'/health',timeout=1) as response:
                                assert response.status==200
                            break
                        except (urllib.error.URLError,TimeoutError):time.sleep(0.25)
                    else:raise RuntimeError('Gunicorn health timed out.')
                    preflight=urllib.request.Request(origin+'/profile',method='OPTIONS',headers={
                        'Origin':env['CORS_ORIGINS'],'Access-Control-Request-Method':'GET',
                        'Access-Control-Request-Headers':'Authorization'})
                    with urllib.request.urlopen(preflight,timeout=2) as response:
                        assert response.headers['Access-Control-Allow-Origin']==env['CORS_ORIGINS']
                    try:
                        urllib.request.urlopen(origin+'/uploads/task_proofs/private.png',timeout=2)
                        raise AssertionError('Private upload path became public')
                    except urllib.error.HTTPError as error:assert error.code==404
                    if restart==0:
                        for attempt in range(11):
                            request=urllib.request.Request(origin+'/login',data=b'{}',headers={'Content-Type':'application/json'})
                            try:
                                urllib.request.urlopen(request,timeout=2)
                                raise AssertionError('Invalid login unexpectedly succeeded')
                            except urllib.error.HTTPError as error:
                                assert error.code==(429 if attempt==10 else 400)
                                assert json.load(error)['success'] is False
                finally:
                    process.terminate()
                    try:process.wait(timeout=15)
                    except subprocess.TimeoutExpired:process.kill();process.wait(timeout=5)
            digest=hashlib.sha256((root/'isolated.db').read_bytes()).digest()
            if before is not None:assert digest==before,'Restart changed the temporary database'
            before=digest
        with sqlite3.connect((root/'isolated.db').as_uri()+'?mode=ro',uri=True) as connection:
            assert connection.execute('SELECT COUNT(*) FROM users').fetchone()[0]==0
    print('PASS Linux Gunicorn: production WSGI, CORS, private paths, rate limits, empty DB and restart.')


if __name__=='__main__':
    main()
