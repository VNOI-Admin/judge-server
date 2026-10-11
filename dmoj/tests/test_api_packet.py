import json
import threading
import time
import unittest
from http.server import BaseHTTPRequestHandler, HTTPServer
from unittest import mock

import requests

from dmoj.api_packet import ApiPacketManager

KEY = 'secret'
AUTH = {'Authorization': 'Bearer ' + KEY}
SUBMISSION = {
    'submission-id': 42,
    'problem-id': 'aplusb',
    'language': 'CPP17',
    'source': 'int main() {}',
    'time-limit': 1.0,
    'memory-limit': 65536,
    'short-circuit': False,
    'meta': {},
}


class FakeJudge:
    def __init__(self):
        self.grading = False
        self.current_submission = None
        self.manager = None
        self.begin_grading = mock.Mock(side_effect=self._begin_grading)
        self.abort_grading = mock.Mock()

    def _begin_grading(self, submission):
        self.current_submission = submission
        self.manager.begin_grading_packet(False)
        self.manager.grading_end_packet()


class ApiPacketManagerTest(unittest.TestCase):
    def setUp(self):
        self.events = []
        self.callback_auth = []
        events, callback_auth = self.events, self.callback_auth

        class CallbackHandler(BaseHTTPRequestHandler):
            def do_POST(self):
                callback_auth.append(self.headers.get('Authorization'))
                events.append(json.loads(self.rfile.read(int(self.headers['Content-Length']))))
                self.send_response(200)
                self.end_headers()

            def log_message(self, *args):
                pass

        self.callback_server = HTTPServer(('127.0.0.1', 0), CallbackHandler)
        threading.Thread(target=self.callback_server.serve_forever, daemon=True).start()

        self.judge = FakeJudge()
        callback_url = 'http://%s:%s/callback' % self.callback_server.server_address
        self.manager = ApiPacketManager(self.judge, 'test-judge', KEY, callback_url, ('127.0.0.1', 0))
        self.judge.manager = self.manager
        self.thread = threading.Thread(target=self.manager.run, daemon=True)
        self.thread.start()
        self.url = 'http://%s:%s' % self.manager.server.server_address

    def tearDown(self):
        self.manager.close()
        self.callback_server.shutdown()
        self.callback_server.server_close()

    def wait_for_events(self, count):
        deadline = time.time() + 5
        while len(self.events) < count and time.time() < deadline:
            time.sleep(0.05)
        return self.events

    def test_unauthorized(self):
        self.assertEqual(requests.post(self.url + '/submissions', json=SUBMISSION).status_code, 401)
        self.assertEqual(requests.get(self.url + '/status').status_code, 401)
        self.judge.begin_grading.assert_not_called()

    def test_missing_fields(self):
        resp = requests.post(self.url + '/submissions', json={'submission-id': 1}, headers=AUTH)
        self.assertEqual(resp.status_code, 400)
        self.judge.begin_grading.assert_not_called()

    def test_submission(self):
        resp = requests.post(self.url + '/submissions', json=SUBMISSION, headers=AUTH)
        self.assertEqual(resp.status_code, 202)
        self.assertEqual(resp.json(), {'submission-id': 42})

        submission = self.judge.begin_grading.call_args[0][0]
        self.assertEqual(submission.id, 42)
        self.assertEqual(submission.problem_id, 'aplusb')
        self.assertIsNone(submission.storage_namespace)
        self.assertEqual(submission.time_limit, 1.0)

        events = self.wait_for_events(3)
        self.assertEqual(
            [event['name'] for event in events], ['submission-acknowledged', 'grading-begin', 'grading-end']
        )
        self.assertTrue(all(event['submission-id'] == 42 and event['judge'] == 'test-judge' for event in events))
        self.assertEqual(set(self.callback_auth), {'Bearer ' + KEY})

    def test_busy(self):
        self.judge.grading = True
        self.judge.current_submission = mock.Mock(id=7)
        resp = requests.post(self.url + '/submissions', json=SUBMISSION, headers=AUTH)
        self.assertEqual(resp.status_code, 409)
        self.assertEqual(resp.json()['current-submission-id'], 7)
        self.judge.begin_grading.assert_not_called()

    def test_abort(self):
        resp = requests.post(self.url + '/submissions/42/abort', headers=AUTH)
        self.assertEqual(resp.status_code, 200)
        self.judge.abort_grading.assert_called_once_with(42)

    @mock.patch('dmoj.api_packet.get_runtime_versions', return_value={'CPP17': []})
    def test_status(self, _):
        resp = requests.get(self.url + '/status', headers=AUTH)
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertEqual(data['id'], 'test-judge')
        self.assertFalse(data['grading'])
        self.assertEqual(data['executors'], {'CPP17': []})
