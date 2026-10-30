"""Validate/import inert plugin ZIPs before any Python or QML is activated."""
import json, os, re, shutil, stat, tempfile, zipfile
import math
from pathlib import Path, PurePosixPath
from . import PluginError
MAX_BYTES=128*1024*1024
MAX_FILES=2048
PERMISSIONS={'workspace.read','workspace.write','session.read','session.write','process.execute','git.read','git.write','pi.read','pi.manage','pi.observe'}
BUILTIN_ICONS={row['id'] for row in json.loads(Path(__file__).with_name('icons.json').read_text(encoding='utf-8'))}

def relative(value):
    if not isinstance(value,str) or not value or '\0' in value or '\\' in value or ':' in value or value.startswith('/'):
        raise PluginError('插件路径必须是安全的相对路径')
    parts=value.rstrip('/').split('/')
    if any(x in ('','..') or x.endswith(('.', ' ')) or re.fullmatch(r'(CON|PRN|AUX|NUL|COM[1-9]|LPT[1-9])(?:\..*)?',x,re.I) for x in parts):
        raise PluginError('插件路径包含不支持的目录段')
    return '/'.join(x for x in parts if x!='.')

def validate_config(value, schema):
    if not isinstance(value,dict): raise PluginError('插件配置必须是 JSON 对象')
    def visit(v,s):
        types={'object':dict,'array':list,'string':str,'boolean':bool,'integer':int,'number':(int,float)}
        if s.get('type') not in types or not isinstance(v,types[s['type']]) or (s['type'] in ('integer','number') and isinstance(v,bool)): raise PluginError('插件配置类型无效')
        if 'enum' in s and v not in s['enum']: raise PluginError('插件配置选项无效')
        if isinstance(v,str) and len(v)>s.get('maxLength',65536):raise PluginError('字符串超过允许长度')
        if type(v) in (int,float) and (not math.isfinite(v) or v<s.get('minimum',-math.inf) or v>s.get('maximum',math.inf)):raise PluginError('数值超过允许范围')
        if isinstance(v,list) and len(v)>s.get('maxItems',10000):raise PluginError('列表超过允许长度')
        if isinstance(v,dict):
            if any(k not in v for k in s.get('required',[])):raise PluginError('插件缺少必需配置项')
            props=s.get('properties',{})
            if s.get('additionalProperties') is False and any(k not in props for k in v): raise PluginError('插件包含未知配置项')
            for k,x in v.items():
                if k in props:visit(x,props[k])
        if isinstance(v,list) and 'items' in s:
            for x in v:visit(x,s['items'])
    visit(value,schema)

def validate_schema(schema, depth=0):
    if depth>12 or not isinstance(schema,dict) or schema.get('type') not in ('object','array','string','boolean','integer','number'):
        raise PluginError('公开方法 parameters 必须使用支持的 JSON schema')
    if set(schema)-{'type','properties','required','additionalProperties','items','enum','description','maxLength','maxItems','minimum','maximum'}:
        raise PluginError('公开方法使用了不支持的 schema 约束')
    if 'properties' in schema:
        if not isinstance(schema['properties'],dict) or len(schema['properties'])>64:raise PluginError('公开方法属性清单无效')
        for child in schema['properties'].values():validate_schema(child,depth+1)
    if 'required' in schema and (not isinstance(schema['required'],list) or any(not isinstance(k,str) or k not in schema.get('properties',{}) for k in schema['required'])):raise PluginError('公开方法 required 无效')
    if 'additionalProperties' in schema and type(schema['additionalProperties']) is not bool:raise PluginError('additionalProperties 必须是布尔值')
    if 'items' in schema:validate_schema(schema['items'],depth+1)
    for key in ('maxLength','maxItems'):
        if key in schema and (type(schema[key]) is not int or not 0<=schema[key]<=65536):raise PluginError(key+' 无效')
    for key in ('minimum','maximum'):
        if key in schema and (type(schema[key]) not in (int,float) or not math.isfinite(schema[key])):raise PluginError(key+' 无效')

