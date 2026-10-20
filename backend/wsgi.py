"""Gunicorn entry point; startup validation runs before serving requests."""
from app import create_app

application = create_app()
