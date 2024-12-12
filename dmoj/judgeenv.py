import argparse
import glob
import hashlib
import logging
import os
import ssl
import tempfile
from collections import defaultdict
from fnmatch import fnmatch
from operator import itemgetter
from typing import Dict, Iterable, List, Optional, Set, Tuple
import pickle

import yaml

from dmoj.config import ConfigNode
from dmoj.utils import pyyaml_patch  # noqa: F401, imported for side effect
from dmoj.utils.ansi import print_ansi
from dmoj.utils.unicode import utf8bytes, utf8text
from dmoj.utils.glob_ext import find_glob_root

storage_namespaces: Dict[Optional[str], List[str]] = {}
problem_globs: List[str] = []
problem_watches: List[str] = []
logger = logging.getLogger(__name__)
env: ConfigNode = ConfigNode(
    defaults={
        'selftest_time_limit': 60,  # 60 seconds
        'selftest_memory_limit': 131072,  # 128mb of RAM
        'generator_compiler_time_limit': 30,  # 30 seconds
        'generator_time_limit': 20,  # 20 seconds
        'generator_memory_limit': 524288,  # 512mb of RAM
        'validator_compiler_time_limit': 30,  # 30 seconds
        'validator_time_limit': 20,  # 20 seconds
        'validator_memory_limit': 524288,  # 512mb of RAM
        'compiler_time_limit': 30,  # Kill compiler after 10 seconds
        'compiler_size_limit': 131072,  # Maximum allowable compiled file size, 128mb
        'compiler_output_character_limit': 65536,  # Number of characters allowed in compile output
        'compiled_binary_cache_dir': None,  # Location to store cached binaries, defaults to tempdir
        'compiled_binary_cache_size': 100,  # Maximum number of executables to cache (LRU order)
        'test_size_limit': 262144,  # Maximum allowable test size, 256mb
        'runtime': {},
        # Map of executor: fs_config, used to configure
        # the filesystem sandbox on a per-machine basis, without having to hack
        # executor source.
        # fs_config is a list of dictionaries. Each dictionary should contain one key/value pair.
        # Three keys are possible:
        # `exact_file`, to allow a specific file
        # `exact_dir`, to allow listing files in a directory
        # `recursive_dir`, to allow everything under and including a directory
        # Example YAML:
        # extra_fs:
        #   PERL:
        #   - exact_file: /dev/dtrace/helper
        #   - exact_dir: /some/exact/directory
        #   - recursive_dir: /some/directory/and/all/children
        'extra_fs': {},
        # List of judge URLs to ping on problem data updates (the URLs are expected
        # to host judges running with --api-host and --api-port)
        'update_pings': [],
        # Directory to use as temporary submission storage, system default
        # (e.g. /tmp) if left blank.
        'tempdir': None,
        # CPU affinity (as a list of 0-indexed CPU IDs) to run submissions on
        'submission_cpu_affinity': None,
    },
    dynamic=False,
)
_root: str = os.path.dirname(__file__)

log_file = server_host = server_port = no_ansi = skip_self_test = no_watchdog = problem_regex = case_regex = None
cli_history_file = cert_store = api_listen = None
secure: bool = False
no_cert_check: bool = False
log_level = logging.DEBUG

startup_warnings: List[str] = []
cli_command: List[str] = []

only_executors: Set[str] = set()
exclude_executors: Set[str] = set()


class StorageNamespaceCache:
    problem_root_cache: Dict[str, str] = {}
    problem_roots_cache: Optional[List[str]] = None
    supported_problems_cache: Optional[List[Tuple[str, float]]] = None

    def __str__(self) -> str:
        return (
            f"StorageNamespaceCache(\n"
            f"  problem_root_cache: {self.problem_root_cache},\n"
            f"  problem_roots_cache: {self.problem_roots_cache},\n"
            f"  supported_problems_cache: {self.supported_problems_cache}\n"
            f")"
        )

_storage_namespace_cache: Dict[Optional[str], StorageNamespaceCache] = defaultdict(StorageNamespaceCache)


