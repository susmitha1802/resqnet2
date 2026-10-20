"""Private image storage with validated content and server-generated filenames."""
from pathlib import Path
from uuid import uuid4
from flask import current_app
from PIL import Image, UnidentifiedImageError


def save_incident_image(upload, subfolder):
    if not upload or not upload.filename or subfolder not in {'reports', 'requests'}:
        return None
    try:
        with Image.open(upload.stream, formats=['PNG', 'JPEG']) as picture:
            image_format = picture.format
            picture.verify()
        if image_format not in {'PNG', 'JPEG'}:
            return None
        upload.stream.seek(0)
    except (UnidentifiedImageError, OSError, ValueError, Image.DecompressionBombError):
        return None
    folder = Path(current_app.config['UPLOAD_FOLDER']).resolve() / subfolder
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / (uuid4().hex + ('.png' if image_format == 'PNG' else '.jpg'))
    try:
        upload.save(path)
    except OSError:
        path.unlink(missing_ok=True)
        raise
    return str(path)