def validate(folder):
    root=Path(folder).resolve()
    def file(name):
        p=root/relative(name)
        if not p.resolve().is_relative_to(root) or p.is_symlink() or not p.is_file():raise PluginError('插件缺少文件或使用了符号链接：'+str(name))
        return p
    p=file('manifest.json')
    if p.stat().st_size>65536:raise PluginError('插件清单过大')
    m=json.loads(p.read_text(encoding='utf-8-sig'))
    if not isinstance(m,dict) or m.get('kind')!='umeko-plugin' or m.get('apiVersion')!=1:raise PluginError('不是兼容的 Umeko 插件包')
    if not isinstance(m.get('id'),str) or not re.fullmatch('[a-z][a-z0-9-]{0,63}',m['id']):raise PluginError('插件 ID 无效')
    if not isinstance(m.get('version'),str) or not re.fullmatch(r'\d+\.\d+\.\d+(?:-[A-Za-z0-9.-]+)?',m['version']):raise PluginError('插件版本无效')
    for key in ('name','description'):
        if not isinstance(m.get(key,''),str) or len(m.get(key,''))>8000:raise PluginError('插件文案无效')
    if not m.get('name','').strip():raise PluginError('插件名称不能为空')
    icon=m.get('icon','puzzle')
    if isinstance(icon,str):
        if icon not in BUILTIN_ICONS:raise PluginError('未知内置 Widget 图标：'+icon+'；可选名称见 SDK 的 icons.json')
    elif isinstance(icon,dict) and set(icon)=={'path'}:
        image=file(icon['path'])
        if image.suffix.lower() not in ('.svg','.png','.webp','.jpg','.jpeg') or image.stat().st_size>512*1024:raise PluginError('Widget 自定义图标须为 SVG/PNG/WebP/JPEG，最多 512 KiB')
    else:raise PluginError('icon 应为内置图标名称，或 {"path":"assets/icon.svg"}')
    m['icon']=icon
    lifecycle=m.get('lifecycle','session')
    if lifecycle not in ('session','application'):raise PluginError('lifecycle 必须为 session 或 application')
    m['lifecycle']=lifecycle
    if not isinstance(m.get('summary'),str) or not m['summary'].strip() or len(m['summary'])>20 or '\n' in m['summary'] or '\r' in m['summary']:
        raise PluginError('Widget 插件必须提供 20 字以内的单行 summary 简介')
    perms=m.get('permissions',[])
    if not isinstance(perms,list) or any(x not in PERMISSIONS for x in perms):raise PluginError('插件权限清单无效')
    entry,sep,factory=m.get('entrypoint','').partition(':')
    if not sep or not factory.isidentifier() or not entry.endswith('.py'):raise PluginError('插件 entrypoint 无效')
    file(entry)
    for key in ('builtin','enabled','sessionEnabled','hasPage','path','readmeText','configText'):m.pop(key,None)
    if m.get('page'):file(m['page'])
    if m.get('settingsPage'):file(m['settingsPage'])
    m['readme']=m.get('readme','README.md')
    with file(m['readme']).open(encoding='utf-8') as document:document.read(65536)
    agent=m.get('agent')
    if not isinstance(agent,dict) or not isinstance(agent.get('document'),str):raise PluginError('Widget 插件必须提供 agent.document 完整使用文档')
    document=file(agent['document'])
    if not document.name.lower().endswith('.md') or document.stat().st_size>65536 or not document.read_text(encoding='utf-8-sig').strip():raise PluginError('Agent 使用文档必须是非空 Markdown，最多 64 KiB')
    methods=agent.get('methods',{})
    if not isinstance(methods,dict) or len(methods)>64:raise PluginError('Widget 公开方法清单无效')
    for name,spec in methods.items():
        if not isinstance(name,str) or not re.fullmatch(r'[A-Za-z][A-Za-z0-9_.-]{0,63}',name) or not isinstance(spec,dict):raise PluginError('Widget 公开方法名称无效')
        if not isinstance(spec.get('description'),str) or not spec['description'].strip() or len(spec['description'])>500:raise PluginError('公开方法必须提供 description')
        validate_schema(spec.get('parameters'))
        if spec['parameters'].get('type')!='object':raise PluginError('公开方法参数必须为 JSON 对象')
    m['config']=m.get('config','config.json');m['configSchema']=m.get('configSchema','config.schema.json')
    if file(m['config']).stat().st_size>65536 or file(m['configSchema']).stat().st_size>65536:raise PluginError('插件配置或 schema 超过 64 KiB')
    defaults=json.loads(file(m['config']).read_text(encoding='utf-8-sig'))
    schema=json.loads(file(m['configSchema']).read_text(encoding='utf-8-sig'))
    validate_config(defaults,schema)
    for name,spec in m.get('executables',{}).items():
        if not isinstance(spec,dict) or not isinstance(name,str):raise PluginError('可执行文件清单无效')
        for target,path in spec.items():
            if target=='runtime':
                if set(spec)!={'runtime'} or path!='node':raise PluginError('Only the host node runtime is supported')
            elif target=='system':
                if not isinstance(path,str) or not re.fullmatch('[A-Za-z0-9_.-]+',path):raise PluginError('系统可执行文件名无效')
            else:file(path)
    return m,defaults,schema

