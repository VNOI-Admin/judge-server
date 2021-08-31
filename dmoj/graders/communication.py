import os
import shlex
import subprocess
import uuid

from dmoj.contrib import contrib_modules
from dmoj.error import InternalError
from dmoj.executors import executors
from dmoj.graders.standard import StandardGrader
from dmoj.judgeenv import env, get_problem_root
from dmoj.utils.helper_files import compile_with_auxiliary_files, mktemp
from dmoj.utils.unicode import utf8bytes, utf8text


class CommunicationGrader(StandardGrader):
    def __init__(self, judge, problem, language, source):
        super().__init__(judge, problem, language, source)
        self.handler_data = self.problem.config.communication
        self.manager_binary = self._generate_manager_binary()
        self.contrib_type = self.handler_data.get('type', 'default')
        if self.contrib_type not in contrib_modules:
            raise InternalError('%s is not a valid contrib module' % self.contrib_type)

    def check_result(self, case, result):
        raise NotImplementedError()

    def _launch_process(self, case):
        raise NotImplementedError()

    def _interact_with_process(self, case, result, input):
        raise NotImplementedError()

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
