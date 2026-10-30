"""Validate a data-only Umeko character folder and create its import ZIP."""
import argparse
import json
from pathlib import Path
import zipfile


def package(folder, output):
    folder=Path(folder).resolve()
    manifest=folder/'manifest.json'
    if manifest.is_symlink() or manifest.stat().st_size>65536: raise ValueError('Invalid manifest')
    data=json.loads(manifest.read_text(encoding='utf-8-sig'))
    import re
    if data.get('format')!='umeko-character' or type(data.get('version')) is not int or data['version']!=1: raise ValueError('Invalid format/version')
    identifier=data.get('id','')
    if not re.fullmatch('[a-z0-9][a-z0-9-]{0,47}',identifier) or identifier in ('yanami','komari','kaju'): raise ValueError('Invalid or reserved id')
    if not isinstance(data.get('name'),str) or not 1<=len(data['name'].strip())<=48: raise ValueError('Invalid name')
    slots=set('welcome avatarSmile avatarWink avatarHappy reply loading catch push pull background subagent0 subagent1 subagent2 subagent3 subagentCatch0 subagentCatch1 subagentCatch2 subagentCatch3'.split())
    assets=data.get('assets',{})
    if not isinstance(assets,dict) or set(assets)-slots: raise ValueError('Unknown asset slot')
    paths={'manifest.json',*assets.values()}
    if 'dialogue' in data:
        if not re.fullmatch(r'[a-zA-Z0-9_-]+\.json',data['dialogue']): raise ValueError('Invalid dialogue filename')
        paths.add(data['dialogue'])
    if len(paths)>128: raise ValueError('Too many entries')
    seen=set(); total=0
    for name in sorted(paths):
        if not isinstance(name,str) or '\\' in name or ':' in name or any(ord(c)<32 for c in name) or any(part in ('','.','..') or part.endswith((' ','.')) for part in name.split('/')): raise ValueError('Invalid path: '+str(name))
        from unicodedata import normalize
        key=normalize('NFC',name).casefold()
        if key in seen: raise ValueError('Conflicting filename: '+name)
        seen.add(key)
        path=folder/name
        if not path.resolve().is_relative_to(folder) or any(part.is_symlink() for part in [path,*path.parents] if part!=folder and part.is_relative_to(folder)): raise ValueError('Symlink or outside path: '+name)
        suffix=path.suffix.lower()
        if suffix not in ('.json','.png','.jpg','.jpeg','.gif','.webp'): raise ValueError('Unsupported file: '+name)
        size=path.stat().st_size
        if size>(65536 if suffix=='.json' else 12*1024*1024): raise ValueError('Oversize file: '+name)
        total+=size
    if total>96*1024*1024+131072: raise ValueError('Pack too large')
    target=Path(output).resolve()
    if target.is_relative_to(folder): raise ValueError('Write ZIP outside the source folder')
    with zipfile.ZipFile(target,'w',zipfile.ZIP_DEFLATED) as archive:
        for name in sorted(paths): archive.write(folder/name,name)
    return target


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('folder');parser.add_argument('output')
    args=parser.parse_args()
    print(package(args.folder,args.output))
