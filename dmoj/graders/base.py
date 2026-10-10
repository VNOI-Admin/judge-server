from typing import List, Optional, TYPE_CHECKING

from dmoj.cptbox import TracedPopen
from dmoj.executors.base_executor import BaseExecutor
from dmoj.problem import Problem, TestCase
from dmoj.result import Result
from dmoj.utils.unicode import utf8bytes

if TYPE_CHECKING:
    from dmoj.judge import JudgeWorker


class BaseGrader:
    source: bytes
    language: str
    problem: Problem
    judge: 'JudgeWorker'
    binary: BaseExecutor
    _current_proc: Optional[TracedPopen]
    # Whether test cases may be graded concurrently, each in a forked copy of this grader. Graders that carry state
    # from one test case to the next must set this to False.
    supports_parallel = True

    def __init__(self, judge: 'JudgeWorker', problem: Problem, language: str, source: bytes) -> None:
        self.source = utf8bytes(source)
        self.language = language
        self.problem = problem
        self.judge = judge
        self.binary = self._generate_binary()
        self._abort_requested = False
        self._current_proc = None

    def grade(self, case: TestCase) -> Result:
        raise NotImplementedError

    def _generate_binary(self) -> BaseExecutor:
        raise NotImplementedError

    def use_private_executors(self) -> List[BaseExecutor]:
        """
        Called in each forked process grading cases concurrently. Launching the submission writes into its directory
        (symlinks, file IO links to the current case's input), so each process needs its own copy.

        Returns the replaced executors: the caller must keep them alive, since dropping the last reference would delete
        the directory the other processes still use.
        """
        shared = self.binary
        if getattr(shared, '_dir', None) is None:
            return []
        self.binary = shared.clone()
        return [shared]

    def cleanup_private_executors(self) -> None:
        self.binary.cleanup()

    def abort_grading(self) -> None:
        self._abort_requested = True
        if self._current_proc:
            try:
                self._current_proc.kill()
            except OSError:
                pass