def load_env(cli: bool = False, testsuite: bool = False) -> None:  # pragma: no cover
    global storage_namespaces, problem_globs, only_executors, exclude_executors, log_file, server_host, server_port, no_ansi, no_ansi_emu, skip_self_test, env, startup_warnings, no_watchdog, problem_regex, case_regex, api_listen, secure, no_cert_check, cert_store, problem_watches, cli_history_file, cli_command, log_level

    if cli:
        description = 'Starts a shell for interfacing with a local judge instance.'
    else:
        description = 'Spawns a judge for a submission server.'

    parser = argparse.ArgumentParser(description=description)
    if not cli:
        parser.add_argument('server_host', help='host to connect for the server')
        parser.add_argument('judge_name', nargs='?', help='judge name (overrides configuration)')
        parser.add_argument('judge_key', nargs='?', help='judge key (overrides configuration)')
        parser.add_argument('-p', '--server-port', type=int, default=9999, help='port to connect for the server')
    elif not testsuite:
        parser.add_argument('command', nargs='*', help='invoke CLI command without spawning shell')
        parser.add_argument(
            '--history',
            type=str,
            default='~/.dmoj_history',
            help='file to load and save command history (default: ~/.dmoj_history)',
        )

    parser.add_argument(
        '-c',
        '--config',
        type=str,
        default='~/.dmojrc',
        help='file to load judge configurations from (default: ~/.dmojrc)',
    )

    parser.add_argument(
        '-d',
        '--debug',
        action='store_const',
        const=logging.DEBUG,
        default=logging.INFO,
        dest='log_level',
    )

    if not cli:
        parser.add_argument('-l', '--log-file', help='log file to use')
        parser.add_argument('--no-watchdog', action='store_true', help='disable use of watchdog on problem directories')
        parser.add_argument('--skip-first-scan', action='store_true', help='skip the first scan of problem directories')
        parser.add_argument(
            '-a',
            '--api-port',
            type=int,
            default=None,
            help='port to listen for the judge API (do not expose to public, '
            'security is left as an exercise for the reverse proxy)',
        )
        parser.add_argument('-A', '--api-host', default='127.0.0.1', help='IPv4 address to listen for judge API')

        parser.add_argument('-s', '--secure', action='store_true', help='connect to server via TLS')
        parser.add_argument('-k', '--no-certificate-check', action='store_true', help='do not check TLS certificate')
        parser.add_argument(
            '-T', '--trusted-certificates', default=None, help='use trusted certificate file instead of system'
        )

    _group = parser.add_mutually_exclusive_group()
    _group.add_argument('-e', '--only-executors', help='only listed executors will be loaded (comma-separated)')
    _group.add_argument('-x', '--exclude-executors', help='prevent listed executors from loading (comma-separated)')

    parser.add_argument('--no-ansi', action='store_true', help='disable ANSI output')

    parser.add_argument('--skip-self-test', action='store_true', help='skip executor self-tests')

    if testsuite:
        parser.add_argument('tests_dir', help='directory where tests are stored')
        parser.add_argument('problem_regex', help='when specified, only matched problems will be tested', nargs='?')
        parser.add_argument('case_regex', help='when specified, only matched cases will be tested', nargs='?')

    args = parser.parse_args()

    server_host = getattr(args, 'server_host', None)
    server_port = getattr(args, 'server_port', None)
    cli_command = getattr(args, 'command', [])
    cli_history_file = getattr(args, 'history', None)
    if cli_history_file:
        cli_history_file = os.path.expanduser(cli_history_file)

    no_ansi = args.no_ansi
    skip_self_test = args.skip_self_test
    no_watchdog = True if cli else args.no_watchdog
    log_level = args.log_level
    if not cli:
        api_listen = (args.api_host, args.api_port) if args.api_port else None

        if ssl:
            secure = args.secure
            no_cert_check = args.no_certificate_check
            cert_store = args.trusted_certificates

    log_file = getattr(args, 'log_file', None)
    only_executors |= args.only_executors and set(args.only_executors.split(',')) or set()
    exclude_executors |= args.exclude_executors and set(args.exclude_executors.split(',')) or set()

    is_docker = bool(os.getenv('DMOJ_IN_DOCKER'))
    if is_docker:
        if not cli:
            api_listen = api_listen or ('0.0.0.0', 15001)

        with open('/judge-runtime-paths.yml', 'rb') as runtimes_file:
            env.update(yaml.safe_load(runtimes_file))

        problem_globs = ['/problems/**/']

    model_file = os.path.expanduser(args.config)
    try:
        with open(model_file) as init_file:
            env.update(yaml.safe_load(init_file))
    except IOError:
        if not is_docker:
            raise

    if getattr(args, 'judge_name', None):
        env['id'] = args.judge_name
    elif 'DMOJ_JUDGE_NAME' in os.environ:
        env['id'] = os.environ['DMOJ_JUDGE_NAME']

    if not is_docker and not cli and not testsuite:
        folder_name = hashlib.sha384(utf8bytes(env['id'])).hexdigest()
        env['tempdir'] = os.path.join(tempfile.gettempdir(), folder_name)
        os.makedirs(env['tempdir'], exist_ok=True)

    if getattr(args, 'judge_key', None):
        env['key'] = args.judge_key
    elif 'DMOJ_JUDGE_KEY' in os.environ:
        env['key'] = os.environ['DMOJ_JUDGE_KEY']

    if not testsuite:
        storage_namespaces[None] = env.problem_storage_globs or []
        storage_namespaces.update(env.storage_namespaces or {})

        all_problem_globs = []
        for globs in storage_namespaces.values():
            all_problem_globs.extend(globs)

        if not all_problem_globs:
            raise SystemExit('no problems available to grade')

        problem_globs = storage_namespaces[None]
        problem_watches = problem_globs
    else:
        if not os.path.isdir(args.tests_dir):
            raise SystemExit('Invalid tests directory')
        problem_globs = [os.path.join(args.tests_dir, '*')]
        storage_namespaces[None] = problem_globs

        import re

        if args.problem_regex:
            try:
                problem_regex = re.compile(args.problem_regex)
            except re.error:
                raise SystemExit('Invalid problem regex')
        if args.case_regex:
            try:
                case_regex = re.compile(args.case_regex)
            except re.error:
                raise SystemExit('Invalid case regex')

    for namespace in storage_namespaces:
        _storage_namespace_cache[namespace] = StorageNamespaceCache()

    skip_first_scan = False if cli else args.skip_first_scan
    if not skip_first_scan:
        # Populate cache and send warnings
        get_supported_problems_and_mtimes()
    else:
        for namespace, globs in storage_namespaces.items():
            cache = _storage_namespace_cache[namespace]
            cache.problem_roots_cache = [str(root) for root in map(find_glob_root, globs)]
            cache.supported_problems_cache = []


