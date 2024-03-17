import os
import shlex
import shutil
import stat
import subprocess
import tempfile
import uuid
from typing import List, TYPE_CHECKING

from dmoj.checkers import CheckerOutput
from dmoj.contrib import contrib_modules
from dmoj.cptbox import TracedPopen
from dmoj.cptbox.filesystem_policies import RecursiveDir
from dmoj.error import InternalError
from dmoj.executors import executors
from dmoj.executors.base_executor import BaseExecutor
from dmoj.graders.standard import StandardGrader
from dmoj.judgeenv import env, get_problem_root
from dmoj.problem import Problem, TestCase
from dmoj.result import Result
from dmoj.utils.helper_files import compile_with_auxiliary_files
from dmoj.utils.unicode import utf8bytes, utf8text

if TYPE_CHECKING:
    from dmoj.judge import JudgeWorker


STDIN_FD_FLAGS = os.O_RDONLY
STDOUT_FD_FLAGS = os.O_WRONLY | os.O_TRUNC | os.O_CREAT
STDOUT_FD_MODE = stat.S_IRUSR | stat.S_IRGRP | stat.S_IROTH | stat.S_IWUSR


def merge_results(first_result: Result, second_result: Result):
    """
    Merge second_result into first_result and return first_result

    Based on https://github.com/cms-dev/cms/blob/v1.4/cms/grading/steps/stats.py#L70-L125
    """
    if second_result is None:
        raise InternalError('The second result cannot be None')
    if first_result is None:
        return second_result

    first_result.execution_time += second_result.execution_time
    first_result.wall_clock_time = max(first_result.wall_clock_time, second_result.wall_clock_time)
    first_result.max_memory += second_result.max_memory
    first_result.result_flag |= second_result.result_flag

    return first_result


