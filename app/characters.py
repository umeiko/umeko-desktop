"""Declarative, user-owned character artwork; no scripts or remote resources."""
import json
import copy
import hashlib
import re
import shutil
import uuid
import stat
import tempfile
import unicodedata
import zipfile
import zlib
from pathlib import Path

from PySide6.QtCore import QUrl, Slot, QSaveFile, QIODevice, QTimer
from PySide6.QtGui import QImageReader

SLOTS = frozenset('welcome avatarSmile avatarWink avatarHappy reply loading catch push pull background subagent0 subagent1 subagent2 subagent3 subagentCatch0 subagentCatch1 subagentCatch2 subagentCatch3'.split())
LINES = frozenset(('tap', 'celebration', 'greeting'))
DEFAULT = {'id': 'yanami', 'name': '八奈见杏菜', 'assets': {}, 'lines': {}}
BUILTINS = frozenset(('yanami', 'komari', 'kaju'))
CONFIG_DEFAULTS = json.loads((Path(__file__).parent/'character-defaults.json').read_text(encoding='utf-8'))


def cleanup_retired_character(folder, attempt=0):
    try:
        if folder.is_dir() and not folder.is_symlink(): shutil.rmtree(folder)
    except OSError:
        if attempt < 5: QTimer.singleShot(250,lambda:cleanup_retired_character(folder,attempt+1))


def cleanup_removed_character(folder, marker, attempt=0):
    if (folder/marker).is_file() and not (folder/'manifest.json').exists():
        try: shutil.rmtree(folder)
        except OSError:
            if attempt<5: QTimer.singleShot(250,lambda:cleanup_removed_character(folder,marker,attempt+1))


def write_character_manifest(file, value):
    output = QSaveFile(str(file))
    raw = json.dumps(value, ensure_ascii=False, indent=2).encode('utf-8')
    if not output.open(QIODevice.OpenModeFlag.WriteOnly) or output.write(raw)!=len(raw) or not output.commit():
        raise OSError('无法保存形象清单')


def merge_configuration(base, patch):
    result = copy.deepcopy(base)
    for key, value in patch.items():
        if isinstance(value, dict): result[key] = merge_configuration(result.get(key, {}), value)
        elif key == 'subagents':
            result[key] = [merge_configuration(row, value[i] if i < len(value) else {}) for i, row in enumerate(result[key])]
        else: result[key] = copy.deepcopy(value)
    return result


def normalize_configuration(value, template=CONFIG_DEFAULTS):
    def visit(patch, schema, path=''):
        if not isinstance(patch, dict) or patch.keys() - schema.keys(): raise ValueError('未知的角色配置项：'+path)
        result = {}
        for key, item in patch.items():
            expected, name = schema[key], path+key
            if key == 'version':
                if type(item) is not int or item != 1: raise ValueError('角色配置 version 必须为 1')
                result[key] = 1
            elif isinstance(expected, dict): result[key] = visit(item, expected, name+'.')
            elif key == 'subagents':
                if not isinstance(item, list) or not 1 <= len(item) <= 4: raise ValueError('subagents 需要 1–4 个角色配置对象')
                result[key] = [visit(row, expected[i], name+f'.{i}.') for i, row in enumerate(item)]
            elif isinstance(expected, list):
                if not isinstance(item, list) or not 1 <= len(item) <= 32 or any(not isinstance(text,str) or not text.strip() or len(text)>500 for text in item):
                    raise ValueError(name+' 需要 1–32 条短文本')
                result[key] = list(item)
            else:
                if not isinstance(item,str) or len(item)>500 or key == 'name' and (not item.strip() or len(item)>48): raise ValueError(name+' 需要短文本')
                result[key] = item
        return result
    return visit(value, template)


