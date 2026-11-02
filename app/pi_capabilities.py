"""Per-chat Pi tool loadouts; no writes to global Pi configuration."""
from __future__ import annotations
import copy

NATIVE_ID = 'builtin:pi-tools'

def from_legacy(value, blocked=()):
    return value or ({'preset':'custom','custom':{'base':'full','tools':{name:False for name in blocked},'plugins':{}}} if blocked else {})

CORE = ('read','bash','powershell','edit','write','grep','find','ls')
MINIMAL = ('read','bash','edit','write')
PRESETS = ('full','standard','minimal','custom')

def normalize(value):
    value=value if isinstance(value,dict) else {}
    custom=value.get('custom',{});custom=custom if isinstance(custom,dict) else {}
    def clean(key,limit):
        rows=custom.get(key,{})
        return {k:v for k,v in list(rows.items())[:2000] if isinstance(k,str) and 0<len(k)<=limit and type(v) is bool} if isinstance(rows,dict) else {}
    return {'preset':value.get('preset') if value.get('preset') in PRESETS else 'full',
            'custom':{'base':custom.get('base') if custom.get('base') in PRESETS[:3] else 'full','tools':clean('tools',256),'plugins':clean('plugins',4096)}}

def effective(value):
    value=normalize(value)
    return value['custom'] if value['preset']=='custom' else {'base':value['preset'],'tools':{},'plugins':{}}

def plugin_enabled(value,source,default=True):
    profile=effective(value)
    return profile['plugins'].get(source, source=='native' or (profile['base']=='full' and default))

def tool_enabled(value,tool,default=True):
    profile=effective(value);owner=tool.get('owner') or tool.get('source','native')
    return plugin_enabled(value,owner,default) and profile['tools'].get(tool['name'], owner!='native' or profile['base']!='minimal' or tool['name'] in MINIMAL)

def catalog(resources):
    tools={name:{'name':name,'description':'','owner':'native','source':'builtin:'+name} for name in CORE}
    for row in resources.get('toolCatalog',resources.get('allTools',[])):
        if not isinstance(row,dict) or not isinstance(row.get('name'),str):continue
        row=copy.deepcopy(row)
        row['owner']=row.get('owner') or ('native' if row['name'] in CORE and row.get('source') in ('builtin:'+row['name'],'builtin','Pi') else 'builtin:mcp' if row['name'].startswith('mcp__') else row.get('source','Pi'))
        tools[row['name']]=row
    return list(tools.values())

def merge_resources(previous,current,profile):
    known={t['name']:t for t in previous.get('toolCatalog',[]) if not plugin_enabled(profile,t.get('owner',t.get('source','Pi')))}
    known.update({t['name']:t for t in current.get('toolCatalog',[])})
    return {**current,'toolCatalog':list(known.values())} if 'toolCatalog' in current else current

def change(value,action,args,extensions,resources):
    result=normalize(value)
    if action=='pi.preset':
        if args.get('preset') not in PRESETS:raise ValueError('Invalid Pi preset')
        result['preset']=args['preset'];return result
    if type(args.get('enabled')) is not bool:raise ValueError('enabled must be boolean')
    if result['preset']!='custom':result['custom']={'base':result['preset'],'tools':{},'plugins':{}}
    result['preset']='custom'
    if action=='pi.tool':
        name=args.get('name')
        if not isinstance(name,str) or not 0<len(name)<=256 or any(c in name for c in '*?[]!+\x00') or not any(t['name']==name for t in catalog(resources)):raise ValueError('Refresh the current tool catalog first')
        result['custom']['tools'][name]=args['enabled']
    elif action=='pi.plugin':
        source='native' if args.get('id') in ('native',NATIVE_ID) else next((r['path'] for r in extensions if r['id']==args.get('id')),None)
        if not source:raise ValueError('Refresh the current extension catalog first')
        result['custom']['plugins'][source]=args['enabled']
    else:raise ValueError('Unknown Pi capability operation')
    return result
