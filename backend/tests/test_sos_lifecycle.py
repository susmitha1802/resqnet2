"""SOS lifecycle contracts: real routes, memory DB, temporary private images."""
import io
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
import unittest
from unittest.mock import patch

import test_volunteer_acceptance as acceptance
from PIL import Image
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy import text
from extensions import db
from models import HelpRequest, ReliefTask, Volunteer, User
from routes.admin import admin_bp
from routes.help_requests import help_bp
from sos_lifecycle import proof_file
from repair_sos_data import repair_plan, apply_plan


class LifecycleTests(unittest.TestCase):
    def setUp(self):
        acceptance.AcceptanceTests.setUp(self)
        self.app.register_blueprint(admin_bp)
        self.app.register_blueprint(help_bp)
        self.storage = TemporaryDirectory(prefix='resqnet-sos-')
        self.app.config['UPLOAD_FOLDER'] = self.storage.name
        self.assertEqual(self.accept().status_code, 200)
        self.task_id = ReliefTask.query.one().task_id

    def tearDown(self):
        acceptance.AcceptanceTests.tearDown(self)
        self.storage.cleanup()

    accept = acceptance.AcceptanceTests.accept

    def headers(self, role):
        return {'Authorization': 'Bearer ' + self.tokens[role]} if role else {}

    def progress(self, status, role='volunteer'):
        return self.client.put('/help-request/status', json={'request_id': self.request_id, 'status': status},
                               headers=self.headers(role))

    def upload(self, role='volunteer', content=None, filename='proof.png', notes='Assistance delivered'):
        if content is None:
            buf = io.BytesIO()
            Image.new('RGB', (2, 2), color='green').save(buf, format='PNG')
            content = buf.getvalue()
        return self.client.post(f'/volunteer/upload-proof/{self.task_id}',
                                data={'proof_image': (io.BytesIO(content), filename), 'notes': notes},
                                headers=self.headers(role))

    def review(self, action='Approve', role='admin'):
        return self.client.put(f'/admin/verify-task/{self.task_id}', json={'action': action},
                               headers=self.headers(role))

    def snapshot(self):
        db.session.expire_all()
        task = db.session.get(ReliefTask, self.task_id)
        req = db.session.get(HelpRequest, self.request_id)
        vol = Volunteer.query.filter_by(user_id=self.users['volunteer']).one()
        return (req.status, task.status, task.verification_status, vol.availability_status, vol.completed_tasks)

    def test_ordered_progress_updates_request_and_task_and_rejects_regressions(self):
        self.assertEqual(self.progress('On Site').status_code, 409)
        self.assertEqual(self.progress('En Route').status_code, 200)
        self.assertEqual(self.snapshot()[:2], ('En Route', 'En Route'))
        self.assertEqual(self.progress('En Route').status_code, 409)
        self.assertEqual(self.progress('On Site').status_code, 200)
        for status in ['Pending', 'Accepted', 'Duplicate', 'En Route']:
            self.assertEqual(self.progress(status).status_code, 409)
        self.assertEqual(self.snapshot()[:2], ('On Site', 'On Site'))

    def test_proof_submission_is_enum_safe_and_citizen_progress_is_accurate(self):
        response = self.upload(filename='../../private.svg')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(self.snapshot(), ('On Site', 'Proof Submitted', 'Pending', 'on_task', 0))
        task = db.session.get(ReliefTask, self.task_id)
        self.assertTrue(task.proof_image_path.startswith('task_proofs/'))
        self.assertTrue(task.proof_image_path.endswith('.png'))
        self.assertNotIn(self.storage.name, str(response.json))
        self.assertEqual(response.json['task']['proof_image_path'], f'/volunteer/tasks/{self.task_id}/proof')
        result = self.client.get(f'/help-request/{self.request_id}', headers=self.headers('citizen'))
        self.assertEqual(result.status_code, 200)
        self.assertEqual(result.json['request']['progress_status'], 'Awaiting admin verification')
        self.assertEqual(self.client.get('/volunteer/tasks', headers=self.headers('volunteer')).status_code, 200)
        self.assertEqual(self.client.get('/admin/pending-verifications', headers=self.headers('admin')).json['verifications'][0]['task_id'], self.task_id)

    def test_proof_authorization_and_duplicate_submission(self):
        for role, expected in [(None, 401), ('citizen', 403), ('ngo', 403), ('admin', 403), ('other', 404)]:
            self.assertEqual(self.upload(role).status_code, expected)
        self.assertFalse(list(Path(self.storage.name).rglob('*.png')))
        self.assertEqual(self.upload().status_code, 200)
        self.assertEqual(self.upload().status_code, 409)
        self.assertEqual(len(list(Path(self.storage.name).rglob('*.png'))), 1)

    def test_invalid_image_missing_image_and_oversized_notes(self):
        self.assertEqual(self.upload(content=b'<html>not an image</html>').status_code, 400)
        self.assertEqual(self.client.post(f'/volunteer/upload-proof/{self.task_id}', headers=self.headers('volunteer')).status_code, 400)
        self.assertEqual(self.upload(notes='x' * 2001).status_code, 400)
        self.assertEqual(self.snapshot()[:2], ('Accepted', 'Assigned'))

    def test_private_proof_viewing_and_legacy_path_compatibility(self):
        self.upload()
        route = f'/volunteer/tasks/{self.task_id}/proof'
        for role, status in [(None, 401), ('citizen', 403), ('ngo', 403), ('other', 403), ('volunteer', 200), ('admin', 200)]:
            result = self.client.get(route, headers=self.headers(role))
            self.assertEqual(result.status_code, status)
            if status == 200:
                self.assertEqual(result.mimetype, 'image/png')
                self.assertTrue(result.data.startswith(b'\x89PNG'))
                self.assertEqual(result.headers['Cache-Control'], 'private, no-store')
                self.assertEqual(result.headers['X-Content-Type-Options'], 'nosniff')
            result.close()
        task = db.session.get(ReliefTask, self.task_id)
        legacy = str(proof_file(task.proof_image_path))
        task.proof_image_path = legacy
        db.session.commit()
        result = self.client.get(route, headers=self.headers('admin'))
        self.assertEqual(result.status_code, 200)
        result.close()
        self.assertNotIn(self.storage.name, str(task.to_dict()))
        task.proof_image_path = 'task_proofs/../outside.png'
        db.session.commit()
        self.assertEqual(self.client.get(route, headers=self.headers('admin')).status_code, 404)

    def test_only_admin_can_review_and_only_submitted_proof_is_reviewable(self):
        self.assertEqual(self.review().status_code, 409)
        self.upload()
        for role, status in [(None, 401), ('citizen', 403), ('ngo', 403), ('volunteer', 403), ('other', 403)]:
            self.assertEqual(self.review(role=role).status_code, status)
        self.assertEqual(self.review('Invalid').status_code, 400)
        self.assertEqual(self.snapshot()[1], 'Proof Submitted')

    def test_completion_requires_approval_and_duplicate_approval_is_rejected(self):
        self.upload()
        for role in ['volunteer', 'other', 'admin', 'ngo', 'citizen']:
            self.assertEqual(self.progress('Completed', role).status_code, 403)
        self.assertEqual(self.review().status_code, 200)
        self.assertEqual(self.snapshot(), ('Completed', 'Completed', 'Approved', 'available', 1))
        self.assertEqual(db.session.get(User, self.users['volunteer']).availability, 'available')
        task = db.session.get(ReliefTask, self.task_id)
        self.assertEqual(task.verified_by_admin_id, self.users['admin'])
        self.assertIsNotNone(task.completed_at)
        self.assertEqual(self.review().status_code, 409)
        self.assertEqual(self.review('Reject').status_code, 409)
        self.assertEqual(self.upload().status_code, 409)
        self.assertEqual(self.snapshot()[-1], 1)

    def test_rejection_and_resubmission_do_not_complete_or_release_volunteer(self):
        self.upload()
        self.assertEqual(self.review('Reject').status_code, 200)
        self.assertEqual(self.snapshot(), ('On Site', 'On Site', 'Rejected', 'on_task', 0))
        self.assertEqual(db.session.get(User, self.users['volunteer']).availability, 'unavailable')
        result = self.client.get(f'/help-request/{self.request_id}', headers=self.headers('citizen'))
        self.assertIn('rejected', result.json['request']['progress_status'])
        self.assertEqual(self.review('Reject').status_code, 409)
        self.assertEqual(self.upload().status_code, 200)
        self.assertIsNone(db.session.get(ReliefTask, self.task_id).verified_by_admin_id)
        self.assertEqual(self.review().status_code, 200)
        self.assertEqual(self.snapshot()[:3], ('Completed', 'Completed', 'Approved'))

    def test_missing_proof_blocks_approval_but_can_be_rejected_for_resubmission(self):
        self.upload()
        proof_file(db.session.get(ReliefTask, self.task_id).proof_image_path).unlink()
        self.assertEqual(self.review().status_code, 409)
        self.assertEqual(self.review('Reject').status_code, 200)
        self.assertEqual(self.snapshot()[1:3], ('On Site', 'Rejected'))

    def test_upload_commit_failure_rolls_back_states_and_removes_new_file(self):
        with patch.object(db.session, 'commit', side_effect=SQLAlchemyError('private database error')):
            response = self.upload()
        self.assertEqual(response.status_code, 503)
        self.assertNotIn('private database error', str(response.json))
        self.assertEqual(self.snapshot()[:3], ('Accepted', 'Assigned', 'Pending'))
        self.assertIsNone(db.session.get(ReliefTask, self.task_id).proof_image_path)
        self.assertFalse(list(Path(self.storage.name).rglob('*.png')))

    def test_review_commit_failures_roll_back_all_states_and_counters(self):
        self.upload()
        for action in ['Approve', 'Reject']:
            with self.subTest(action=action), patch.object(db.session, 'commit', side_effect=SQLAlchemyError('failure')):
                self.assertEqual(self.review(action).status_code, 503)
            self.assertEqual(self.snapshot(), ('On Site', 'Proof Submitted', 'Pending', 'on_task', 0))
            self.assertIsNone(db.session.get(ReliefTask, self.task_id).verified_by_admin_id)

    def test_progress_failure_rolls_back_request_and_task(self):
        with patch.object(db.session, 'commit', side_effect=SQLAlchemyError('failure')):
            self.assertEqual(self.progress('En Route').status_code, 503)
        self.assertEqual(self.snapshot()[:2], ('Accepted', 'Assigned'))
        self.assertEqual(self.progress('En Route', 'other').status_code, 403)

    def test_lost_task_claim_rolls_back_request_and_new_upload(self):
        execute = db.session.execute

        def lose_task_claim(statement, *args, **kwargs):
            if getattr(statement, 'is_update', False) and getattr(statement.table, 'name', None) == 'relief_tasks':
                return SimpleNamespace(rowcount=0)
            return execute(statement, *args, **kwargs)

        with patch.object(db.session, 'execute', side_effect=lose_task_claim):
            self.assertEqual(self.upload().status_code, 409)
        self.assertEqual(self.snapshot()[:2], ('Accepted', 'Assigned'))
        self.assertFalse(list(Path(self.storage.name).rglob('*.png')))

    def test_active_volunteer_cannot_clear_busy_status_until_approved(self):
        for status in ['available', 'unavailable']:
            result = self.client.put('/volunteer/update-status', json={'status': status}, headers=self.headers('volunteer'))
            self.assertEqual(result.status_code, 409)
        self.upload()
        self.review()
        self.assertEqual(self.client.put('/volunteer/update-status', json={'status': 'unavailable'},
                         headers=self.headers('volunteer')).status_code, 200)

    def test_legacy_invalid_request_repair_is_data_only_and_enum_safe(self):
        self.upload()
        db.session.execute(text("UPDATE help_requests SET status='Proof Submitted' WHERE request_id=:id"), {'id': self.request_id})
        db.session.commit()
        connection = db.session.connection()
        plan = repair_plan(connection)
        self.assertEqual(len(plan), 1)
        apply_plan(connection, plan)
        db.session.commit()
        self.assertEqual(self.snapshot()[:3], ('On Site', 'Proof Submitted', 'Pending'))
        self.assertEqual(ReliefTask.query.count(), 1)
        self.assertEqual(self.review().status_code, 200)

    def test_legacy_verified_label_is_not_promoted_to_real_approval(self):
        db.session.execute(text("UPDATE help_requests SET status='Completed' WHERE request_id=:id"), {'id': self.request_id})
        db.session.execute(text("UPDATE relief_tasks SET status='Completed', verification_status='Verified' WHERE task_id=:id"), {'id': self.task_id})
        db.session.commit()
        connection = db.session.connection()
        apply_plan(connection, repair_plan(connection))
        db.session.commit()
        self.assertEqual(self.snapshot()[1:3], ('Completed', 'Pending'))
        self.assertIn('unconfirmed', db.session.get(HelpRequest, self.request_id).to_dict()['progress_status'])
        self.assertEqual(self.review().status_code, 409)

    def test_incompatible_legacy_request_is_not_automatically_repaired(self):
        db.session.execute(text("UPDATE help_requests SET status='Proof Submitted' WHERE request_id=:id"), {'id': self.request_id})
        db.session.commit()
        with self.assertRaises(ValueError):
            repair_plan(db.session.connection())


if __name__ == '__main__':
    unittest.main()
