"""Private image storage with validated content and server-generated filenames."""
from pathlib import Path
from io import BytesIO
from uuid import uuid4
from flask import current_app, send_file
from PIL import Image, UnidentifiedImageError
from supabase_storage import is_cloud, upload_image, download_image, delete_image


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
    except (UnidentifiedImageError, OSError, ValueError, SyntaxError, Image.DecompressionBombError):
        return None
    if is_cloud():
        content = upload.stream.read(current_app.config['MAX_CONTENT_LENGTH'] + 1)
        if len(content) > current_app.config['MAX_CONTENT_LENGTH']:
            return None
        upload.stream.seek(0)
        return upload_image(content, subfolder, image_format)
    folder = Path(current_app.config['UPLOAD_FOLDER']).resolve() / subfolder
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / (uuid4().hex + ('.png' if image_format == 'PNG' else '.jpg'))
    try:
        upload.save(path)
    except OSError:
        path.unlink(missing_ok=True)
        raise
    return str(path)


def private_incident_image(stored_path, subfolder):
    """Return an authenticated image only from its expected private directory."""
    if subfolder not in {'reports', 'requests'} or not stored_path:
        return None
    if is_cloud():
        content = download_image(stored_path, subfolder)
        if content is None:
            return None
        response = send_file(BytesIO(content), mimetype='image/png' if stored_path.endswith('.png') else 'image/jpeg')
        response.headers['Cache-Control'] = 'private, no-store'
        response.headers['X-Content-Type-Options'] = 'nosniff'
        return response
    root = (Path(current_app.config['UPLOAD_FOLDER']).resolve() / subfolder).resolve()
    path = Path(stored_path).resolve()
    if path.parent != root or path.suffix.lower() not in {'.png', '.jpg'} or not path.is_file():
        return None
    response = send_file(path, mimetype='image/png' if path.suffix.lower() == '.png' else 'image/jpeg')
    response.headers['Cache-Control'] = 'private, no-store'
    response.headers['X-Content-Type-Options'] = 'nosniff'
    return response


def remove_incident_image(stored_path, subfolder):
    """Compensate a failed DB transaction without touching unrelated files."""
    if not stored_path:
        return
    if is_cloud():
        delete_image(stored_path, subfolder)
        return
    root = (Path(current_app.config['UPLOAD_FOLDER']).resolve() / subfolder).resolve()
    path = Path(stored_path).resolve()
    if path.parent == root:
        path.unlink(missing_ok=True)
