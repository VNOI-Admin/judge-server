import re

from dmoj.contrib.testlib import ContribModule as TestlibContribModule
from dmoj.error import InternalError
from dmoj.result import CheckerResult


class ContribModule(TestlibContribModule):
    name = 'cms'
    repartial = re.compile(r'^([-+]?[0-9]*\.?[0-9]+([eE][-+]?[0-9]+)?)', re.M)

    @classmethod
    def get_checker_args_format_string(cls):
        return '{input_file} {answer_file} {output_file}'

    @classmethod
    def parse_return_code(cls, proc, executor, point_value, time_limit, memory_limit, feedback, extended_feedback, name, stderr):
        if proc.returncode == cls.AC:
            match = cls.repartial.search(feedback)
            if not match:
                raise InternalError('Invalid stderr for partial points: %r' % feedback)
            percentage = float(match.group(1))
            if not 0.0 <= percentage <= 1.0:
                raise InternalError('Invalid partial points: %f, must be between [0; 1]' % percentage)
            points = percentage * point_value
            return CheckerResult(percentage != 0, points, extended_feedback=extended_feedback)
        else:
            return CheckerResult(False, 0, feedback="Checker exitcode %d" % proc.returncode, extended_feedback=extended_feedback)
