import unittest
from functools import partial
from types import SimpleNamespace
from unittest import mock

from dmoj.contrib.base import BaseContribModule
from dmoj.contrib.coci import ContribModule as CociContribModule
from dmoj.error import CheckerError, InternalError
from dmoj.judge import IPC, Judge, JudgeWorker
from dmoj.packet import PacketManager
from dmoj.graders.standard import StandardGrader
from dmoj.result import CheckerResult
from dmoj.testsuite import TestManager, Tester


class CheckerErrorTest(unittest.TestCase):
    def test_internal_error_is_checker_error_only_for_checker(self):
        original = InternalError('checker failed')

        def parse_return_code(cls, proc, name):
            raise original

        parse_return_code = BaseContribModule.catch_internal_error(parse_return_code)
        process = SimpleNamespace(returncode=3)

        with self.assertRaises(CheckerError) as raised:
            parse_return_code(None, process, name='checker')
        self.assertIs(raised.exception.__cause__, original)

        result = parse_return_code(None, process, name='interactor')
        self.assertFalse(result.passed)
        self.assertEqual(result.feedback, 'Checker exitcode 3')

    def make_grader(self, checker, *, output_data=None, input_data=None):
        grader = StandardGrader.__new__(StandardGrader)
        grader.source = b''
        grader.language = 'PY3'
        grader.problem = SimpleNamespace(id='problem')
        case = SimpleNamespace(
            checker=lambda: partial(checker),
            output_data=output_data or (lambda: b'answer'),
            input_data=input_data or (lambda: b'input'),
            points=1,
            position=1,
            batch=0,
            has_binary_data=False,
        )
        result = SimpleNamespace(result_flag=0, proc_output=b'output', execution_time=0.1)
        return grader, case, result

    def test_checker_invocation_errors_and_invalid_returns_are_typed(self):
        grader, case, result = self.make_grader(lambda *args, **kwargs: True)

        def load_error():
            raise OSError('missing checker')

        case.checker = load_error
        with self.assertRaises(CheckerError) as raised:
            grader.check_result(case, result)
        self.assertIsInstance(raised.exception.__cause__, OSError)

        def raises(*args, **kwargs):
            raise ValueError('bad checker')

        grader, case, result = self.make_grader(raises)
        with self.assertRaises(CheckerError) as raised:
            grader.check_result(case, result)
        self.assertIsInstance(raised.exception.__cause__, ValueError)

        grader, case, result = self.make_grader(lambda *args, **kwargs: None)
        with self.assertRaises(CheckerError):
            grader.check_result(case, result)

        def compile_error(*args, **kwargs):
            from dmoj.error import CompileError

            raise CompileError('checker compilation failed')

        grader, case, result = self.make_grader(compile_error)
        with self.assertRaises(CheckerError) as raised:
            grader.check_result(case, result)
        self.assertIn('checker compilation failed', str(raised.exception.__cause__))

    def test_checker_data_errors_keep_their_original_type(self):
        grader, case, result = self.make_grader(
            lambda *args, **kwargs: True,
            output_data=lambda: (_ for _ in ()).throw(OSError('missing answer')),
        )
        with self.assertRaisesRegex(OSError, 'missing answer'):
            grader.check_result(case, result)

        def raises_on_lazy_input(*args, **kwargs):
            bytes(kwargs['judge_input'])
            return True

        grader, case, result = self.make_grader(
            raises_on_lazy_input,
            input_data=lambda: (_ for _ in ()).throw(OSError('missing input')),
        )
        with self.assertRaisesRegex(OSError, 'missing input'):
            grader.check_result(case, result)

    def test_valid_checker_results_are_preserved(self):
        grader, case, result = self.make_grader(lambda *args, **kwargs: CheckerResult(True, 0.5))
        check = grader.check_result(case, result)
        self.assertTrue(check.passed)
        self.assertEqual(check.points, 0.5)

    def test_invalid_checker_result_fields_are_typed(self):
        invalid_results = (
            ('passed', 'yes'),
            ('points', float('nan')),
            ('points', float('inf')),
            ('points', '1'),
            ('feedback', 42),
        )
        for field, value in invalid_results:
            with self.subTest(field=field, value=value):

                def invalid_result(*args, **kwargs):
                    check = CheckerResult(True, 1)
                    setattr(check, field, value)
                    return check

                grader, case, result = self.make_grader(invalid_result)
                with self.assertRaises(CheckerError):
                    grader.check_result(case, result)

    def test_coci_checker_failures_are_typed_but_interactor_failures_stay_wa(self):
        for process in (
            SimpleNamespace(returncode=3, is_tle=False, is_mle=False, protection_fault=None),
            SimpleNamespace(returncode=-9, is_tle=True, is_mle=False, protection_fault=None),
        ):
            with self.subTest(process=process):
                with self.assertRaises(CheckerError):
                    CociContribModule.parse_return_code(process, None, 1, 1, 65536, '', '', name='checker', stderr=b'')

        process = SimpleNamespace(returncode=-9, is_tle=True, is_mle=False, protection_fault=None)
        result = CociContribModule.parse_return_code(process, None, 1, 1, 65536, '', '', name='interactor', stderr=b'')
        self.assertFalse(result.passed)

    def test_float_checker_errors_are_typed_and_unicode_behavior_is_preserved(self):
        from dmoj.checkers import floats

        with self.assertRaises(CheckerError):
            floats.check(b'2', b'1', point_value=1, precision='6')

        malformed = floats.check(b'abc', b'1', point_value=1)
        self.assertFalse(malformed.passed)
        self.assertEqual(malformed.feedback, 'Presentation Error')

        invalid_unicode = floats.check(b'\xff', b'1', point_value=1)
        self.assertFalse(invalid_unicode.passed)
        self.assertEqual(invalid_unicode.feedback, 'Checker error')

        self.assertTrue(floats.check(b'1', b'1', point_value=1).passed)
        self.assertFalse(floats.check(b'2', b'1', point_value=1).passed)

    def test_testsuite_distinguishes_checker_errors_from_internal_errors(self):
        self.assertIn('CKE', Tester.all_codes)

        manager = TestManager()
        manager.set_expected({'CKE'}, {}, None, {}, None, {}, None, {})
        manager.internal_error_packet('checker traceback', 'checker')
        self.assertFalse(manager.failed)

        manager.set_expected({'IE'}, {}, None, {}, None, {}, None, {})
        manager.internal_error_packet('infra traceback')
        self.assertFalse(manager.failed)
        manager.internal_error_packet('checker traceback', 'checker')
        self.assertTrue(manager.failed)

    def test_internal_error_packet_has_optional_checker_type(self):
        packet_manager = PacketManager.__new__(PacketManager)
        packet_manager.conn = None
        packet_manager._closed = True
        packet_manager.judge = SimpleNamespace(current_submission=SimpleNamespace(id=42))
        packet_manager._flush_testcase_queue = mock.Mock()
        packet_manager._send_packet = mock.Mock()

        packet_manager.internal_error_packet('traceback')
        packet = packet_manager._send_packet.call_args.args[0]
        self.assertNotIn('error-type', packet)

        packet_manager.internal_error_packet('traceback', 'checker')
        packet = packet_manager._send_packet.call_args.args[0]
        self.assertEqual(packet['error-type'], 'checker')

    def test_judge_forwards_optional_checker_type(self):
        judge = Judge.__new__(Judge)
        judge.packet_manager = mock.Mock()
        judge._ipc_unhandled_exception(None, 'traceback', 'checker')
        judge.packet_manager.internal_error_packet.assert_called_once_with('traceback', error_type='checker')

    def test_worker_sends_optional_checker_type_with_chained_traceback(self):
        class Connection:
            def __init__(self):
                self.messages = []

            def send(self, message):
                self.messages.append(message)

            def recv(self):
                return IPC.BYE, ()

        def run_worker(error):
            worker = JudgeWorker.__new__(JudgeWorker)

            def fail_grading():
                if isinstance(error, CheckerError):
                    try:
                        raise ValueError('checker root cause')
                    except ValueError as cause:
                        raise error from cause
                raise error
                yield

            worker._grade_cases = fail_grading
            worker._do_abort = mock.Mock()
            worker.grader = None
            connection = Connection()
            worker._worker_process_main(connection, mock.Mock())
            return connection.messages

        checker_messages = run_worker(CheckerError('checker failed'))
        error_message = next(data for ipc, data in checker_messages if ipc == IPC.UNHANDLED_EXCEPTION)
        self.assertEqual(error_message[1], 'checker')
        self.assertIn('ValueError: checker root cause', error_message[0])
        self.assertIn('CheckerError: checker failed', error_message[0])

        infrastructure_messages = run_worker(ValueError('infra failed'))
        error_message = next(data for ipc, data in infrastructure_messages if ipc == IPC.UNHANDLED_EXCEPTION)
        self.assertEqual(len(error_message), 1)


if __name__ == '__main__':
    unittest.main()
