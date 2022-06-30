from dmoj.error import CompileError
from dmoj.executors.script_executor import ScriptExecutor
from dmoj.utils.unicode import utf8bytes

import os
import json
import re
import requests
import time
from zipfile import ZipFile

class Executor(ScriptExecutor):
    ext='sb3'
    name = 'SCAT'
    nproc=-1
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
    test_program = '{"targets":[{"isStage":true,"name":"Stage","variables":{"`jEk@4|i[#Fk?(8x)AV.-my variable":["n","123"]},"lists":{},"broadcasts":{},"blocks":{},"comments":{},"currentCostume":0,"costumes":[{"assetId":"cd21514d0531fdffb22204e0ec5ed84a","name":"backdrop1","md5ext":"cd21514d0531fdffb22204e0ec5ed84a.svg","dataFormat":"svg","rotationCenterX":240,"rotationCenterY":180}],"sounds":[{"assetId":"83a9787d4cb6f3b7632b4ddfebf74367","name":"pop","dataFormat":"wav","format":"","rate":48000,"sampleCount":1123,"md5ext":"83a9787d4cb6f3b7632b4ddfebf74367.wav"}],"volume":100,"layerOrder":0,"tempo":60,"videoTransparency":50,"videoState":"on","textToSpeechLanguage":null},{"isStage":false,"name":"Sprite1","variables":{},"lists":{},"broadcasts":{},"blocks":{"HZ@0TTJLd^k:e-/OiHka":{"opcode":"event_whenflagclicked","next":"[BGc-ZVK`1-vBkLrq+e[","parent":null,"inputs":{},"fields":{},"shadow":false,"topLevel":true,"x":42,"y":123},"-3s32CR]~EV05P6`54Ol":{"opcode":"sensing_answer","next":null,"parent":"IKuK{3JO9hpmZ,HapXl%","inputs":{},"fields":{},"shadow":false,"topLevel":false},"[BGc-ZVK`1-vBkLrq+e[":{"opcode":"sensing_askandwait","next":"IKuK{3JO9hpmZ,HapXl%","parent":"HZ@0TTJLd^k:e-/OiHka","inputs":{"QUESTION":[1,[10,"Say something"]]},"fields":{},"shadow":false,"topLevel":false},"IKuK{3JO9hpmZ,HapXl%":{"opcode":"looks_say","next":null,"parent":"[BGc-ZVK`1-vBkLrq+e[","inputs":{"MESSAGE":[3,"-3s32CR]~EV05P6`54Ol",[10,"Hello!"]]},"fields":{},"shadow":false,"topLevel":false}},"comments":{},"currentCostume":0,"costumes":[{"assetId":"bcf454acf82e4504149f7ffe07081dbc","name":"costume1","bitmapResolution":1,"md5ext":"bcf454acf82e4504149f7ffe07081dbc.svg","dataFormat":"svg","rotationCenterX":48,"rotationCenterY":50},{"assetId":"0fb9be3e8397c983338cb71dc84d0b25","name":"costume2","bitmapResolution":1,"md5ext":"0fb9be3e8397c983338cb71dc84d0b25.svg","dataFormat":"svg","rotationCenterX":46,"rotationCenterY":53}],"sounds":[{"assetId":"83c36d806dc92327b9e7049a565c6bff","name":"Meow","dataFormat":"wav","format":"","rate":48000,"sampleCount":40681,"md5ext":"83c36d806dc92327b9e7049a565c6bff.wav"}],"volume":100,"layerOrder":1,"visible":true,"x":0,"y":0,"size":100,"direction":90,"draggable":false,"rotationStyle":"all around"}],"monitors":[],"extensions":[],"meta":{"semver":"3.0.0","vm":"0.2.0-prerelease.20220102085704","agent":"Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/96.0.4664.110 Safari/537.36"}}'
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
            raise CompileError('Chức năng nộp bài bằng link đã tắt. Các bạn hãy tải file sb3 và nộp bài bằng cách tải file lên từ máy.')
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

    def create_files_from_url(self, project_id):
        project_url = 'https://projects.scratch.mit.edu/{project_id}'
        asset_url = 'https://cdn.assets.scratch.mit.edu/internalapi/asset/{asset_id}.{data_format}/get'

        r = requests.get(project_url.format(project_id=project_id))
        if r.status_code != 200:
            raise CompileError('Cannot fetch project! Maybe due to invalid ID or internet problems.')

        self.create_files_from_json(r.content)
        # NOTE: Don't download from MIT (strict rate limiting)
        # project_json = json.loads(r.content)

        # sb3_file.writestr('project.json', r.content)

        # self.dfs_json(project_json)

        # for file in set(self.item_filename.values()):
        #     time.sleep(0.1) # to pass MIT site rate limiter
        #     parts = file.split('.')
        #     r = requests.get(asset_url.format(
        #             asset_id = parts[0],
        #             data_format = parts[1]
        #         ))
        #     sb3_file.writestr(file, r.content)

        # sb3_file.close()