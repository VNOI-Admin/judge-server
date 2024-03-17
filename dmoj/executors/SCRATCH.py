import subprocess
from typing import List

from dmoj.cptbox import TracedPopen
from dmoj.cptbox.filesystem_policies import ExactFile, FilesystemAccessRule
from dmoj.error import CompileError, InternalError
from dmoj.executors.script_executor import ScriptExecutor
from dmoj.result import Result
from dmoj.utils.helper_files import download_source_code
from dmoj.utils.unicode import utf8bytes, utf8text


class Executor(ScriptExecutor):
    ext = 'sb3'
    command = 'scratch-run'
    nproc = -1
    address_grace = 1048576
    syscalls = ['eventfd2', 'statx']
    check_time = 10  # 10 seconds
    check_memory = 262144  # 256MB of RAM
    test_program = """\
https://raw.githubusercontent.com/VNOI-Admin/judge-server/master/asset/scratch_test_program.sb3
"""

    def __init__(self, problem_id: str, source_code: bytes, **kwargs) -> None:
        super().__init__(problem_id, source_code, **kwargs)
        self.meta = kwargs.get('meta', {})

    def get_fs(self) -> List[FilesystemAccessRule]:
        return super().get_fs() + [ExactFile('/etc/ssl/openssl.cnf'), ExactFile(self.runtime_dict['scratch-run'])]

    def validate_file(self, filename: str) -> None:
        command = self.get_command()
        assert command is not None
        assert self._dir is not None

        args = [command, '--check', filename]

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
            env=self.get_env(),
            cwd=utf8bytes(self._dir),
            nproc=self.get_nproc(),
            fsize=self.fsize,
        )

        _stdout, stderr = proc.communicate()

        if proc.is_tle:
            raise CompileError('Time Limit Exceeded while validating Scratch file')
        if proc.is_mle:
            raise CompileError('Memory Limit Exceeded while validating Scratch file')
        if proc.returncode != 0:
            if proc.returncode == 1 and b'Not a valid Scratch file' in stderr:
                raise CompileError(stderr)
            else:
                raise InternalError('Unknown error while validating Scratch file')

    def create_files(self, problem_id: str, source_code: bytes, *args, **kwargs) -> None:
        if problem_id == self.test_name or self.meta.get('file-only', False):
            source_code = download_source_code(
                source_code.decode().strip(), 1 if problem_id == self.test_name else self.meta.get('file-size-limit', 1)
            )

        super().create_files(problem_id, source_code, *args, **kwargs)

        self.validate_file(self._code)

    def populate_result(self, stderr: bytes, result: Result, process: TracedPopen) -> None:
        super().populate_result(stderr, result, process)
        if process.is_ir and b'scratch-vm encountered an error' in stderr:
            result.result_flag |= Result.RTE

    def parse_feedback_from_stderr(self, stderr: bytes, process: TracedPopen) -> str:
        if not stderr:
            return ''
        log = utf8text(stderr, 'replace')
        if b'scratch-vm encountered an error' in stderr:
            log = log.replace('scratch-vm encountered an error: ', '').strip()
            return '' if len(log) > 50 else log
        else:
            raise InternalError(log)
