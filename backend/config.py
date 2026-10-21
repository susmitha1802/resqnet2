"""
ResQNet — Flask Configuration
"""
import os
from pathlib import Path
from dotenv import load_dotenv

load_dotenv(Path(__file__).with_name('.env'), override=False)

class Config:
    # Flask
    APP_ENV = 'production' if os.getenv('RENDER', '').lower() == 'true' else os.getenv('APP_ENV', 'development').lower()
    RUNNING_ON_RENDER = os.getenv('RENDER', '').lower() == 'true'
    SECRET_KEY = os.getenv('SECRET_KEY')
    DEBUG = os.getenv('FLASK_DEBUG', 'False') == 'True'
    SEED_DEMO_DATA = os.getenv('SEED_DEMO_DATA', 'False') == 'True'

    # ── Database Configuration ──
    # Supabase's session pooler uses an IPv4-compatible PostgreSQL connection.
    _database_url = os.getenv('DATABASE_URL', 'sqlite:///resqnet.db')
    SQLALCHEMY_DATABASE_URI = (_database_url.replace('postgresql://', 'postgresql+psycopg://', 1)
                               if _database_url.startswith('postgresql://') else _database_url)
    SQLALCHEMY_ENGINE_OPTIONS = ({'pool_pre_ping': True, 'pool_size': 2,
                                  'max_overflow': 0, 'pool_recycle': 300}
                                 if SQLALCHEMY_DATABASE_URI.startswith('postgresql+psycopg://') else {})

    SQLALCHEMY_TRACK_MODIFICATIONS = False

    # JWT
    JWT_SECRET_KEY           = os.getenv('JWT_SECRET_KEY')
    JWT_ACCESS_TOKEN_EXPIRES = 86400  # 24 hours
    ADMIN_SECRET_CODE = os.getenv('ADMIN_SECRET_CODE', '')

    # File uploads
    UPLOAD_FOLDER      = os.path.join(os.path.dirname(__file__), os.getenv('UPLOAD_FOLDER', 'uploads'))
    PERSISTENT_STORAGE_PATH = os.getenv('PERSISTENT_STORAGE_PATH')
    STORAGE_BACKEND = os.getenv('STORAGE_BACKEND', 'local').lower()
    SUPABASE_URL = os.getenv('SUPABASE_URL', '')
    SUPABASE_SECRET_KEY = os.getenv('SUPABASE_SECRET_KEY', '')
    SUPABASE_STORAGE_BUCKET = os.getenv('SUPABASE_STORAGE_BUCKET', '')
    MAX_CONTENT_LENGTH = int(os.getenv('MAX_CONTENT_LENGTH', 10 * 1024 * 1024))  # 10 MB
    ALLOWED_EXTENSIONS = {'png', 'jpg', 'jpeg'}

    # CORS
    _cors = os.getenv(
        "CORS_ORIGINS",
        "http://127.0.0.1:5500,http://localhost:5500,https://resqnet1-2026.netlify.app"
    )
    CORS_ORIGINS = [o.strip() for o in _cors.split(",")]

    # Redis-compatible shared counters are required in production, never memory fallback.
    RATELIMIT_STORAGE_URI = os.getenv('RATELIMIT_STORAGE_URI', 'memory://')
    RATELIMIT_ENABLED = True
    TRUSTED_PROXY_HOPS = int(os.getenv('TRUSTED_PROXY_HOPS', '0'))
    PROXY_DIAGNOSTIC_ENABLED = os.getenv('PROXY_DIAGNOSTIC_ENABLED', 'False') == 'True'

    # Maps & Geocoding (Currently Leaflet + Nominatim are free, but keys can be provided for Mapbox/LocationIQ)
    MAP_PROVIDER = os.getenv('MAP_PROVIDER', 'leaflet')
    LOCATION_API_KEY = os.getenv('LOCATION_API_KEY', '')
