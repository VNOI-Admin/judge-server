import json
import logging
import queue
import re
import threading
import time
from http.server import HTTPServer
from typing import Optional, TYPE_CHECKING, Tuple

import requests

from dmoj import sysinfo
from dmoj.control import JudgeControlRequestHandler
from dmoj.judgeenv import get_judge_version, get_problem_storages, get_runtime_versions
from dmoj.packet import PacketManager

if TYPE_CHECKING:
    from dmoj.judge import Judge

log = logging.getLogger(__name__)

SUBMISSION_FIELDS = ('submission-id', 'problem-id', 'language', 'source', 'time-limit', 'memory-limit')
ABORT_PATH = re.compile(r'^/submissions/(\d+)/abort$')


class ApiPacketManager(PacketManager):
    """
    Packet manager for running the judge without a persistent connection to the server.

    Submissions arrive as HTTP requests to the judge, and every packet the judge would send over the socket is
    instead POSTed as JSON, in order, to a callback URL.
    """

    CALLBACK_TIMEOUT = 30
    CALLBACK_ATTEMPTS = 5

    def __init__(self, judge: 'Judge', name: str, key: str, callback_url: str, listen: Tuple[str, int]) -> None:
        # Intentionally not calling `super().__init__`, which would connect to the server.
        self.judge = judge
        self.name = name
        self.key = key
        self.callback_url = callback_url
        self.listen = listen
        self._closed = False
        self._serving = False

        self._lock = threading.RLock()
        self._batch = 0
        self._testcase_queue_lock = threading.Lock()
        self._testcase_queue = []
        self.fallback = 4

        self._current_callback_url = callback_url
        self._outbox: 'queue.Queue[Optional[Tuple[str, dict]]]' = queue.Queue()
        self._session = requests.Session()

        self.conn = None
        self.online = True
        self.server = HTTPServer(listen, self._make_handler())
        log.info('Judge API listening on %s:%s, sending events to %s', listen[0], listen[1], callback_url)

    def _make_handler(self):
        manager = self

        class Handler(JudgeControlRequestHandler):
            judge = manager.judge

            def _authorized(self) -> bool:
                if self.headers.get('Authorization') == f'Bearer {manager.key}':
                    return True
                self._send_json(401, {'error': 'unauthorized'})
                return False

            def _send_json(self, code: int, data: dict) -> None:
                body = json.dumps(data).encode('utf-8')
                self.send_response(code)
                self.send_header('Content-Type', 'application/json')
                self.send_header('Content-Length', str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def _read_json(self) -> Optional[dict]:
                try:
                    length = int(self.headers.get('Content-Length', 0))
                    data = json.loads(self.rfile.read(length) or b'{}')
                except (ValueError, UnicodeDecodeError):
                    data = None
                if not isinstance(data, dict):
                    self._send_json(400, {'error': 'body must be a JSON object'})
                    return None
                return data

            def do_POST(self):
                if self.path == '/submissions':
                    if self._authorized():
                        data = self._read_json()
                        if data is not None:
                            self._send_json(*manager.handle_submission(data))
                    return

                match = ABORT_PATH.match(self.path)
                if match:
                    if self._authorized():
                        manager.judge.abort_grading(int(match.group(1)))
                        self._send_json(200, {'status': 'ok'})
                    return

                super().do_POST()

            def do_GET(self):
                if self.path == '/status':
                    if self._authorized():
                        self._send_json(200, manager.status())
                    return

                super().do_GET()

        return Handler

    def handle_submission(self, data: dict) -> Tuple[int, dict]:
        missing = [field for field in SUBMISSION_FIELDS if field not in data]
        if missing:
            return 400, {'error': 'missing fields: %s' % ', '.join(missing)}

        if self.judge.grading:
            current = self.judge.current_submission
            return 409, {'error': 'judge is busy', 'current-submission-id': current.id if current else None}

        data.setdefault('short-circuit', False)
        data.setdefault('meta', {})
        self._current_callback_url = data.get('callback-url') or self.callback_url

        # Acknowledge before grading starts, so that the acknowledgement is ordered before `grading-begin`.
        self.submission_acknowledged_packet(data['submission-id'])
        self._begin_grading_from_request(data)
        return 202, {'submission-id': data['submission-id']}

    def status(self) -> dict:
        current = self.judge.current_submission
        data = {
            'id': self.name,
            'online': self.online,
            'grading': self.judge.grading,
            'current-submission-id': current.id if current else None,
            'judge-version': get_judge_version(),
            'storages': get_problem_storages(),
            'executors': get_runtime_versions(),
            'time': time.time(),
        }
        for fn in sysinfo.report_callbacks:
            key, value = fn()
            data[key] = value
        return data

    def _send_packet(self, packet: dict):
        for k, v in packet.items():
            if isinstance(v, bytes):
                packet[k] = v.decode('utf-8', 'replace')
        packet['judge'] = self.name
        self._outbox.put((self._current_callback_url, packet))

    def _deliver(self, url: str, packet: dict) -> None:
        delay = 1.0
        for attempt in range(1, self.CALLBACK_ATTEMPTS + 1):
            try:
                resp = self._session.post(
                    url,
                    json=packet,
                    headers={'Authorization': f'Bearer {self.key}'},
                    timeout=self.CALLBACK_TIMEOUT,
                )
                if resp.status_code < 500:
                    if resp.status_code >= 400:
                        log.error('Callback rejected %s with HTTP %d: %s', packet['name'], resp.status_code, resp.text)
                    return
                log.warning('Callback for %s failed with HTTP %d', packet['name'], resp.status_code)
            except requests.RequestException:
                log.warning('Callback for %s failed (attempt %d)', packet['name'], attempt, exc_info=True)
            time.sleep(delay)
            delay = min(delay * 2, 15)
        log.error(
            'Dropping %s packet for submission %s after %d attempts',
            packet['name'],
            packet.get('submission-id'),
            self.CALLBACK_ATTEMPTS,
        )

    def _sender_thread_main(self) -> None:
        while True:
            item = self._outbox.get()
            if item is None:
                return
            try:
                self._deliver(*item)
            except Exception:
                log.exception('Unexpected error while delivering callback')

    def run(self):
        threading.Thread(target=self._periodically_flush_testcase_queue, daemon=True).start()
        threading.Thread(target=self._sender_thread_main, daemon=True).start()
        self._serving = True
        try:
            self.server.serve_forever()
        finally:
            self._serving = False

    def close(self):
        if self._closed:
            return
        self._closed = True
        if self._serving:
            self.server.shutdown()
        self.server.server_close()
        self._outbox.put(None)

    def disconnect(self):
        self.close()
        self.judge.abort_grading()
