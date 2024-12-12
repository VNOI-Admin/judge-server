import re
from typing import TYPE_CHECKING

from dmoj.contrib.default import ContribModule as DefaultContribModule
from dmoj.error import InternalError
from dmoj.executors.base_executor import BaseExecutor
from dmoj.result import CheckerResult
from dmoj.utils.helper_files import parse_helper_file_error

if TYPE_CHECKING:
    from dmoj.cptbox import TracedPopen


class ContribModule(DefaultContribModule):
    AC = 0
    WA = 1
    PARTIAL = 2
    IE = 3
    PE = 4

    name = 'lqdoj'
    repartial = re.compile(br'^([-+]?[0-9]*\.?[0-9]+([eE][-+]?[0-9]+)?)', re.M)

    @classmethod
    def get_checker_args_format_string(cls):
        return '{input_file} {output_file} {answer_file}'

    @classmethod
    def get_interactor_args_format_string(cls):
        return '{input_file} {answer_file}'

    @classmethod
    @DefaultContribModule.catch_internal_error
    def parse_return_code(
        cls,
        proc: 'TracedPopen',
        executor: BaseExecutor,
        point_value: float,
        time_limit: float,
        memory_limit: int,
        feedback: str,
        extended_feedback: str,
        name: str,
        stderr: bytes,
        treat_checker_points_as_percentage: bool = False,
        **kwargs,
    ):
        if proc.returncode == cls.AC:
            return CheckerResult(True, point_value, feedback=feedback, extended_feedback=extended_feedback)
        elif proc.returncode == cls.PARTIAL:
            match = cls.repartial.search(stderr)
            if not match:
                raise InternalError('Invalid stderr for partial points: %r' % stderr)
            points = float(match.group(0))
            if not 0 <= points <= 1:
                raise InternalError('Invalid partial points: %d' % points)

            ac = points == 1
            return CheckerResult(ac, points * point_value, feedback=feedback, extended_feedback=extended_feedback)
        elif proc.returncode == cls.WA:
            return CheckerResult(False, 0, feedback=feedback, extended_feedback=extended_feedback)
        elif proc.returncode == cls.PE:
            return CheckerResult(
                False, 0, feedback=feedback or 'Presentation Error', extended_feedback=extended_feedback
            )
        elif proc.returncode == cls.IE:
            raise InternalError('%s failed assertion with message %s %s' % (name, feedback, extended_feedback))
        else:
            parse_helper_file_error(proc, executor, name, stderr, time_limit, memory_limit)
