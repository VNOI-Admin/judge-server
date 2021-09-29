from dmoj.contrib.default import ContribModule as DefaultContribModule
from dmoj.error import InternalError
from dmoj.result import CheckerResult
from dmoj.utils.helper_files import parse_helper_file_error


class ContribModule(DefaultContribModule):
    AC = 0

    name = 'themis'

    @classmethod
    def parse_return_code(
        cls, proc, executor, point_value, time_limit, memory_limit, feedback, extended_feedback, name, stderr
    ):
        if proc.returncode != cls.AC:
            try:
                parse_helper_file_error(proc, executor, name, stderr, time_limit, memory_limit)
            except InternalError as e:
                return CheckerResult(False, 0, feedback=f'Checker exitcode {proc.returncode}', extended_feedback=str(e))

            return CheckerResult(
                False, 0, feedback=f'Checker exitcode {proc.returncode}', extended_feedback=extended_feedback
            )
        else:
            # Don't need to strip() here because extended_feedback has already stripped.
            points = float(extended_feedback.split('\n')[-1]) * point_value
            # TODO (thuc): We should check 0 <= points <= point_value, but I don't want to raise an internal error
            # So I skip the check.

            # Use points != 0 is kinda risky because of the floating points
            return CheckerResult(
                True if points >= 1e-6 else False, points, feedback=feedback, extended_feedback=extended_feedback
            )
