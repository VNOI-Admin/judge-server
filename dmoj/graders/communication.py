import os
import shlex
import stat
import subprocess
import tempfile
import uuid

from dmoj.contrib import contrib_modules
from dmoj.error import InternalError
from dmoj.executors import executors
from dmoj.graders.standard import StandardGrader
from dmoj.judgeenv import env, get_problem_root
from dmoj.utils.helper_files import compile_with_auxiliary_files
from dmoj.utils.unicode import utf8bytes


class CommunicationGrader(StandardGrader):
    def __init__(self, judge, problem, language, source):
        super().__init__(judge, problem, language, source)
        self.handler_data = self.problem.config.communication
        self.manager_binary = self._generate_manager_binary()
        self.num_processes = self.handler_data.get('num_processes', 1)
        self.contrib_type = self.handler_data.get('type', 'default')
        if self.contrib_type not in contrib_modules:
            raise InternalError('%s is not a valid contrib module' % self.contrib_type)

    def populate_result(self, error, result, process):
        raise NotImplementedError()

    def check_result(self, case, result):
        raise NotImplementedError()

    def _launch_process(self, case):
        # Indices for the objects related to each user process
        indices = range(self.num_processes)

        # Create FIFOs for communication between manager and user processes
        fifo_dir = [tempfile.mkdtemp() for i in indices]
        fifo_user_to_manager = [
            os.path.join(fifo_dir[i], "u%d_to_m" % i) for i in indices]
        fifo_manager_to_user = [
            os.path.join(fifo_dir[i], "m_to_u%d" % i) for i in indices]
        for i in indices:
            os.mkfifo(fifo_user_to_manager[i])
            os.mkfifo(fifo_manager_to_user[i])
            os.chmod(fifo_dir[i], 0o755)
            os.chmod(fifo_user_to_manager[i], 0o666)
            os.chmod(fifo_manager_to_user[i], 0o666)

        # Create user processes
        self._user_procs = [None for i in indices]
        for i in indices:
            stdin_fd = os.open(fifo_manager_to_user[i],
                               os.O_RDONLY)
            stdout_fd = os.open(fifo_user_to_manager[i],
                                os.O_WRONLY | os.O_TRUNC | os.O_CREAT,
                                stat.S_IRUSR | stat.S_IRGRP |
                                stat.S_IROTH | stat.S_IWUSR)
            self._user_procs[i] = self.binary.launch(
                time=self.problem.time_limit,
                memory=self.problem.memory_limit,
                symlinks=case.config.symlinks,
                stdin=stdin_fd,
                stdout=stdout_fd,
                stderr=subprocess.PIPE,
                wall_time=case.config.wall_time_factor * self.problem.time_limit,
            )
            os.close(stdin_fd)
            os.close(stdout_fd)

        # Create manager processes
        manager_args = []
        for i in indices:
            manager_args += [shlex.quote(fifo_user_to_manager[i]), shlex.quote(fifo_manager_to_user[i])]

        manager_time_limit = self.num_processes * (self.problem.time_limit + 1.0)
        manager_memory_limit = self.handler_data.manager.memory_limit or env['generator_memory_limit']

        self._manager_proc = self.manager_binary.launch(
            *manager_args,
            time=manager_time_limit,
            memory=manager_memory_limit,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )

    def _interact_with_process(self, case, result, input):
        result.proc_output, error = self._manager_proc.communicate(input)

        self._manager_proc.wait()
        for _user_proc in self._user_procs:
            _user_proc.wait()

        # TODO: cleanup fifo_dir

        return error

    def _generate_binary(self):
        siggraders = ('C', 'C11', 'CPP03', 'CPP11', 'CPP14', 'CPP17', 'CPP20', 'CLANG', 'CLANGX')

        if self.language in siggraders:
            aux_sources = {}
            signature_data = self.problem.config.communication.signature  # FIXME: check if key exists

            entry_point = self.problem.problem_data[signature_data['entry']]
            header = self.problem.problem_data[signature_data['header']]

            submission_prefix = '#include "%s"\n' % signature_data['header']
            if not signature_data.get('allow_main', False):
                submission_prefix += '#define main main_%s\n' % uuid.uuid4().hex

            aux_sources[self.problem.id + '_submission'] = utf8bytes(submission_prefix) + self.source

            aux_sources[signature_data['header']] = header
            entry = entry_point
            return executors[self.language].Executor(
                self.problem.id, entry, aux_sources=aux_sources, defines=['-DSIGNATURE_GRADER'],
            )
        else:
            raise InternalError('no valid runtime for signature grading %s found' % self.language)

    def _generate_manager_binary(self):
        # FIXME: check if manager key exists
        files = self.handler_data.manager.files
        if isinstance(files, str):
            filenames = [files]
        elif isinstance(files.unwrap(), list):
            filenames = list(files.unwrap())
        filenames = [os.path.join(get_problem_root(self.problem.id), f) for f in filenames]
        flags = self.handler_data.manager.get('flags', [])
        unbuffered = self.handler_data.manager.get('unbuffered', True)
        lang = self.handler_data.manager.lang
        compiler_time_limit = self.handler_data.manager.compiler_time_limit
        return compile_with_auxiliary_files(
            filenames, flags, lang, compiler_time_limit, unbuffered,
        )
