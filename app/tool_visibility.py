"""Bounded desktop catalog, separate from the model's filtered registry."""
NATIVE_ID = 'builtin:pi-tools'
NATIVE_NAMES = {'read','bash','powershell','edit','write','grep','find','ls'}


def catalog(record, extensions):
    raw = record.resources.get('allTools', [])
    blocked = set(getattr(record, 'blocked_tools', []))
    rows = list(extensions)
    if raw:
        rows.insert(0, {'id':NATIVE_ID,'path':NATIVE_ID,'name':'Pi 内置工具','source':'builtin','scope':'session','enabled':True,
            'info':{'icon':'pi-commands','required':True,'bundled':True,'description':'Pi 原生的文件、搜索与命令工具。','updateKind':'desktop'}})
    modes = record.extension_modes
    groups = {}
    for tool in raw:
        name, source = tool.get('name',''), tool.get('source','')
        if not isinstance(name,str) or not name or len(name)>256: continue
        source = NATIVE_ID if name in NATIVE_NAMES and source == 'builtin:'+name else source
        groups.setdefault(source, []).append(tool)
    result=[]
    for row in rows:
        enabled = modes.get(row['path']) == 'session' if row['path'] in modes else row.get('enabled',False)
        tools=[]
        for tool in groups.get(row['path'],[]):
            name=tool['name']; hidden=tool.get('exposure')=='hidden'
            tools.append({'name':name,'description':str(tool.get('description',''))[:4096],
                'visible':enabled and name not in blocked and not hidden,'editable':enabled and not hidden})
        result.append({**row,'tools':tools,'toolCount':len(tools)})
    return result
