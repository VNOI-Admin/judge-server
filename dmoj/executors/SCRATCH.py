import requests

from dmoj.error import CompileError
from dmoj.executors.script_executor import ScriptExecutor


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
            raise CompileError(repr(e))

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

    def create_files(self, problem_id, source_code, *args, **kwargs):
        if problem_id == self.test_name or self.meta.get('file-only', False):
            source_code = self.download_source_code(
                source_code.decode().strip(),
                1 if problem_id == self.test_name else self.meta.get('file-size-limit', 1)
            )

        super().create_files(problem_id, source_code, *args, **kwargs)
