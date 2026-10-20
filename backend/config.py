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
    SECRET_KEY = os.getenv('SECRET_KEY')
    DEBUG = os.getenv('FLASK_DEBUG', 'False') == 'True'
    SEED_DEMO_DATA = os.getenv('SEED_DEMO_DATA', 'False') == 'True'

    # ── Database Configuration ──
    # The application strictly relies on the DATABASE_URL environment variable.
    # Neon PostgreSQL Example: postgresql+psycopg2://user:password@host/dbname?sslmode=require
    SQLALCHEMY_DATABASE_URI = os.getenv('DATABASE_URL', 'sqlite:///resqnet.db')

    SQLALCHEMY_TRACK_MODIFICATIONS = False

    # JWT
    JWT_SECRET_KEY           = os.getenv('JWT_SECRET_KEY')
    JWT_ACCESS_TOKEN_EXPIRES = 86400  # 24 hours
    ADMIN_SECRET_CODE = os.getenv('ADMIN_SECRET_CODE', '')

    # File uploads
    UPLOAD_FOLDER      = os.path.join(os.path.dirname(__file__), os.getenv('UPLOAD_FOLDER', 'uploads'))
    PERSISTENT_STORAGE_PATH = os.getenv('PERSISTENT_STORAGE_PATH')
    MAX_CONTENT_LENGTH = int(os.getenv('MAX_CONTENT_LENGTH', 10 * 1024 * 1024))  # 10 MB
    ALLOWED_EXTENSIONS = {'png', 'jpg', 'jpeg'}

    # CORS
    _cors = os.getenv(
        "CORS_ORIGINS",
        "http://127.0.0.1:5500,http://localhost:5500,https://resqnet1-2026.netlify.app"
    )
    CORS_ORIGINS = [o.strip() for o in _cors.split(",")]

    # Maps & Geocoding (Currently Leaflet + Nominatim are free, but keys can be provided for Mapbox/LocationIQ)
    MAP_PROVIDER = os.getenv('MAP_PROVIDER', 'leaflet')
    LOCATION_API_KEY = os.getenv('LOCATION_API_KEY', '')