def read_character(file, check_images=False):
    file = Path(file).resolve()
    raw = file.read_bytes()
    if len(raw) > 65536: raise ValueError('形象清单不能超过 64 KiB')
    item = json.loads(raw.decode('utf-8-sig'))
    if not isinstance(item, dict) or item.get('format') != 'umeko-character' or type(item.get('version')) is not int or item['version'] != 1:
        raise ValueError('需要 format 为 umeko-character、version 为 1 的形象清单')
    if not isinstance(item.get('id'), str) or not re.fullmatch(r'[a-z0-9][a-z0-9-]{0,47}', item['id']):
        raise ValueError('形象 id 只能使用小写字母、数字和短横线，最多 48 位')
    if not isinstance(item.get('name'), str) or not item['name'].strip() or len(item['name']) > 48:
        raise ValueError('形象名称应为 1–48 个字符')
    assets, lines = item.get('assets', {}), item.get('lines', {})
    if not isinstance(assets, dict) or assets.keys() - SLOTS: raise ValueError('形象资源名称无效')
    if not isinstance(lines, dict) or lines.keys() - LINES: raise ValueError('形象台词名称无效')
    for key, value in lines.items():
        values = value if key == 'tap' else [value]
        if not isinstance(values, list) or not 1 <= len(values) <= 16 or any(not isinstance(text, str) or len(text) > 240 for text in values):
            raise ValueError('形象台词应为短文本；tap 为 1–16 条文本的数组')
    total = 0
    for name, value in assets.items():
        if not isinstance(value, str) or not value or '\\' in value or ':' in value or any(part in ('', '.', '..') for part in value.split('/')) or value.startswith('/'):
            raise ValueError('形象资源必须是包内的正常相对路径')
        path = file.parent / value
        if not path.resolve().is_relative_to(file.parent) or any(parent.is_symlink() for parent in [path, *path.parents] if parent.is_relative_to(file.parent) and parent != file.parent):
            raise ValueError('形象资源不能包含符号链接或指向包外')
        if path.suffix.lower() not in ('.png', '.jpg', '.jpeg', '.gif', '.webp'):
            raise ValueError('形象支持 PNG、JPEG、GIF 和 WebP')
        if check_images:
            size = path.stat().st_size
            total += size
            reader = QImageReader(str(path))
            dimensions = reader.size()
            if size > 12 * 1024 * 1024 or not reader.canRead() or dimensions.width() <= 0 or dimensions.height() <= 0 or dimensions.width() * dimensions.height() > 16777216:
                raise ValueError('形象图片无法读取或过大')
    if total > 96 * 1024 * 1024: raise ValueError('形象包不能超过 96 MiB')
    result = {'format': 'umeko-character', 'version': 1, 'id': item['id'], 'name': item['name'].strip(), 'assets': dict(assets), 'lines': dict(lines)}
    if 'dialogue' in item:
        relative = item['dialogue']
        if not isinstance(relative,str) or not re.fullmatch(r'[a-zA-Z0-9_-]+\.json',relative): raise ValueError('dialogue 需要包内 JSON 文件名')
        path = file.parent/relative
        if path.is_symlink() or len(path.read_bytes())>65536: raise ValueError('台词配置无效或过大')
        configuration = normalize_configuration(json.loads(path.read_text(encoding='utf-8-sig')))
        if any(row.get('avatar') or row.get('catch') for row in configuration.get('subagents',[])): raise ValueError('包内头像请放入 assets.subagent0 等资源项')
        result.update(dialogue=relative, _configuration=configuration)
    return result


