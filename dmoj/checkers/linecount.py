from typing import Callable

from dmoj.checkers._checker import linecount
from dmoj.result import CheckerResult
from dmoj.utils.unicode import utf8bytes


def check(
    process_output: bytes,
    judge_output: bytes,
    point_value: float,
    _checker: Callable[[bytes, bytes], tuple] = linecount,
    **kwargs
) -> CheckerResult:
    passed, feedback = _checker(utf8bytes(judge_output), utf8bytes(process_output))
    return CheckerResult(passed, point_value if passed else 0, extended_feedback=feedback.decode('utf-8'))
