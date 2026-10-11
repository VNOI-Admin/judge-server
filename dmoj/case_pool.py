"""
Grades the test cases of a single submission concurrently, in several forked children.

The judge worker process compiles the submission, then forks one child per grading slot. Children inherit the grader
(and with it the compiled binary) and the resolved test cases, so only case indices and results cross the pipes.

The pool only ever *computes* results; it never decides what gets reported. The worker's commit loop walks the cases in
order with the usual short-circuiting logic and asks the pool for the results it needs, so the reported results are
exactly those of sequential grading. Cases are graded speculatively ahead of the commit loop; the pool skips cases that
a speculative failure guarantees will be short-circuited, and grades any case the commit loop asks for on demand.
"""

import logging
import multiprocessing
import os
import sys
import threading
import traceback
from multiprocessing.connection import Connection, wait
from typing import Any, Dict, Iterable, List, Optional, Set, Tuple

from dmoj.judgeenv import env
from dmoj.problem import BaseTestCase
from dmoj.result import Result
from dmoj.utils.unicode import utf8bytes

logger = logging.getLogger(__name__)

# How long to wait for children to exit before killing them, in seconds.
SHUTDOWN_TIMEOUT = 10

_PENDING, _RUNNING, _DONE, _SKIPPED = range(4)


class GradingChildError(Exception):
    pass


