import os
import shutil
import subprocess
import requests

from dmoj.cptbox import TracedPopen
from dmoj.error import CompileError, InternalError
from dmoj.executors.script_executor import ScriptExecutor
from dmoj.result import Result
from dmoj.utils import setbufsize_path
from dmoj.utils.unicode import utf8bytes, utf8text


class Executor(ScriptExecutor):
    ext = 'sc3'
    name = 'SCRATCH'
    command = 'scratch-run'
    nproc = -1
    address_grace = 1048576
    syscalls = [
        'eventfd2',
        'epoll_create1',
        'epoll_ctl',
        'epoll_wait',
        'statx',
    ]
    check_time = 10  # 10 seconds
    check_memory = 262144  # 256mb of RAM
    test_program = '''\
https://gist.github.com/leduythuccs/c0dc83d4710e498348dc4c600a5cc209/raw/baf1d80bdf795fde02641e2b2cf4011a6b266896/test.sb3
'''

    def __init__(self, problem_id, source_code, **kwargs):
        super().__init__(problem_id, source_code, **kwargs)
        self.meta = kwargs.get('meta', {})

    def download_source_code(self, link, file_size_limit):
        # MB to bytes
        file_size_limit = file_size_limit * 1024 * 1024

        r = requests.get(link, stream=True)
        try:
            r.raise_for_status()
        except Exception as e:
            raise InternalError(repr(e))

        if int(r.headers.get('Content-Length')) > file_size_limit:
            raise CompileError(f"Response size ({r.headers.get('Content-Length')}) is larger than file size limit")

        size = 0
        content = b''

        for chunk in r.iter_content(1024 * 1024):
            size += len(chunk)
            content += chunk
            if size > file_size_limit:
                raise CompileError('response too large')

        return content

    def validate_file(self, filename):
        # Based on PlatformExecutorMixin.launch

        agent = self._file('setbufsize.so')
        shutil.copyfile(setbufsize_path, agent)
        env = {
            'LD_LIBRARY_PATH': os.environ.get('LD_LIBRARY_PATH', ''),
            'LD_PRELOAD': agent,
        }
        env.update(self.get_env())

        args = [self.get_command(), '--check', filename]

        proc = TracedPopen(
            [utf8bytes(a) for a in args],
            executable=utf8bytes(self.get_executable()),
            security=self.get_security(),
            address_grace=self.get_address_grace(),
            data_grace=self.data_grace,
            personality=self.personality,
            time=self.check_time,
            memory=self.check_memory,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            env=env,
            cwd=utf8bytes(self._dir),
            nproc=self.get_nproc(),
            fsize=self.fsize,
        )

        stdout, stderr = proc.communicate()

        if proc.is_tle:
            raise CompileError('Time Limit Exceeded while validating Scratch file')
        if proc.is_mle:
            raise CompileError('Memory Limit Exceeded while validating Scratch file')
        if proc.returncode != 0:
            if proc.returncode == 1 and b'Not a valid Scratch file' in stderr:
                raise CompileError('Not a valid Scratch file')
            else:
                raise InternalError('Unknown error while validating Scratch file')

    def create_files(self, problem_id, source_code, *args, **kwargs):
        if problem_id == self.test_name or self.meta.get('file-only', False):
            source_code = self.download_source_code(
                source_code.decode().strip(),
                1 if problem_id == self.test_name else self.meta.get('file-size-limit', 1)
            )

        super().create_files(problem_id, source_code, *args, **kwargs)

        self.validate_file(self._code)

    def populate_result(self, stderr, result, process):
        super().populate_result(stderr, result, process)
        if process.is_ir and b'scratch-vm encountered an error' in stderr:
            result.result_flag |= Result.RTE

    def parse_feedback_from_stderr(self, stderr, process):
        log = utf8text(stderr, 'replace')
        if b'scratch-vm encountered an error' in stderr:
            log = log.replace('scratch-vm encountered an error: ', '').strip()
            return '' if len(log) > 50 else log
        else:
            raise InternalError(log)