def unpack_character_zip(source, destination):
    """Bounded data-only extraction; validate every entry before writing any file."""
    limit = 96 * 1024 * 1024 + 131072
    if source.stat().st_size > limit: raise ValueError('形象 ZIP 超过 96 MiB')
    with zipfile.ZipFile(source) as archive:
        entries = archive.infolist()
        if not 1 <= len(entries) <= 128: raise ValueError('形象 ZIP 最多包含 128 个条目')
        names, files, total = {}, [], 0
        for entry in entries:
            original = entry.orig_filename
            name = original[:-1] if entry.is_dir() else original
            parts = name.split('/')
            if (not name or '\\' in name or ':' in name or any(ord(c)<32 for c in name)
                    or any(part in ('', '.', '..') or part.endswith((' ', '.')) for part in parts)):
                raise ValueError('ZIP 包含无效路径')
            kind = stat.S_IFMT(entry.external_attr >> 16)
            if kind not in (0, stat.S_IFREG, stat.S_IFDIR) or (kind == stat.S_IFDIR) != entry.is_dir() and kind:
                raise ValueError('ZIP 不能包含符号链接或特殊文件')
            key = unicodedata.normalize('NFC', name).casefold()
            if key in names or any(key.startswith(old+'/') and not is_dir or old.startswith(key+'/') and not entry.is_dir() for old,is_dir in names.items()):
                raise ValueError('ZIP 包含重复或冲突路径')
            names[key] = entry.is_dir()
            if entry.is_dir(): continue
            if entry.compress_type not in (zipfile.ZIP_STORED, zipfile.ZIP_DEFLATED) or entry.flag_bits & 1:
                raise ValueError('ZIP 仅支持未加密的 Stored/Deflate 格式')
            suffix = Path(name).suffix.lower()
            if suffix not in ('.json','.png','.jpg','.jpeg','.gif','.webp'): raise ValueError('形象 ZIP 只能包含 JSON 和图片')
            maximum = 65536 if suffix == '.json' else 12*1024*1024
            total += entry.file_size
            if entry.file_size > maximum or total > limit: raise ValueError('ZIP 解压大小超过形象包限制')
            files.append((entry,name))
        manifests = [name for _,name in files if name.split('/')[-1]=='manifest.json']
        if len(manifests)!=1 or manifests[0].count('/')>1: raise ValueError('ZIP 需要一个根目录或一级目录中的 manifest.json')
        prefix = manifests[0][:-len('manifest.json')]
        if any(not name.startswith(prefix) for _,name in files): raise ValueError('ZIP 文件必须位于同一个形象目录')
        for entry,name in files:
            output = destination/name
            output.parent.mkdir(parents=True,exist_ok=True)
            with archive.open(entry) as stream, output.open('wb') as target:
                written=0
                while data := stream.read(65536):
                    written += len(data)
                    if written > entry.file_size: raise ValueError('ZIP 数据大小不符')
                    target.write(data)
                if written != entry.file_size: raise ValueError('ZIP 数据不完整')
        return destination/manifests[0]