def install(archive, destination, reserved=(), current_configs=None):
    destination=Path(destination);destination.mkdir(parents=True,exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='.staging-',dir=destination) as temporary:
        stage=Path(temporary)/'package';stage.mkdir()
        with zipfile.ZipFile(archive) as stream:
            entries=stream.infolist()
            if len(entries)>MAX_FILES or sum(i.file_size for i in entries)>MAX_BYTES:raise PluginError('插件包超过 128 MiB 或 2048 个文件的限制')
            normalized=[];seen={}
            for info in entries:
                name=relative(info.orig_filename)
                mode=stat.S_IFMT(info.external_attr>>16)
                if mode not in (0,stat.S_IFREG,stat.S_IFDIR):raise PluginError('插件不支持链接或特殊文件')
                key=name.casefold()
                if key in seen:raise PluginError('插件包存在重复或大小写冲突的路径')
                seen[key]=info.is_dir();normalized.append((info,name))
            roots=[name for info,name in normalized if not info.is_dir() and name.endswith('manifest.json') and PurePosixPath(name).name=='manifest.json']
            prefix='' if 'manifest.json' in roots else roots[0].split('/')[0]+'/' if len(roots)==1 and roots[0].count('/')==1 else None
            if prefix is None:raise PluginError('ZIP 根目录必须有一个 manifest.json')
            for info,name in normalized:
                if info.is_dir():continue
                if prefix and not name.startswith(prefix):raise PluginError('ZIP 包含插件目录外的文件')
                target=stage/relative(name[len(prefix):])
                target.parent.mkdir(parents=True,exist_ok=True)
                with stream.open(info) as source,target.open('xb') as output:
                    shutil.copyfileobj(source,output,65536)
                if os.name!='nt' and info.external_attr>>16 & 0o111:target.chmod(0o755)
        m,config,schema=validate(stage)
        if m['id'] in reserved:raise PluginError('不能覆盖内置官方插件')
        if current_configs and m['id'] in current_configs:
            config=current_configs[m['id']];validate_config(config,schema)
        target=destination/m['id']/m['version']
        target.parent.mkdir(parents=True,exist_ok=True)
        if target.exists():raise PluginError('该插件版本已安装；请先卸载或使用新版本号')
        stage.rename(target)
        return {'manifest':m,'config':config,'path':str(target)}
