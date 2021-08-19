import requests

from dmoj.error import CompileError
from dmoj.executors.compiled_executor import CompiledExecutor


class Executor(CompiledExecutor):
    ext = 'sc3'
    name = 'SCRATCH'
    command = 'scrapec'
    test_program = '''\
https://gist.github.com/leduythuccs/c0dc83d4710e498348dc4c600a5cc209/raw/baf1d80bdf795fde02641e2b2cf4011a6b266896/test.sb3
'''

    def get_compile_args(self):
        return [self.get_command(), self._code, '-o', self.get_compiled_file()]

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

    def create_files(self, problem_id: str, source_code: bytes, *args, **kwargs) -> None:
        if problem_id == self.test_name or ('meta' in kwargs and kwargs['meta'].get('file_only', False)):
            source_code = self.download_source_code(
                source_code.decode().strip(),
                1 if problem_id == self.test_name else kwargs['meta']['file_size_limit']
            )

        return super(Executor, self).create_files(problem_id, source_code, *args, **kwargs)

    def get_executable(self) -> str:
        return '/usr/local/bin/scrape'

    def get_cmdline(self, **kwargs):
        return [
            '/usr/local/bin/scrape',
            self.get_compiled_file(),
        ]
