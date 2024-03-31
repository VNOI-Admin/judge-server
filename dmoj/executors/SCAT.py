import json
import os
import re
from zipfile import ZipFile

from dmoj.error import CompileError
from dmoj.executors.script_executor import ScriptExecutor
from dmoj.utils.helper_files import download_source_code
from dmoj.utils.unicode import utf8bytes, utf8text


class Executor(ScriptExecutor):
    ext = 'sb3'
    name = 'SCAT'
    nproc = -1
    command = 'scratch'
    syscalls = [
        'newselect',
        'select',
        'epoll_create1',
        'epoll_ctl',
        'epoll_wait',
        'epoll_pwait',
        'sched_yield',
        'setrlimit',
        'eventfd2',
        'statx',
    ]
    address_grace = 1048576
    test_program = "https://raw.githubusercontent.com/VNOI-Admin/judge-server/master/asset/scratch_test_program.sb3"
    item_filename = {}

    @classmethod
    def get_command(cls):
        cls._home = '%s_home' % cls.name.lower()
        if cls.command not in cls.runtime_dict or cls._home not in cls.runtime_dict:
            cls._home = None
            return None

        cls._home = cls.runtime_dict[cls._home]
        return cls.runtime_dict[cls.command]

    # Get media item's filename by doing dfs in json
    def dfs_json(self, node):
        if isinstance(node, list):
            node = {k: v for k, v in enumerate(node)}
        if isinstance(node, dict):
            for i in node:
                self.dfs_json(node[i])
            if 'assetId' in node and 'md5ext' in node:
                filename = node['md5ext']
                item_name = node['name'] + '.' + node['dataFormat']
                self.item_filename[item_name] = filename

    def create_files(self, problem_id: str, source_code: bytes) -> None:
        source_code_str = source_code.decode('utf-8')
        url_pattern = r'scratch.mit.edu\/projects\/([0-9]+)'
        match = re.search(url_pattern, source_code_str)

        if match:
            raise CompileError(
                'Chức năng nộp bài bằng link đã tắt. Các bạn hãy tải file sb3 và nộp bài bằng cách tải file lên từ máy.'
            )
        if source_code_str.endswith('.sb3'):
            self.create_files_from_url(source_code)
        else:
            self.create_files_from_json(source_code)

    def create_files_from_json(self, source_code):
        if not self._home:
            return
        try:
            source_json = json.loads(utf8bytes(source_code))
            self.dfs_json(source_json)
            sb3_file = ZipFile(self._code, mode='w')
            sb3_file.writestr('project.json', utf8bytes(source_code))
            media_files = os.listdir(os.path.join(self._home, 'media_files'))

            for item in media_files:
                filename = self.item_filename[item]
                path = os.path.join(self._home, 'media_files', item)
                sb3_file.write(path, filename)

            sb3_file.close()
        except json.decoder.JSONDecodeError:
            raise CompileError('Input is not a valid json file')
        except KeyError:
            raise CompileError('Please use default sounds/images only')

    def create_files_from_url(self, source_code):
        fize_size_limit = 1
        zip_data = download_source_code(utf8text(self.source).strip(), fize_size_limit)
        try:
            with open(self._code, 'wb') as f:
                f.write(zip_data)
        except Exception as e:
            raise CompileError(repr(e))
