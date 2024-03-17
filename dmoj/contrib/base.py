from typing import Any, TYPE_CHECKING

from dmoj.error import InternalError
from dmoj.executors.base_executor import BaseExecutor
from dmoj.result import CheckerResult

if TYPE_CHECKING:
    from dmoj.cptbox import TracedPopen


class BaseContribModule:
    name: str
    AC = 0
    WA = 1

    def catch_internal_error(f: Any) -> Any:
        def wrapper(*args, **kwargs) -> CheckerResult:
            try:
                return f(*args, **kwargs)
            except InternalError as e:
                proc = args[1]
                return CheckerResult(
                    False,
                    0,
                    feedback=f'Checker exitcode {proc.returncode}',
                    extended_feedback=str(e),
                )

        return wrapper

    @classmethod
    def get_checker_args_format_string(cls) -> str:
        raise NotImplementedError

    @classmethod
    def get_interactor_args_format_string(cls) -> str:
        raise NotImplementedError

    @classmethod
    def get_validator_args_format_string(cls) -> str:
        raise NotImplementedError

    @classmethod
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
        **kwargs,
    ):
        raise NotImplementedError