class CharactersMixin:
    def _init_characters(self):
        self._character_options = {}
        try:
            file = self.store.directory/'character-config.json'
            if file.is_file() and file.stat().st_size <= 65536:
                self._character_options = normalize_configuration(json.loads(file.read_text(encoding='utf-8-sig')))
        except (ValueError,OSError): pass
        self._refresh_characters()

    def _refresh_characters(self):
        self._character_record = next((row for row in self._character_packs() if row['id'] == self.store.data.get('character','yanami')), DEFAULT)
        configuration = merge_configuration(CONFIG_DEFAULTS, self._character_record.get('_configuration',{}))
        legacy = self._character_record.get('lines',{})
        for key in ('welcome','reply'):
            if legacy.get('tap'): configuration['scenes'][key]['tap'] = legacy['tap']
            if legacy.get('celebration'): configuration['scenes'][key]['celebration'] = legacy['celebration']
        if legacy.get('greeting'): configuration['scenes']['welcome']['greetings'] = [legacy['greeting']]
        self._character_config = merge_configuration(configuration,self._character_options)
        self._character_animated_slots = set()
        for key,value in self._character_record['assets'].items():
            if Path(value).suffix.lower()=='.webp' and QImageReader(str(Path(self._character_record['directory'])/value)).imageCount()>1:
                self._character_animated_slots.add(key)
        self._character_animated_roles = []
        for row in self._character_config['subagents']:
            for key in ('avatar','catch'):
                value=row.get(key,'')
                if value and QUrl(value).path().lower().endswith('.webp') and QImageReader(QUrl(value).toLocalFile()).imageCount()>1:
                    self._character_animated_roles.append(value)

    def _characterNames(self):
        return [row['name'] for row in self._character_config['subagents']]

    def _character_packs(self):
        rows = [dict(DEFAULT, builtin=True)]
        files = [(self.root/f'app/icons/characters/{identifier}/manifest.json', True)
                 for identifier in ('komari', 'kaju') if (self.root/f'app/icons/characters/{identifier}/manifest.json').is_file()]
        files += [(path, False) for path in sorted((self.store.directory/'characters').glob('*/manifest.json'))
                  if re.fullmatch(r'[a-z0-9][a-z0-9-]{0,47}', path.parent.name) and not path.is_symlink() and not path.parent.is_symlink()]
        for file, builtin in files:
            try:
                item = read_character(file)
                if not builtin and (item['id'] in BUILTINS or item['id'] != file.parent.name): continue
                item.update(builtin=builtin, directory=str(file.parent.resolve()))
                rows.append(item)
            except (ValueError, OSError): pass
        return rows

    def _characterPacks(self):
        rows = []
        for item in self._character_packs():
            row = {key: item[key] for key in ('id', 'name', 'builtin')}
            asset = next((item['assets'][key] for key in ('avatarSmile','reply','welcome') if key in item['assets']), None)
            path = Path(item['directory'])/asset if asset else self.root/'app/icons/avatars/smile.webp'
            row['portrait'] = QUrl.fromLocalFile(str(path)).toString()
            rows.append(row)
        return rows

    def _characterStyle(self):
        item = self._character_record
        assets = {}
        for key, value in item['assets'].items():
            path = Path(item['directory'])/value
            if path.is_file(): assets[key] = QUrl.fromLocalFile(str(path)).toString() + '?v=' + str((Path(item['directory'])/'manifest.json').stat().st_mtime_ns)
        return dict(id=item['id'], name=item['name'], assets=assets, lines=item['lines'],
                    animatedSources=[assets[key] for key in self._character_animated_slots if key in assets]+self._character_animated_roles,
                    customGreetings=bool(item.get('_configuration',{}).get('scenes',{}).get('welcome',{}).get('greetings') or item['lines'].get('greeting') or self._character_options.get('scenes',{}).get('welcome',{}).get('greetings')),
                    dialogue=copy.deepcopy(self._character_config['scenes']), subagents=copy.deepcopy(self._character_config['subagents']))

    @Slot(str, result=bool)
    def configureCharacter(self, raw):
        try:
            options = normalize_configuration(json.loads(raw))
            for index, row in enumerate(options.get('subagents',[])):
                for key in ('avatar','catch'):
                    if not row.get(key): continue
                    source = Path(QUrl(row[key]).toLocalFile() or row[key]).expanduser()
                    if not source.is_absolute() or not source.is_file(): raise ValueError('角色头像需为现有本地文件的绝对路径')
                    reader = QImageReader(str(source))
                    size = reader.size()
                    if source.suffix.lower() not in ('.png','.jpg','.jpeg','.webp','.gif') or source.stat().st_size>12*1024*1024 or not reader.canRead() or size.width()<=0 or size.height()<=0 or size.width()*size.height()>16777216:
                        raise ValueError('角色头像无法读取或过大')
                    directory = self.store.directory/'character-assets'
                    directory.mkdir(exist_ok=True)
                    if directory.is_symlink(): raise ValueError('角色资源目录不能为符号链接')
                    target = directory/(hashlib.sha256(source.read_bytes()).hexdigest()+source.suffix.lower())
                    if not target.exists(): shutil.copyfile(source,target)
                    row[key] = QUrl.fromLocalFile(str(target)).toString()
            file = QSaveFile(str(self.store.directory/'character-config.json'))
            data = json.dumps(options,ensure_ascii=False,indent=2).encode('utf-8')
            if len(data)>65536: raise ValueError('角色配置不能超过 64 KiB')
            if not file.open(QIODevice.OpenModeFlag.WriteOnly) or file.write(data)!=len(data) or not file.commit(): raise OSError('无法保存角色配置')
            self._character_options = options
            self._refresh_characters()
            self.changed.emit()
            return True
        except (ValueError,OSError,RuntimeError) as error:
            self.toast.emit('角色配置失败：'+str(error))
            return False

    @Slot(str, result=bool)
    def selectCharacter(self, identifier):
        if not any(row['id'] == identifier for row in self._character_packs()): return False
        previous = self.store.data.get('character', 'yanami')
        try:
            self.store.data['character'] = identifier
            self.store.save()
        except (OSError, RuntimeError):
            self.store.data['character'] = previous
            return False
        self._refresh_characters()
        self.changed.emit()
        return True

    @Slot(str, result=bool)
    def importCharacter(self, url):
        staging = revision = dialogue = None
        extraction = None
        committed = False
        previous = self.store.data.get('character', 'yanami')
        try:
            file = Path(QUrl(url).toLocalFile() or url).expanduser().resolve()
            if file.suffix.lower() == '.zip':
                extraction = tempfile.TemporaryDirectory(prefix='umeko-character-')
                file = unpack_character_zip(file, Path(extraction.name))
            item = read_character(file, check_images=True)
            if item['id'] in BUILTINS: raise ValueError('不能覆盖内置形象的 id')
            library = self.store.directory/'characters'
            library.mkdir(exist_ok=True)
            if library.is_symlink(): raise ValueError('形象安装目录不能是符号链接')
            target = library/item['id']
            if target.is_symlink(): raise ValueError('形象安装目录不能是符号链接')
            if (target/'manifest.json').is_symlink(): raise ValueError('形象清单不能是符号链接')
            target.mkdir(exist_ok=True)
            staging = library/('.staging-'+uuid.uuid4().hex)
            staging.mkdir()
            for value in set(item['assets'].values()):
                output = staging/value
                output.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(file.parent/value, output)
            # AnimatedImage can hold GIFs open on Windows. Publish fresh assets
            # without renaming or overwriting the currently displayed files.
            token = uuid.uuid4().hex
            revision = target/('.assets-'+token)
            staging.rename(revision)
            published = {key:value for key,value in item.items() if not key.startswith('_')}
            published['assets'] = {key:revision.name+'/'+value for key,value in item['assets'].items()}
            if item.get('dialogue'):
                dialogue = target/('dialogue-'+token+'.json')
                shutil.copyfile(file.parent/item['dialogue'],dialogue)
                published['dialogue'] = dialogue.name
            try:
                self.store.data['character'] = item['id']
                self.store.save()
                write_character_manifest(target/'manifest.json',published)
                committed = True
            except Exception:
                self.store.data['character'] = previous
                self.store.save()
                raise
            self._refresh_characters()
            self.changed.emit()
            for folder in target.iterdir():
                if folder != revision and re.fullmatch(r'\.assets-[a-f0-9]{32}',folder.name):
                    QTimer.singleShot(250,lambda folder=folder:cleanup_retired_character(folder))
                elif folder != dialogue and re.fullmatch(r'dialogue-[a-f0-9]{32}\.json',folder.name):
                    try: folder.unlink(missing_ok=True)
                    except OSError: pass
            return True
        except (ValueError, OSError, RuntimeError, zipfile.BadZipFile, NotImplementedError, zlib.error, EOFError) as error:
            self.toast.emit('形象导入失败：'+str(error))
            return False
        finally:
            if extraction: extraction.cleanup()
            for folder in (staging, revision if not committed else None):
                if folder and folder.is_dir(): shutil.rmtree(folder, ignore_errors=True)
            if dialogue and not committed: dialogue.unlink(missing_ok=True)

    @Slot(str, result=bool)
    def removeCharacter(self, identifier):
        if identifier in BUILTINS or not re.fullmatch(r'[a-z0-9][a-z0-9-]{0,47}', identifier): return False
        folder = self.store.directory/'characters'/identifier
        if not folder.is_dir() or folder.is_symlink(): return False
        previous = self.store.data.get('character', 'yanami')
        try:
            if previous == identifier:
                self.store.data['character'] = 'yanami'
                self.store.save()
            marker = '.removed-'+uuid.uuid4().hex+'.json'
            (folder/'manifest.json').rename(folder/marker)
        except (OSError, RuntimeError):
            self.store.data['character'] = previous
            self.store.save()
            return False
        self._refresh_characters()
        self.changed.emit()
        QTimer.singleShot(250,lambda:cleanup_removed_character(folder,marker))
        return True


    @Slot(str, result=bool)
    def exportCharacterSkill(self, url):
        try:
            name = 'create-umeko-character.zip'
            source = next((folder/name for folder in (self.root/'provider-resources', self.root/'build/provider-resources') if (folder/name).is_file()), None)
            target = QUrl(url).toLocalFile()
            if source is None: raise ValueError('角色制作 Skill 不可用，请重新构建开发资源')
            if not target: raise ValueError('请选择本机保存位置')
            output = QSaveFile(target)
            data = source.read_bytes()
            if not output.open(QIODevice.OpenModeFlag.WriteOnly) or output.write(data)!=len(data) or not output.commit():
                raise OSError('无法导出角色制作 Skill')
            self.toast.emit('角色制作 Skill 已导出')
            return True
        except (ValueError,OSError) as error:
            self.toast.emit(str(error))
            return False
