"""python -m umeko_plugin_sdk validate|pack folder [output.zip]."""
import argparse, json, zipfile
from pathlib import Path
from .packages import validate, relative

def main():
    parser=argparse.ArgumentParser();parser.add_argument('operation',choices=['validate','pack']);parser.add_argument('folder',type=Path);parser.add_argument('output',nargs='?',type=Path);args=parser.parse_args()
    manifest,_,_=validate(args.folder)
    if args.operation=='pack':
        if not args.output:parser.error('pack requires output.zip')
        files=[]
        for p in sorted(args.folder.rglob('*')):
            if p.is_symlink():raise ValueError('Do not package symlinks')
            if p.is_file() and '__pycache__' not in p.parts and p.suffix!='.pyc':files.append((p,relative(p.relative_to(args.folder).as_posix())))
        with zipfile.ZipFile(args.output,'w',zipfile.ZIP_DEFLATED) as stream:
            for p,name in files:stream.write(p,name)
    print(json.dumps({'ok':True,'id':manifest['id'],'version':manifest['version']},ensure_ascii=False))
if __name__=='__main__':main()
