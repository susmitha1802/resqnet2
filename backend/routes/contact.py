"""
ResQNet — Contact Us Routes Blueprint
POST /contact
GET  /admin/contact-messages
PUT  /admin/contact-messages/<id>/read
DELETE /admin/contact-messages/<id>
"""
from flask import Blueprint, request, jsonify


from extensions import db
from models import ContactMessage
from routes.middleware import require_role

contact_bp = Blueprint('contact', __name__)

def _success(data=None, message='OK', status=200):
    return jsonify({'success': True, 'message': message, **(data or {})}), status

def _error(message='Error', status=400):
    return jsonify({'success': False, 'message': message}), status

# ── POST /contact ─────────────────────────────────────────────────────────────
@contact_bp.route('/contact', methods=['POST'])
def submit_contact():
    data = request.get_json(silent=True) or {}
    
    name    = data.get('name', '').strip()
    email   = data.get('email', '').strip().lower()
    subject = data.get('subject', '').strip()
    message = data.get('message', '').strip()
    
    if not all([name, email, subject, message]):
        return _error('Name, email, subject, and message are required')
        
    msg = ContactMessage(
        name=name,
        email=email,
        subject=subject,
        message=message
    )
    db.session.add(msg)
    db.session.commit()
    
    return _success({'contact_message': msg.to_dict()}, 'Message submitted successfully', 201)

# ── GET /admin/contact-messages ────────────────────────────────────────────────
@contact_bp.route('/admin/contact-messages', methods=['GET'])
@require_role('admin')
def get_contact_messages():
    messages = ContactMessage.query.order_by(ContactMessage.created_at.desc()).all()
    return _success({'messages': [m.to_dict() for m in messages]})

# ── PUT /admin/contact-messages/<id>/read ──────────────────────────────────────
@contact_bp.route('/admin/contact-messages/<int:msg_id>/read', methods=['PUT'])
@require_role('admin')
def mark_contact_message_read(msg_id):
    msg = db.get_or_404(ContactMessage, msg_id)
    msg.status = 'Read'
    db.session.commit()
    return _success({'contact_message': msg.to_dict()}, 'Message marked as read')

# ── DELETE /admin/contact-messages/<id> ────────────────────────────────────────
@contact_bp.route('/admin/contact-messages/<int:msg_id>', methods=['DELETE'])
@require_role('admin')
def delete_contact_message(msg_id):
    msg = db.get_or_404(ContactMessage, msg_id)
    db.session.delete(msg)
    db.session.commit()
    return _success(None, 'Message deleted successfully')
