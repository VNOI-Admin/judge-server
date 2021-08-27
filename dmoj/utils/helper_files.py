import os
import requests
import signal
import tempfile

from dmoj.error import InternalError
from dmoj.result import Result
from dmoj.utils.os_ext import strsignal


def mktemp(data):
    tmp = tempfile.NamedTemporaryFile()
    tmp.write(data)
    tmp.flush()
    return tmp


def mkdtemp():
    return tempfile.TemporaryDirectory()


def compile_with_auxiliary_files(filenames, flags=[], lang=None, compiler_time_limit=None, unbuffered=False):
    from dmoj.executors import executors
    from dmoj.executors.compiled_executor import CompiledExecutor

    sources = {}

    for filename in filenames:
        with open(filename, 'rb') as f:
            sources[os.path.basename(filename)] = f.read()

    def find_runtime(languages):
        for grader in languages:
            if grader in executors:
                return grader
        return None

    use_cpp = any(map(lambda name: os.path.splitext(name)[1] in ['.cpp', '.cc'], filenames))
    use_c = any(map(lambda name: os.path.splitext(name)[1] in ['.c'], filenames))
    if lang is None:
        best_choices = ('CPP20', 'CPP17', 'CPP14', 'CPP11', 'CPP03') if use_cpp else ('C11', 'C')
        lang = find_runtime(best_choices)

    executor = executors.get(lang)
    if not executor:
        raise IOError(f'could not find an appropriate {lang} executor')

    executor = executor.Executor

    kwargs = {'fs': executor.fs + [tempfile.gettempdir()]}

    if issubclass(executor, CompiledExecutor):
        kwargs['compiler_time_limit'] = compiler_time_limit

    if hasattr(executor, 'flags'):
        kwargs['flags'] = flags + list(executor.flags)

    # Optimize the common case.
    if use_cpp or use_c:
        # Some auxiliary files (like those using testlib.h) take an extremely long time to compile, so we cache them.
        executor = executor('_aux_file', None, aux_sources=sources, cached=True, unbuffered=unbuffered, **kwargs)
    else:
        if len(sources) > 1:
            raise InternalError('non-C/C++ auxilary programs cannot be multi-file')
        executor = executor('_aux_file', list(sources.values())[0], cached=True, unbuffered=unbuffered, **kwargs)

    return executor


def parse_helper_file_error(proc, executor, name, stderr, time_limit, memory_limit):
    if proc.is_tle:
        error = '%s timed out (> %d seconds)' % (name, time_limit)
    elif proc.is_mle:
        error = '%s ran out of memory (> %s Kb)' % (name, memory_limit)
    elif proc.protection_fault:
        syscall, callname, args, update_errno = proc.protection_fault
        error = '%s invoked disallowed syscall %s (%s)' % (name, syscall, callname)
    elif proc.returncode:
        if proc.returncode > 0:
            error = '%s exited with nonzero code %d' % (name, proc.returncode)
        else:
            error = '%s exited with %s' % (name, strsignal(proc.signal))
        feedback = Result.get_feedback_str(stderr, proc, executor)
        if feedback:
            error += ' with feedback %s' % feedback
    else:
        return

    raise InternalError(error)


def download_source_code(link, file_size_limit):
    # MB to bytes
    file_size_limit = file_size_limit * 1024 * 1024

    r = requests.get(link, stream=True)
    try:
        r.raise_for_status()
    except Exception as e:
        raise InternalError(repr(e))

    if int(r.headers.get('Content-Length')) > file_size_limit:
        raise InternalError(f"Response size ({r.headers.get('Content-Length')}) is larger than file size limit")

    size = 0
    content = b''

    for chunk in r.iter_content(1024 * 1024):
        size += len(chunk)
        content += chunk
        if size > file_size_limit:
            raise InternalError('response too large')

    return content


class FunctionTimeout:
    def __init__(self, seconds=1, error_message='Timeout'):
        self.seconds = seconds
        self.error_message = error_message

    def handle_timeout(self, signum, frame):
        raise TimeoutError(self.error_message)

    def __enter__(self):
        signal.signal(signal.SIGALRM, self.handle_timeout)
        signal.setitimer(signal.ITIMER_REAL, self.seconds)

    def __exit__(self, type, value, traceback):
        signal.alarm(0)
