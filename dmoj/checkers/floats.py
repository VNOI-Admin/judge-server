from re import split as resplit
from typing import Union

from dmoj.error import InternalError
from dmoj.result import CheckerResult
from dmoj.utils.format_feedback import compress, english_ending
from dmoj.utils.unicode import utf8bytes


def verify_absolute(process_float: float, judge_float: float, epsilon: float) -> bool:
    # Since process_float can be NaN, this is NOT equivalent to
    # (process_float - judge_float) > epsilon;  the code below will always
    # reject NaN, even if judge_float is NaN
    return abs(process_float - judge_float) <= epsilon


def error_absolute(process_float: float, judge_float: float) -> float:
    return abs(process_float - judge_float)


def verify_relative(process_float: float, judge_float: float, epsilon: float) -> bool:
    p1 = min(judge_float * (1 - epsilon), judge_float * (1 + epsilon))
    p2 = max(judge_float * (1 - epsilon), judge_float * (1 + epsilon))
    # Since process_float can be NaN, this is NOT equivalent to
    # (process_float < p1 or process_float > p2)
    return p1 <= process_float <= p2


def error_relative(process_float: float, judge_float: float) -> float:
    absolute = abs(process_float - judge_float)
    # if judge_float is too small, we return absolute error instead
    if abs(judge_float) > 1e-9:
        return abs(absolute / judge_float)
    return absolute


def verify_default(process_float: float, judge_float: float, epsilon: float) -> bool:
    # process_float can be NaN
    # in this case, we reject NaN as a possible answer, even if judge_float is NaN
    return (
        abs(process_float - judge_float) <= epsilon
        or abs(judge_float) >= epsilon
        and abs(1.0 - process_float / judge_float) <= epsilon
    )


def error_default(process_float: float, judge_float: float) -> float:
    absolute = abs(process_float - judge_float)
    # if judge_float is too small, we return absolute error instead
    if abs(judge_float) > 1e-9:
        return min(absolute, abs(absolute / judge_float))
    return absolute


def check(
    process_output: bytes,
    judge_output: bytes,
    point_value: float,
    precision: int = 6,
    error_mode: str = 'default',
    **kwargs,
) -> Union[CheckerResult, bool]:
    # Discount empty lines
    process_lines = list(filter(None, resplit(b'[\r\n]', utf8bytes(process_output))))
    judge_lines = list(filter(None, resplit(b'[\r\n]', utf8bytes(judge_output))))

    if len(process_lines) != len(judge_lines):
        return CheckerResult(
            False,
            0,
            'Presentation Error',
            f"Judge output's has {len(judge_lines)} non-empty line(s), participant's output has {len(process_lines)}",
        )

    verify_float = {'absolute': verify_absolute, 'relative': verify_relative, 'default': verify_default}.get(error_mode)
    error_float = {'absolute': error_absolute, 'relative': error_relative, 'default': error_default}.get(error_mode)
    if not verify_float or not error_float:
        raise InternalError('invalid `error_mode` value')

    epsilon = 10 ** -int(precision)

    try:
        cnt_line = 0
        cnt_token = 0
        for process_line, judge_line in zip(process_lines, judge_lines):
            cnt_line += 1
            process_tokens = process_line.split()
            judge_tokens = judge_line.split()

            if len(process_tokens) != len(judge_tokens):
                return CheckerResult(
                    False,
                    0,
                    'Presentation Error',
                    "{}{} line differs, judge's output has {} token(s), participant's output has {}".format(
                        cnt_line, english_ending(cnt_line), len(judge_tokens), len(process_tokens)
                    ),
                )

            for process_token, judge_token in zip(process_tokens, judge_tokens):
                cnt_token += 1
                # Allow mixed tokens, for lines like "abc 0.68 def 0.70"
                try:
                    judge_float = float(judge_token)
                except ValueError:
                    # If it's not a float the token must match exactly
                    if process_token != judge_token:
                        return CheckerResult(
                            False,
                            0,
                            None,
                            "{}{} token differs - expected: '{}', found: '{}'".format(
                                cnt_token, english_ending(cnt_token), compress(judge_token), compress(process_token)
                            ),
                        )
                else:
                    try:
                        process_float = float(process_token)
                    except ValueError:
                        return CheckerResult(
                            False,
                            0,
                            'Presentation Error',
                            "{}{} token differs - expected float: '{}', found: '{}'".format(
                                cnt_token, english_ending(cnt_token), compress(judge_token), compress(process_token)
                            ),
                        )
                    if not verify_float(process_float, judge_float, epsilon):
                        return CheckerResult(
                            False,
                            0,
                            None,
                            "{0}{1} number differs - expected: '{2:.{5}f}', found: '{3:.{5}f}', error = '{4:.{5}f}'".format(
                                cnt_token,
                                english_ending(cnt_token),
                                judge_float,
                                process_float,
                                error_float(process_float, judge_float),
                                precision + 2,
                            ),
                        )
    except Exception as e:
        return CheckerResult(False, 0, 'Checker error', str(e))
    return CheckerResult(True, point_value, None, f'{cnt_token} token(s)')
