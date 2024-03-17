import os
import shlex
import subprocess

from dmoj.contrib import contrib_modules
from dmoj.error import InternalError
from dmoj.judgeenv import env, get_problem_root
from dmoj.result import CheckerResult
from dmoj.utils.helper_files import compile_with_auxiliary_files, mkdtemp, mktemp
from dmoj.utils.unicode import utf8text


def get_executor(problem_id, files, flags, lang, compiler_time_limit):
    if isinstance(files, str):
        filenames = [files]
    elif isinstance(files.unwrap(), list):
        filenames = list(files.unwrap())

    filenames = [os.path.join(get_problem_root(problem_id), f) for f in filenames]
    executor = compile_with_auxiliary_files(filenames, flags, lang, compiler_time_limit)

    return executor


def check(
    process_output,
    judge_output,
    judge_input,
    problem_id,
    files,
    lang='CPP17',
    time_limit=env['generator_time_limit'],
    memory_limit=env['generator_memory_limit'],
    compiler_time_limit=env['generator_compiler_limit'],
    feedback=True,
    flags=None,
    type='default',
    args_format_string=None,
    point_value=None,
    input_name=None,
    output_name=None,
    treat_checker_points_as_percentage=False,
    **kwargs,
) -> CheckerResult:

    flags = flags or []
    if lang == 'PAS':
        flags.append('-Fu/usr/lib/fpc')
    elif type == 'themis':
        # Actually it should be `defines` instead of `flags`
        # but using `defines` requires more changes
        flags.append('-DTHEMIS')
    elif type == 'cms':
        flags.append('-DCMS')
    executor = get_executor(problem_id, files, flags, lang, compiler_time_limit)

    if type not in contrib_modules:
        raise InternalError('%s is not a valid contrib module' % type)

    if type == 'themis':
        """This is a small hack to use themis checker
        The themis checker has the following format:
            - stdin:
                - First line: path to the test data folder that contains an input file and an output file.
                - Second line: path to the folder that contains user's output.
        """
        if not input_name or not output_name:
            raise InternalError('Themis checker need input & output files')

        with mkdtemp() as test_data_folder, mkdtemp() as user_output_folder:
            if test_data_folder[-1] != '/':
                test_data_folder += '/'
            if user_output_folder[-1] != '/':
                user_output_folder += '/'

            input_file_path = os.path.join(test_data_folder, os.path.basename(input_name))
            with open(input_file_path, 'wb') as f:
                f.write(judge_input)

            answer_file_path = os.path.join(test_data_folder, os.path.basename(output_name))
            with open(answer_file_path, 'wb') as f:
                f.write(judge_output)

            user_output_file_path = os.path.join(user_output_folder, os.path.basename(output_name))
            with open(user_output_file_path, 'wb') as f:
                f.write(process_output)

            process = executor.launch(
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                memory=memory_limit,
                time=time_limit,
                path_case_fixes=[input_file_path, answer_file_path, user_output_file_path],
            )

            proc_output, error = process.communicate(input='\n'.join([test_data_folder, user_output_folder]).encode())
            proc_output = utf8text(proc_output, 'replace').strip()

            return contrib_modules[type].ContribModule.parse_return_code(
                process,
                executor,
                point_value,
                time_limit,
                memory_limit,
                feedback='',  # everything will be show in extended_feedback.
                extended_feedback=proc_output if feedback else '',
                name='checker',
                stderr=error,
            )

    with mktemp(judge_input) as input_file, mktemp(process_output) as output_file, mktemp(judge_output) as answer_file:
        args_format_string = args_format_string or contrib_modules[type].ContribModule.get_checker_args_format_string()
        checker_args = shlex.split(
            args_format_string.format(
                input_file=shlex.quote(input_file.name),
                output_file=shlex.quote(output_file.name),
                answer_file=shlex.quote(answer_file.name),
            )
        )
        process = executor.launch(
            *checker_args, stdout=subprocess.PIPE, stderr=subprocess.PIPE, memory=memory_limit, time=time_limit
        )

        proc_output, error = process.communicate()
        proc_output = utf8text(proc_output, 'replace')

        return contrib_modules[type].ContribModule.parse_return_code(
            process,
            executor,
            point_value,
            time_limit,
            memory_limit,
            feedback=proc_output if feedback else '',
            extended_feedback=utf8text(error, 'replace') if feedback else '',
            name='checker',
            stderr=error,
            treat_checker_points_as_percentage=treat_checker_points_as_percentage,
        )