def get_problem_watches():
    return problem_watches


def get_problem_root(problem_id, namespace=None) -> Optional[str]:
    def _find_problem_root():
        cache = _storage_namespace_cache[namespace]
        cached_root = cache.problem_root_cache.get(problem_id)

        if cached_root is None or not os.path.isfile(os.path.join(cached_root, 'init.yml')):
            for root_dir in get_problem_roots(namespace):
                problem_root_dir = os.path.join(root_dir, problem_id)
                problem_config = os.path.join(problem_root_dir, 'init.yml')
                if os.path.isfile(problem_config):
                    if problem_globs and not any(
                        fnmatch(problem_config, os.path.join(problem_glob, 'init.yml'))
                        for problem_glob in problem_globs
                    ):
                        continue
                    cache.problem_root_cache[problem_id] = problem_root_dir
                    break
            else:
                return None
        return cache.problem_root_cache[problem_id]

    problem_root = _find_problem_root()
    if problem_root:
        return problem_root

    # Recalculate the cache based on filecache
    logger.error('root_dir is None. 1st retry. cache=%s', _storage_namespace_cache[namespace])
    clear_storage_cache(namespace)
    get_supported_problems_and_mtimes(force_update=False)
    problem_root = _find_problem_root()
    if problem_root:
        return problem_root

    # Recalculate the cache with scanning
    logger.error('root_dir is None. 2nd retry. cache=%s', _storage_namespace_cache[namespace])
    clear_storage_cache(namespace)
    get_supported_problems_and_mtimes(force_update=True)
    problem_root = _find_problem_root()
    if problem_root:
        return problem_root

    return None


