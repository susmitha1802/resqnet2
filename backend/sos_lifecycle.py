"""Shared SOS transitions and private proof storage; no schema changes."""
from pathlib import Path, PurePosixPath
from io import BytesIO
from uuid import uuid4

from flask import current_app, send_file
from PIL import Image, UnidentifiedImageError
from sqlalchemy import update

from extensions import db
from models import HelpRequest, ReliefTask
from supabase_storage import is_cloud, upload_image, download_image, delete_image

ACTIVE_TASK_STATES = ('Assigned', 'En Route', 'On Site', 'Proof Submitted')
REQUEST_STATE = {'Assigned': 'Accepted', 'En Route': 'En Route',
                 'On Site': 'On Site', 'Proof Submitted': 'On Site'}


class TransitionConflict(Exception):
    pass


def ensure_active(task):
    active = ReliefTask.query.filter(ReliefTask.request_id == task.request_id,
                                     ReliefTask.status.in_(ACTIVE_TASK_STATES)).all()
    if (len(active) != 1 or active[0].task_id != task.task_id
            or task.request.status != REQUEST_STATE.get(task.status)):
        raise TransitionConflict('Task and request are no longer in a compatible active state.')


def transition(task, task_status, request_status, **task_fields):
    """Conditionally claim both observed states; caller commits or rolls back."""
    ensure_active(task)
    request_changed = db.session.execute(update(HelpRequest).where(
        HelpRequest.request_id == task.request_id, HelpRequest.status == task.request.status
    ).values(status=request_status)).rowcount
    task_changed = db.session.execute(update(ReliefTask).where(
        ReliefTask.task_id == task.task_id, ReliefTask.status == task.status,
        ReliefTask.verification_status == task.verification_status,
        ReliefTask.proof_image_path == task.proof_image_path
    ).values(status=task_status, **task_fields)).rowcount
    if request_changed != 1 or task_changed != 1:
        raise TransitionConflict('This task changed. Refresh before trying again.')


def proof_directory():
    return (Path(current_app.config['UPLOAD_FOLDER']) / 'task_proofs').resolve()


def proof_file(stored):
    """Accept current relative references and safe legacy references inside this root."""
    if not stored:
        return None
    normalized = stored.replace('\\', '/')
    parts = PurePosixPath(normalized)
    if '..' in parts.parts:
        return None
    root = proof_directory()
    allowed = {'task_proofs', 'uploads/task_proofs', root.as_posix().strip('/').casefold()}
    if str(parts.parent).strip('/').casefold() not in allowed:
        return None
    candidate = (root / parts.name).resolve()
    if candidate.parent != root or candidate.suffix.lower() not in {'.png', '.jpg', '.jpeg'}:
        return None
    return candidate


def save_proof(upload):
    if not upload or not upload.filename:
        raise ValueError('A PNG or JPEG proof image is required.')
    try:
        with Image.open(upload.stream, formats=['PNG', 'JPEG']) as picture:
            image_format = picture.format
            picture.verify()
        if image_format not in {'PNG', 'JPEG'}:
            raise ValueError('Only PNG or JPEG proof images are supported.')
        upload.stream.seek(0)
    except (UnidentifiedImageError, OSError, SyntaxError, Image.DecompressionBombError) as exc:
        raise ValueError('Proof image is invalid. Use a PNG or JPEG image.') from exc
    if is_cloud():
        content = upload.stream.read(current_app.config['MAX_CONTENT_LENGTH'] + 1)
        if len(content) > current_app.config['MAX_CONTENT_LENGTH']:
            raise ValueError('Proof image is too large.')
        return upload_image(content, 'task_proofs', image_format)
    name = uuid4().hex + ('.png' if image_format == 'PNG' else '.jpg')
    folder = proof_directory()
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / name
    try:
        upload.save(path)
    except OSError:
        path.unlink(missing_ok=True)
        raise
    return 'task_proofs/' + name


def proof_available(stored):
    if is_cloud():
        return download_image(stored, 'task_proofs') is not None
    path = proof_file(stored)
    return path is not None and path.is_file()


def private_proof(stored):
    if is_cloud():
        content = download_image(stored, 'task_proofs')
        if content is None:
            return None
        extension = '.png' if stored.endswith('.png') else '.jpg'
        response = send_file(BytesIO(content),
                             mimetype='image/png' if extension == '.png' else 'image/jpeg',
                             download_name='proof' + extension, conditional=False)
    else:
        path = proof_file(stored)
        if path is None or not path.is_file():
            return None
        response = send_file(path, mimetype='image/png' if path.suffix.lower() == '.png' else 'image/jpeg',
                             download_name='proof' + path.suffix.lower(), conditional=False)
    response.headers['Cache-Control'] = 'private, no-store'
    response.headers['X-Content-Type-Options'] = 'nosniff'
    return response


def remove_proof(stored):
    if is_cloud():
        delete_image(stored, 'task_proofs')
    else:
        path = proof_file(stored)
        if path:
            path.unlink(missing_ok=True)
