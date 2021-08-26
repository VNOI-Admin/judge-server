from io import BytesIO
from zipfile import ZipFile

from dmoj.error import CompileError
from dmoj.executors.python_executor import PythonExecutor
from dmoj.utils.helper_files import download_source_code


class Executor(PythonExecutor):
    loader_script = '''\
import runpy, sys, os
from zipfile import ZipFile
del sys.argv[0]
sys.stdin = os.fdopen(0, 'r', 65536)
sys.stdout = os.fdopen(1, 'w', 65536)
with ZipFile(sys.argv[0]) as output:
    output_name = input()
    if output_name not in output.namelist():
        raise Exception("`" + output_name + "` not found in zip file")
    sys.stdout.buffer.write(output.open(output_name).read())
'''
    unbuffered_loader_script = loader_script
    command = 'python3'
    command_paths = ['python%s' % i for i in ['3.6', '3.5', '3.4', '3.3', '3.2', '3.1', '3']]
    test_program = '''\
https://gist.github.com/leduythuccs/c0dc83d4710e498348dc4c600a5cc209/raw/3b6060eab89a4ef6c7532e72938d003cccf550a2/test.zip
'''
    name = 'OUTPUT'
    ext = 'zip'

    def create_files(self, problem_id, source_code, *args, **kwargs):
        if problem_id == self.test_name or self.meta.get('file-only', False):
            source_code = download_source_code(
                source_code.decode().strip(),
                1 if problem_id == self.test_name else self.meta.get('file-size-limit', 1)
            )

        self.validate_file(source_code)
        super().create_files(problem_id, source_code, *args, **kwargs)

    def validate_file(self, source_code):
        try:
            with ZipFile(BytesIO(source_code)):
                pass
        except Exception as e:
            raise CompileError(repr(e))
