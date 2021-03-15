from typing import Union

from dmoj.checkers._checker import standard
from dmoj.result import CheckerResult
from dmoj.utils.unicode import utf8bytes


def check(process_output: bytes, judge_output: bytes, pe_allowed: bool = True, **kwargs) -> Union[CheckerResult, bool]:
    if judge_output == process_output:
        return True
    feedback = None
    extended_feedback = None
    if pe_allowed:
        passed, standard_feedback = standard(utf8bytes(judge_output), utf8bytes(process_output))
        # in the event the standard checker would have passed the problem, raise a presentation error
        if passed:
            feedback = 'Presentation Error, check your whitespace'
            extended_feedback = standard_feedback.decode('utf-8')
    return CheckerResult(False, 0, feedback=feedback, extended_feedback=extended_feedback)
