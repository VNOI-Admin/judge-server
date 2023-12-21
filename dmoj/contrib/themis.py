from dmoj.contrib.default import ContribModule as DefaultContribModule
from dmoj.error import InternalError
from dmoj.result import CheckerResult
from dmoj.utils.helper_files import parse_helper_file_error


class ContribModule(DefaultContribModule):
    AC = 0

    name = 'themis'

    @classmethod
    @DefaultContribModule.catch_internal_error
    def parse_return_code(
        cls, proc, executor, point_value, time_limit, memory_limit, feedback, extended_feedback, name, stderr, **kwargs
    ):
        if proc.returncode != cls.AC:
            parse_helper_file_error(proc, executor, name, stderr, time_limit, memory_limit)
        else:
            try:
                # Don't need to strip() here because extended_feedback has already stripped.
                points = float(extended_feedback.split('\n')[-1]) * point_value
            except ValueError as e:
                # In case the last line is not a float number, raise Internal Error
                # so that the wrapper catch_internal_error will catch the exception
                raise InternalError(e)
            # TODO (thuc): We should check 0 <= points <= point_value, but I don't want to raise an internal error
            # So I skip the check.

            # Use points != 0 is kinda risky because of the floating points
            return CheckerResult(
                True if points >= 1e-6 else False, points, feedback=feedback, extended_feedback=extended_feedback
            )