class CasePool:
    def __init__(
        self,
        grader: Any,
        flattened_cases: List[Tuple[Optional[int], BaseTestCase]],
        batch_dependencies: List[Set[int]],
        short_circuit: bool,
        slots: List[Optional[List[int]]],
        inherited_conns: Iterable[Connection] = (),
    ) -> None:
        self.grader = grader
        self.cases = flattened_cases
        self.batch_dependencies = batch_dependencies
        self.short_circuit = short_circuit
        self.slots = slots[: len(flattened_cases)]
        self.inherited_conns = list(inherited_conns)

        self._state = [_PENDING] * len(flattened_cases)
        self._results: Dict[int, Result] = {}
        self._demanded: List[int] = []
        self._failed_batches: Set[int] = set()
        self._next_index = 0
        self._aborted = False

        # Cases sharing (input, output) with an earlier positive-point case are answered from the commit loop's cache,
        # so we only grade them if the commit loop asks for them.
        seen_keys: Set[Tuple[Any, Any]] = set()
        for index, (_, case) in enumerate(flattened_cases):
            key = (case.config['in'], case.config['out'])
            if key in seen_keys:
                self._state[index] = _SKIPPED
            elif case.points != 0 and key != (None, None):
                seen_keys.add(key)

        self._conns: List[Connection] = []
        self._send_locks: List[threading.Lock] = []
        self._processes: List[Any] = []
        self._running_on: Dict[Connection, int] = {}

    def start(self) -> None:
        context = multiprocessing.get_context('fork')
        for slot in self.slots:
            conn, child_conn = context.Pipe()
            process = context.Process(
                name='%s (case pool)' % multiprocessing.current_process().name,
                target=self._child_main,
                args=(child_conn, [*self.inherited_conns, *self._conns], slot),
            )
            process.start()
            child_conn.close()
            self._conns.append(conn)
            self._send_locks.append(threading.Lock())
            self._processes.append(process)

    def get(self, index: int, _case: Optional[BaseTestCase] = None) -> Result:
        """
        Returns the result of grading case `index`, grading it now if that hasn't happened yet.
        """
        if self._state[index] in (_PENDING, _SKIPPED):
            self._state[index] = _PENDING
            self._demanded.append(index)

        while index not in self._results:
            if self._aborted:
                # The commit loop reports the abort as soon as it sees any result.
                return Result(self.cases[index][1], result_flag=Result.SC)
            self._dispatch()
            self._receive()

        return self._results[index]

    def abort(self) -> None:
        self._aborted = True
        for conn, lock in zip(self._conns, self._send_locks):
            try:
                with lock:
                    conn.send(('abort',))
            except Exception:
                pass

    def close(self) -> None:
        for conn, lock in zip(self._conns, self._send_locks):
            try:
                with lock:
                    conn.send(('stop',))
            except Exception:
                pass

        for process in self._processes:
            process.join(timeout=SHUTDOWN_TIMEOUT)
            if process.is_alive():
                logger.error('Case pool child is still alive, sending SIGKILL!')
                process.kill()
                process.join()

        for conn in self._conns:
            conn.close()

    def _next_case(self) -> Optional[int]:
        while self._demanded:
            index = self._demanded.pop()
            if self._state[index] == _PENDING:
                return index

        while self._next_index < len(self.cases):
            index = self._next_index
            self._next_index += 1
            if self._state[index] == _PENDING:
                return index

        return None

    def _dispatch(self) -> None:
        if self._aborted:
            return

        for conn, lock in zip(self._conns, self._send_locks):
            if conn in self._running_on:
                continue

            index = self._next_case()
            if index is None:
                return

            self._state[index] = _RUNNING
            self._running_on[conn] = index
            with lock:
                conn.send(('grade', index))

    def _receive(self) -> None:
        busy = list(self._running_on)
        if not busy:
            if self._aborted:
                return
            raise GradingChildError('nothing to wait for, case pool is stuck')

        for conn in wait(busy):
            assert isinstance(conn, Connection)
            try:
                message = conn.recv()
            except EOFError:
                raise GradingChildError('case pool child died while grading') from None

            index = self._running_on.pop(conn)
            if message[0] == 'error':
                raise GradingChildError('case pool child failed:\n' + message[1])

            _, result_index, result = message
            assert result_index == index
            # The pickled case lost its config; give the commit loop the real one back.
            result.case = self.cases[index][1]
            self._results[index] = result
            self._state[index] = _DONE

            if result.result_flag & Result.WA:
                self._prune_after_failure(index)

    def _prune_after_failure(self, failed_index: int) -> None:
        """
        Skips cases that are guaranteed to be short-circuited now that `failed_index` failed. This is only an
        optimization: the commit loop decides what is short-circuited, and demands any case it needs.
        """
        failed_batch, failed_case = self.cases[failed_index]

        if self.short_circuit or not failed_case.points:
            self._skip(range(failed_index + 1, len(self.cases)))
            return

        if failed_batch is None:
            return

        self._skip(
            index
            for index in range(failed_index + 1, len(self.cases))
            if self.cases[index][0] == failed_batch
        )

        self._failed_batches.add(failed_batch)
        for batch_number in range(failed_batch + 1, len(self.batch_dependencies) + 1):
            if self.batch_dependencies[batch_number - 1] & self._failed_batches:
                self._failed_batches.add(batch_number)
        self._skip(
            index for index, (batch_number, _) in enumerate(self.cases) if batch_number in self._failed_batches
        )

    def _skip(self, indices: Iterable[int]) -> None:
        for index in indices:
            if self._state[index] == _PENDING:
                self._state[index] = _SKIPPED

    def _child_main(self, conn: Connection, inherited_conns: List[Connection], cpus: Optional[List[int]]) -> None:
        # Never return normally: running finalizers here would e.g. delete the compiled binary, which the other children
        # are still using.
        shared_executors: List[Any] = []
        try:
            suffix = ' on CPU %s' % ','.join(map(str, cpus)) if cpus else ''
            _set_proc_title(multiprocessing.current_process().name + suffix)

            for inherited in inherited_conns:
                inherited.close()

            # Cases share one Problem, whose archive handle would otherwise share its file offset across children.
            problem = getattr(self.cases[0][1], 'problem', None) if self.cases else None
            if problem is not None:
                problem.problem_data.reopen_archive()

            if hasattr(self.grader, 'use_private_executors'):
                # Held until we exit: releasing them would delete directories the other children still use.
                shared_executors = self.grader.use_private_executors()

            if cpus:
                # Pin both ourselves (the tracer) and every process we launch to this slot's CPUs.
                os.sched_setaffinity(0, cpus)
                env['submission_cpu_affinity'] = cpus

            self._child_loop(conn)
        except BaseException:  # noqa: B036, we must never fall through to the finalizers
            logger.exception('Case pool child crashed')
        finally:
            if shared_executors:
                try:
                    self.grader.cleanup_private_executors()
                except Exception:
                    logger.exception('Failed to clean up private executors')
            sys.stdout.flush()
            sys.stderr.flush()
            os._exit(0)

    def _child_loop(self, conn: Connection) -> None:
        jobs: List[Optional[int]] = []
        jobs_ready = threading.Condition()

        def recv_thread_main() -> None:
            while True:
                try:
                    message = conn.recv()
                except Exception:
                    message = ('stop',)

                if message[0] == 'abort':
                    self.grader.abort_grading()
                    continue

                with jobs_ready:
                    jobs.append(message[1] if message[0] == 'grade' else None)
                    jobs_ready.notify()
                if message[0] == 'stop':
                    return

        threading.Thread(target=recv_thread_main, daemon=True).start()

        while True:
            with jobs_ready:
                while not jobs:
                    jobs_ready.wait()
                index = jobs.pop(0)

            if index is None:
                return

            try:
                result = self.grader.grade(self.cases[index][1])
                # Same trimming as the sequential path: only the trimmed output crosses the pipe.
                result.proc_output = utf8bytes(result.output)
            except Exception:
                conn.send(('error', ''.join(traceback.format_exception(*sys.exc_info()))))
                return

            conn.send(('result', index, result))


def _set_proc_title(title: str) -> None:
    try:
        from setproctitle import setproctitle
    except ImportError:
        return
    setproctitle(title)