class CommunicationGrader(StandardGrader):
    _fifo_dir: List[str]
    _fifo_user_to_manager: List[str]
    _fifo_manager_to_user: List[str]
    _manager_proc: TracedPopen
    _user_procs: List[TracedPopen]
    _user_results: List[Result]

    def __init__(self, judge: 'JudgeWorker', problem: Problem, language: str, source: bytes) -> None:
        super().__init__(judge, problem, language, source)

        self.handler_data = self.problem.config.communication
        if 'manager' not in self.handler_data:
            raise InternalError('missing manager config')

        self.contrib_type = self.handler_data.get('type', 'default')
        if self.contrib_type not in contrib_modules:
            raise InternalError('%s is not a valid contrib module' % self.contrib_type)

        self.num_processes = int(self.handler_data.get('num_processes', 1))
        if self.num_processes < 1:
            raise InternalError('num_processes must be positive')

        self.manager_binary = self._generate_manager_binary()

    def populate_result(self, error: bytes, result: Result, process: TracedPopen) -> None:
        for i in range(self.num_processes):
            _user_proc, _user_result = self._user_procs[i], self._user_results[i]
            assert _user_proc.stderr is not None
            self.binary.populate_result(_user_proc.stderr.read(), _user_result, _user_proc)
            result = merge_results(result, _user_result)

        # The actual running time is the sum of every user process, but each
        # sandbox can only check its own; if the sum is greater than the time
        # limit we adjust the result.
        if result.execution_time > self.problem.time_limit:
            result.result_flag |= Result.TLE

    def check_result(self, case: TestCase, result: Result) -> CheckerOutput:
        if (case.config['checker'] or 'standard') != 'standard':
            return super().check_result(case, result)

        if result.result_flag:
            return False

        return contrib_modules[self.contrib_type].ContribModule.parse_return_code(
            self._manager_proc,
            self.manager_binary,
            case.points,
            self._manager_time_limit,
            self._manager_memory_limit,
            feedback=utf8text(result.proc_output, 'replace'),
            extended_feedback=utf8text(self._manager_stderr, 'replace'),
            name='manager',
            stderr=self._manager_stderr,
        )

    def _launch_process(self, case: TestCase) -> None:
        # Indices for the objects related to each user process
        indices = range(self.num_processes)

        # Create FIFOs for communication between manager and user processes
        self._fifo_dir = [tempfile.mkdtemp(prefix='fifo_') for i in indices]
        self._fifo_user_to_manager = [os.path.join(self._fifo_dir[i], 'u%d_to_m' % i) for i in indices]
        self._fifo_manager_to_user = [os.path.join(self._fifo_dir[i], 'm_to_u%d' % i) for i in indices]
        for i in indices:
            os.mkfifo(self._fifo_user_to_manager[i])
            os.mkfifo(self._fifo_manager_to_user[i])
            os.chmod(self._fifo_dir[i], 0o700)
            os.chmod(self._fifo_user_to_manager[i], 0o666)
            os.chmod(self._fifo_manager_to_user[i], 0o666)

        # Allow manager to write to FIFOs
        self.manager_binary.write_fs += [RecursiveDir(_dir) for _dir in self._fifo_dir]

        # Create manager process
        manager_args = []
        for i in indices:
            manager_args += [shlex.quote(self._fifo_user_to_manager[i]), shlex.quote(self._fifo_manager_to_user[i])]

        # https://github.com/cms-dev/cms/blob/v1.4/cms/grading/tasktypes/Communication.py#L319-L320
        self._manager_time_limit = self.num_processes * (self.problem.time_limit + 1.0)
        self._manager_memory_limit = self.handler_data.manager.memory_limit or env['generator_memory_limit']

        self._current_proc = self._manager_proc = self.manager_binary.launch(
            *manager_args,
            time=self._manager_time_limit,
            memory=self._manager_memory_limit,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )

        # Create user processes
        self._user_procs = []
        self._user_results = []
        for i in indices:
            # Setup std*** redirection
            stdin_fd = os.open(self._fifo_manager_to_user[i], STDIN_FD_FLAGS)
            stdout_fd = os.open(self._fifo_user_to_manager[i], STDOUT_FD_FLAGS, STDOUT_FD_MODE)

            self._user_procs.append(
                self.binary.launch(
                    time=self.problem.time_limit,
                    memory=self.problem.memory_limit,
                    symlinks=case.config.symlinks,
                    stdin=stdin_fd,
                    stdout=stdout_fd,
                    stderr=subprocess.PIPE,
                    wall_time=case.config.wall_time_factor * self.problem.time_limit,
                )
            )
            self._user_results.append(Result(case))

            # Close file descriptors passed to the process
            os.close(stdin_fd)
            os.close(stdout_fd)

    def _interact_with_process(self, case: TestCase, result: Result, input: bytes) -> bytes:
        result.proc_output, self._manager_stderr = self._manager_proc.communicate(input)

        self._manager_proc.wait()
        for _user_proc in self._user_procs:
            _user_proc.wait()

        # Cleanup FIFOs
        for _dir in self._fifo_dir:
            shutil.rmtree(_dir)

        return self._manager_stderr

    def _generate_binary(self) -> BaseExecutor:
        if 'signature' not in self.problem.config.communication:
            return super()._generate_binary()

        cpp_siggraders = ('C', 'C11', 'CPP03', 'CPP11', 'CPP14', 'CPP17', 'CPP20', 'CPPTHEMIS', 'CLANG', 'CLANGX')
        java_siggraders = ('JAVA', 'JAVA8', 'JAVA9', 'JAVA10', 'JAVA11', 'JAVA15', 'JAVA17')

        if self.language in cpp_siggraders:
            aux_sources = {}
            signature_data = self.problem.config.communication.signature

            entry_point = self.problem.problem_data[signature_data['entry']]
            header = self.problem.problem_data[signature_data['header']]

            submission_prefix = '#include "%s"\n' % signature_data['header']
            if not signature_data.get('allow_main', False):
                submission_prefix += '#define main main_%s\n' % uuid.uuid4().hex

            aux_sources[self.problem.id + '_submission'] = utf8bytes(submission_prefix) + self.source

            aux_sources[signature_data['header']] = header
            entry = entry_point
            return executors[self.language].Executor(
                self.problem.id, entry, aux_sources=aux_sources, defines=['-DSIGNATURE_GRADER']
            )
        elif self.language in java_siggraders:
            aux_sources = {}
            handler_data = self.problem.config.communication.signature['java']

            entry_point = self.problem.problem_data[handler_data['entry']]

            if not self.problem.config.communication.signature.get('allow_main', False):
                entry = entry_point
                aux_sources[self.problem.id + '_submission'] = self.source
            else:
                entry = self.source
                aux_sources[self.problem.id + '_lib'] = entry_point

            return executors[self.language].Executor(self.problem.id, entry, aux_sources=aux_sources)
        else:
            raise InternalError('no valid runtime for signature grading %s found' % self.language)

    def _generate_manager_binary(self) -> BaseExecutor:
        files = self.handler_data.manager.files
        if isinstance(files, str):
            filenames = [files]
        elif isinstance(files.unwrap(), list):
            filenames = list(files.unwrap())
        problem_root = get_problem_root(self.problem.id)
        assert problem_root is not None
        filenames = [os.path.join(problem_root, f) for f in filenames]
        flags = self.handler_data.manager.get('flags', [])
        unbuffered = self.handler_data.manager.get('unbuffered', True)
        lang = self.handler_data.manager.lang
        compiler_time_limit = self.handler_data.manager.compiler_time_limit
        return compile_with_auxiliary_files(
            filenames,
            flags,
            lang,
            compiler_time_limit,
            unbuffered,
        )
