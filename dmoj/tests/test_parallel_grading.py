import multiprocessing
import random
import threading
import time
import unittest
from typing import Dict, List, Optional, Set, Tuple

from dmoj.case_pool import CasePool, GradingChildError
from dmoj.judge import IPC, JudgeWorker, Submission
from dmoj.problem import TestCase
from dmoj.result import Result


class FakeCase(TestCase):
    def __init__(self, position: int, points: int, in_file: Optional[str], out_file: Optional[str]) -> None:
        self.position = position
        self.points = points
        self.config = {'in': in_file, 'out': out_file}
        self.output_prefix_length = 8


class FakeGrader:
    supports_parallel = True

    def __init__(self, verdicts: Dict[int, int], slow_case: Optional[int] = None, crash_case: Optional[int] = None):
        self.verdicts = verdicts
        self.slow_case = slow_case
        self.crash_case = crash_case
        self.aborted = threading.Event()

    def grade(self, case: FakeCase) -> Result:
        if case.position == self.crash_case:
            raise RuntimeError('grader exploded')
        if case.position == self.slow_case:
            self.aborted.wait(30)
        else:
            time.sleep(random.random() / 500)

        flag = self.verdicts[case.position]
        return Result(
            case,
            result_flag=flag,
            execution_time=case.position / 100,
            proc_output=b'output %d' % case.position,
            points=0 if flag else case.points,
        )

    def abort_grading(self) -> None:
        self.aborted.set()


def make_worker(grader: FakeGrader, short_circuit: bool) -> JudgeWorker:
    worker = JudgeWorker.__new__(JudgeWorker)
    worker.submission = Submission(1, 'fake', None, 'CPP17', '', 1.0, 65536, short_circuit, {})
    worker.grader = grader
    worker.case_pool = None
    worker._abort_requested = False
    worker._judge_process_conn = None
    return worker


def random_layout(rng: random.Random) -> Tuple[List[Tuple[Optional[int], FakeCase]], List[Set[int]], Dict[int, int]]:
    cases: List[Tuple[Optional[int], FakeCase]] = []
    dependencies: List[Set[int]] = []
    verdicts: Dict[int, int] = {}
    files = [None, 'a', 'b', 'c', 'd', 'e', 'f', 'g']

    def add_case(batch_number: Optional[int], points: int) -> None:
        position = len(cases)
        # A 0-point case hitting the result cache breaks later cache hits (pre-existing ZeroDivisionError), so keep
        # 0-point cases out of it.
        in_file = rng.choice(files) if points else 'zero%d' % position
        out_file = in_file and in_file + '.out'
        cases.append((batch_number, FakeCase(position, points, in_file, out_file)))
        verdicts[position] = rng.choices([Result.AC, Result.WA, Result.WA | Result.TLE], weights=[8, 1, 1])[0]

    # Pretests are forced to 0 points.
    for _ in range(rng.randint(0, 2)):
        add_case(None, 0)

    for _ in range(rng.randint(1, 8)):
        if rng.random() < 0.5:
            add_case(None, rng.choice([0, 1, 5]))
        else:
            batch_number = len(dependencies) + 1
            dependencies.append({dep for dep in range(1, batch_number) if rng.random() < 0.3})
            for _ in range(rng.randint(1, 5)):
                add_case(batch_number, rng.choice([0, 1, 5]))

    return cases, dependencies, verdicts


def summarize(messages) -> List[tuple]:
    summary = []
    for ipc_type, data in messages:
        if ipc_type == IPC.RESULT:
            batch_number, case_number, result = data
            summary.append(
                (
                    ipc_type,
                    batch_number,
                    case_number,
                    result.case.position,
                    result.result_flag,
                    result.points,
                    result.execution_time,
                    result.output,
                )
            )
        else:
            summary.append((ipc_type, data))
    return summary


class ParallelGradingTest(unittest.TestCase):
    def grade_sequentially(self, cases, dependencies, grader, short_circuit):
        worker = make_worker(grader, short_circuit)
        return summarize(worker._commit_results(cases, dependencies, lambda _, case: grader.grade(case)))

    def grade_in_parallel(self, cases, dependencies, grader, short_circuit, workers):
        worker = make_worker(grader, short_circuit)
        pool = CasePool(grader, cases, dependencies, short_circuit, [None] * workers)
        pool.start()
        try:
            return summarize(worker._commit_results(cases, dependencies, pool.get))
        finally:
            pool.close()

    def test_matches_sequential_grading(self):
        rng = random.Random(1234)
        for _ in range(150):
            cases, dependencies, verdicts = random_layout(rng)
            short_circuit = rng.random() < 0.3
            grader = FakeGrader(verdicts)
            expected = self.grade_sequentially(cases, dependencies, grader, short_circuit)
            for workers in (2, 4, 8):
                with self.subTest(layout=[(b, c.points, c.config['in']) for b, c in cases], workers=workers):
                    self.assertEqual(
                        self.grade_in_parallel(cases, dependencies, grader, short_circuit, workers), expected
                    )

        self.assertEqual(multiprocessing.active_children(), [])

    def test_abort(self):
        cases = [(None, FakeCase(i, 1, str(i), str(i))) for i in range(6)]
        grader = FakeGrader({i: Result.AC for i in range(6)}, slow_case=2)
        worker = make_worker(grader, False)
        worker.case_pool = pool = CasePool(grader, cases, [], False, [None] * 3)
        pool.start()
        threading.Timer(0.5, worker._do_abort).start()
        try:
            messages = list(worker._commit_results(cases, [], pool.get))
        finally:
            pool.close()

        self.assertEqual(messages[-1], (IPC.GRADING_ABORTED, ()))
        self.assertEqual(multiprocessing.active_children(), [])

    def test_child_crash(self):
        cases = [(None, FakeCase(i, 1, str(i), str(i))) for i in range(6)]
        grader = FakeGrader({i: Result.AC for i in range(6)}, crash_case=3)
        worker = make_worker(grader, False)
        pool = CasePool(grader, cases, [], False, [None] * 3)
        pool.start()
        try:
            with self.assertRaisesRegex(GradingChildError, 'grader exploded'):
                list(worker._commit_results(cases, [], pool.get))
        finally:
            pool.close()

        self.assertEqual(multiprocessing.active_children(), [])