def get_problem_roots(namespace=None) -> List[str]:
    cache = _storage_namespace_cache[namespace]
    assert cache.problem_roots_cache is not None
    return cache.problem_roots_cache


def clear_storage_cache(namespace=None) -> None:
    _storage_namespace_cache[namespace] = StorageNamespaceCache()


def get_supported_problems_and_mtimes(warnings: bool = True, force_update: bool = False) -> List[Tuple[str, float]]:
    """
    Fetches a list of all problems supported by this judge and their mtimes.
    :return:
        A list of all problems in tuple format: (problem id, mtime)
    """
    cache = _storage_namespace_cache[None]

    if cache.supported_problems_cache is not None and not force_update:
        return cache.supported_problems_cache

    problems = []
    root_dirs = []
    root_dirs_set = set()
    problem_dirs: Dict[str, str] = {}

    def process_problem_config(problem_config: str) -> Optional[Tuple[str, str, str, float]]:
        if not os.access(problem_config, os.R_OK):
            return None

        problem_dir = os.path.dirname(problem_config)
        problem = utf8text(os.path.basename(problem_dir))
        root_dir = os.path.dirname(problem_dir)
        mtime = os.path.getmtime(problem_dir)

        return problem, problem_dir, root_dir, mtime

    for dir_glob in problem_globs:
        cache_file: str = os.path.join(dir_glob.rstrip('*/'), 'cache.pkl')
        current_problems = []
        current_root_dirs = []

        # Try to load from cache
        if not force_update and os.path.exists(cache_file):
            try:
                with open(cache_file, 'rb') as f:
                    cached_data = pickle.load(f)
                    current_problems, current_root_dirs, cached_problem_dirs = cached_data
                    problem_dirs.update(cached_problem_dirs)
                    problems.extend(current_problems)
                    for rd in current_root_dirs:
                        if rd not in root_dirs_set:
                            root_dirs.append(rd)
                            root_dirs_set.add(rd)
                    continue
            except (IOError, pickle.PickleError) as e:
                print(f"Failed to read from cache file {cache_file}: {e}")

        # Scan directory if cache fails or force_update is True
        current_problem_dirs = {}
        for problem_config in glob.iglob(os.path.join(dir_glob, 'init.yml'), recursive=True):
            result = process_problem_config(problem_config)
            if not result:
                continue

            problem, problem_dir, root_dir, mtime = result

            if root_dir not in root_dirs_set:
                current_root_dirs.append(root_dir)
                root_dirs_set.add(root_dir)

            if problem in problem_dirs:
                if warnings:
                    print_ansi(
                        f'#ansi[Warning: duplicate problem {problem} found at {problem_dir},'
                        f' ignoring in favour of {problem_dirs[problem]}](yellow)'
                    )
            else:
                problem_dirs[problem] = problem_dir
                current_problem_dirs[problem] = problem_dir
                current_problems.append((problem, mtime))

        problems.extend(current_problems)
        root_dirs.extend(current_root_dirs)

        # Update cache file
        try:
            with open(cache_file, 'wb') as fw:
                pickle.dump((current_problems, current_root_dirs, current_problem_dirs), fw)
        except (IOError, pickle.PickleError) as e:
            print(f"Failed to write cache file {cache_file}: {e}")

    cache.problem_roots_cache = root_dirs
    cache.supported_problems_cache = problems
    cache.problem_root_cache = problem_dirs

    return problems


def get_supported_problems(warnings: bool = True) -> Iterable[str]:
    return map(itemgetter(0), get_supported_problems_and_mtimes(warnings=warnings))


def get_runtime_versions():
    from dmoj.executors import executors

    return {name: clazz.Executor.get_runtime_versions() for name, clazz in executors.items()}
