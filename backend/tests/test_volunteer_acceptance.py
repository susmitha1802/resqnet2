"""Volunteer acceptance contract against an isolated in-memory database."""
from pathlib import Path
from types import SimpleNamespace
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from flask import Flask
from flask_jwt_extended import create_access_token
from extensions import db, jwt
from models import User, Volunteer, HelpRequest, ReliefTask
from routes.volunteers import volunteers_bp


class AcceptanceTests(unittest.TestCase):
    def setUp(self):
        self.app = Flask(__name__)
        self.app.config.update(TESTING=True, SQLALCHEMY_DATABASE_URI='sqlite:///:memory:',
                               SQLALCHEMY_TRACK_MODIFICATIONS=False,
                               JWT_SECRET_KEY='acceptance-tests-only-secret-at-least-32-characters')
        db.init_app(self.app)
        jwt.init_app(self.app)
        self.app.register_blueprint(volunteers_bp)
        self.context = self.app.app_context()
        self.context.push()
        db.create_all()
        self.tokens = {}
        self.users = {}
        for name, role in [('citizen', 'reporter'), ('volunteer', 'volunteer'),
                           ('other', 'volunteer'), ('ngo', 'ngo'), ('admin', 'admin')]:
            user = User(name=name, email=f'{name}@test.invalid', phone='123', password='unused', role=role)
            db.session.add(user)
            db.session.flush()
            self.users[name] = user.user_id
            self.tokens[name] = create_access_token(identity=str(user.user_id))
            if role == 'volunteer':
                db.session.add(Volunteer(user_id=user.user_id))
        self.request = HelpRequest(user_id=self.users['citizen'], name='Citizen', contact='123',
                                   request_type='Rescue', latitude=17.4, longitude=78.4)
        db.session.add(self.request)
        db.session.commit()
        self.request_id = self.request.request_id
        self.client = self.app.test_client()

    def tearDown(self):
        db.session.remove()
        db.engine.dispose()
        self.context.pop()

    def accept(self, name='volunteer', request_id=None):
        return self.client.put('/volunteer/accept-task', json={
            'request_id': self.request_id if request_id is None else request_id
        }, headers={'Authorization': 'Bearer ' + self.tokens[name]})

    def test_success_creates_assignment_and_updates_both_records(self):
        response = self.accept()
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json['success'])
        self.assertEqual(response.json['request']['status'], 'Accepted')
        self.assertEqual(response.json['task']['status'], 'Assigned')
        self.assertEqual(response.json['task']['request_id'], self.request_id)
        db.session.expire_all()
        vol = Volunteer.query.filter_by(user_id=self.users['volunteer']).one()
        self.assertEqual((vol.availability_status, vol.assigned_tasks), ('on_task', 1))
        task = ReliefTask.query.one()
        self.assertEqual(task.volunteer_id, vol.volunteer_id)
        self.assertEqual(db.session.get(HelpRequest, self.request_id).status, 'Accepted')

    def test_missing_invalid_and_wrong_role_authorization(self):
        self.assertEqual(self.client.put('/volunteer/accept-task', json={'request_id': self.request_id}).status_code, 401)
        self.assertEqual(self.client.put('/volunteer/accept-task', json={'request_id': self.request_id},
                         headers={'Authorization': 'Bearer invalid'}).status_code, 422)
        for role in ['citizen', 'ngo', 'admin']:
            self.assertEqual(self.accept(role).status_code, 403)
        self.assertEqual(ReliefTask.query.count(), 0)
        self.assertEqual(db.session.get(HelpRequest, self.request_id).status, 'Pending')

    def test_repeat_and_other_volunteer_cannot_accept_assigned_request(self):
        self.assertEqual(self.accept().status_code, 200)
        self.assertEqual(self.accept().status_code, 409)
        self.assertEqual(self.accept('other').status_code, 409)
        self.assertEqual(ReliefTask.query.count(), 1)
        other = Volunteer.query.filter_by(user_id=self.users['other']).one()
        self.assertEqual((other.availability_status, other.assigned_tasks), ('available', 0))

    def test_unavailable_volunteer_cannot_accept(self):
        vol = Volunteer.query.filter_by(user_id=self.users['volunteer']).one()
        vol.availability_status = 'unavailable'
        db.session.commit()
        self.assertEqual(self.accept().status_code, 409)
        self.assertEqual(ReliefTask.query.count(), 0)

    def test_active_task_blocks_acceptance_even_if_availability_was_reset(self):
        self.accept()
        vol = Volunteer.query.filter_by(user_id=self.users['volunteer']).one()
        vol.availability_status = 'available'
        other = HelpRequest(user_id=self.users['citizen'], name='Other', contact='123',
                            request_type='Food', latitude=17.4, longitude=78.4)
        db.session.add(other)
        db.session.commit()
        self.assertEqual(self.accept(request_id=other.request_id).status_code, 409)
        self.assertEqual(ReliefTask.query.count(), 1)
        self.assertEqual(other.status, 'Pending')

    def test_invalid_ids_and_missing_request_do_not_create_tasks(self):
        for value in ['R1', '1', True, -1, 0, [], {}]:
            self.assertEqual(self.accept(request_id=value).status_code, 400)
        self.assertEqual(self.accept(request_id=999999).status_code, 404)
        self.assertEqual(ReliefTask.query.count(), 0)

    def test_lost_request_claim_rolls_back_volunteer_claim(self):
        execute = db.session.execute

        def lose_request_claim(statement, *args, **kwargs):
            if getattr(getattr(statement, 'table', None), 'name', None) == 'help_requests' and getattr(statement, 'is_update', False):
                return SimpleNamespace(rowcount=0)
            return execute(statement, *args, **kwargs)

        with patch.object(db.session, 'execute', side_effect=lose_request_claim):
            self.assertEqual(self.accept().status_code, 409)
        db.session.expire_all()
        vol = Volunteer.query.filter_by(user_id=self.users['volunteer']).one()
        self.assertEqual((vol.availability_status, vol.assigned_tasks), ('available', 0))
        self.assertEqual(ReliefTask.query.count(), 0)
        self.assertEqual(db.session.get(HelpRequest, self.request_id).status, 'Pending')


if __name__ == '__main__':
    unittest.main()
