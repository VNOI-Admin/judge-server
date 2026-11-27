from functools import partial
from types import SimpleNamespace
from unittest import TestCase
from unittest.mock import Mock

from dmoj.error import CheckerError
from dmoj.graders.standard import StandardGrader
from dmoj.packet import PacketManager


def fails(*args, **kwargs):
    raise RuntimeError('checker crashed')


def invalid_unicode(*args, **kwargs):
    raise UnicodeDecodeError('utf8', b'\xff', 0, 1, 'invalid byte')


class CheckerErrorMetadataTest(TestCase):
    def setUp(self):
        self.grader = StandardGrader.__new__(StandardGrader)
        self.grader.source = b''
        self.grader.language = 'PY3'
        self.grader.problem = SimpleNamespace(id='problem')
        self.case = SimpleNamespace(
            checker=lambda: partial(fails),
            output_data=lambda: b'expected',
            input_data=lambda: b'input',
            points=1,
            position=1,
            batch=0,
            has_binary_data=False,
        )
        self.result = SimpleNamespace(result_flag=0, proc_output=b'output', execution_time=0.1)

    def test_unhandled_checker_exception_is_tagged(self):
        with self.assertRaisesRegex(CheckerError, 'error executing checker') as error:
            self.grader.check_result(self.case, self.result)
        self.assertIsInstance(error.exception.__cause__, RuntimeError)

    def test_checker_load_failure_is_tagged(self):
        self.case.checker = fails
        with self.assertRaisesRegex(CheckerError, 'error loading checker'):
            self.grader.check_result(self.case, self.result)

    def test_normal_result_and_unicode_wa_are_preserved(self):
        self.case.checker = lambda: partial(lambda *args, **kwargs: True)
        self.assertIs(self.grader.check_result(self.case, self.result), True)
        self.case.checker = lambda: partial(invalid_unicode)
        result = self.grader.check_result(self.case, self.result)
        self.assertFalse(result.passed)
        self.assertEqual(result.feedback, 'invalid unicode')

    def test_failed_data_reads_are_not_tagged(self):
        def missing_data():
            raise OSError('missing data')

        self.case.output_data = missing_data
        with self.assertRaisesRegex(OSError, 'missing data'):
            self.grader.check_result(self.case, self.result)
        self.case.output_data = lambda: b'expected'
        self.case.input_data = missing_data
        self.case.checker = lambda: partial(lambda *args, **kwargs: bytes(kwargs['judge_input']))
        with self.assertRaisesRegex(OSError, 'missing data'):
            self.grader.check_result(self.case, self.result)

    def test_packet_uses_optional_metadata_without_changing_name_or_message(self):
        manager = SimpleNamespace(
            judge=SimpleNamespace(current_submission=SimpleNamespace(id=42)),
            _flush_testcase_queue=Mock(),
            _send_packet=Mock(),
        )
        expected = {'name': 'internal-error', 'submission-id': 42, 'message': 'traceback'}
        PacketManager.internal_error_packet(manager, 'traceback')
        manager._send_packet.assert_called_once_with(expected)
        manager._send_packet.reset_mock()
        PacketManager.internal_error_packet(manager, 'traceback', error_type='checker')
        manager._send_packet.assert_called_once_with({**expected, 'error-type': 'checker'})
        self.assertEqual(manager._flush_testcase_queue.call_count, 2)
