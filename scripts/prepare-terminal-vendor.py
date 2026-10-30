"""Vendor small, pure-Python terminal dependencies from hash-pinned wheels."""
from pathlib import Path
import hashlib, io, json, urllib.request, zipfile
ROOT=Path(__file__).resolve().parents[1]
PACKAGES=[
    ('pyte','0.8.2','https://files.pythonhosted.org/packages/59/d0/bb522283b90853afbf506cd5b71c650cf708829914efd0003d615cf426cd/pyte-0.8.2-py3-none-any.whl','85db42a35798a5aafa96ac4d8da78b090b2c933248819157fc0e6f78876a0135'),
    ('wcwidth','0.2.13','https://files.pythonhosted.org/packages/fd/84/fd2ba7aafacbad3c4201d395674fc6348826569da3c0937e75505ead3528/wcwidth-0.2.13-py2.py3-none-any.whl','3da69048e4540d84af32131829ff948f1e022c1c6bdb8d6102117aac784f6859'),
    ('ptyprocess','0.7.0','https://files.pythonhosted.org/packages/22/a6/858897256d0deac81a172289110f31629fc4cee19b6f01283303e18c8db3/ptyprocess-0.7.0-py2.py3-none-any.whl','4b41f3967fce3af57cc7e94b888626c18bf37a083e3651ca8feeb66d492fef35'),
]
GPL_URL='https://raw.githubusercontent.com/qt/qtbase/v6.8.0/LICENSES/GPL-3.0-only.txt'
GPL_SHA256='8ceb4b9ee5adedde47b31e975c1d90c73ad27b6b165a1dcd80c7c545eb65b903'

def main():
    destination=ROOT/'umeko-plugins/terminal/vendor';destination.mkdir(parents=True,exist_ok=True);sources=[]
    for name,version,url,digest in PACKAGES:
        with urllib.request.urlopen(url,timeout=30) as response:data=response.read()
        if hashlib.sha256(data).hexdigest()!=digest:raise RuntimeError('Wheel digest mismatch: '+name)
        licenses=[]
        with zipfile.ZipFile(io.BytesIO(data)) as wheel:
            for entry in wheel.namelist():
                if entry.startswith(name+'/') and entry.endswith('.py'):
                    target=destination/entry;target.parent.mkdir(parents=True,exist_ok=True);target.write_bytes(wheel.read(entry))
                elif '.dist-info/' in entry and ('LICENSE' in entry.upper() or 'COPYING' in entry.upper()):
                    target=destination/'licenses'/(name+'-'+Path(entry).name);target.parent.mkdir(parents=True,exist_ok=True);target.write_bytes(wheel.read(entry));licenses.append(target.relative_to(destination).as_posix())
        sources.append({'name':name,'version':version,'source':url,'sha256':digest,'licenses':licenses})
    # LGPLv3 incorporates GPLv3; include both complete texts with the sources.
    with urllib.request.urlopen(GPL_URL,timeout=30) as response:data=response.read()
    if hashlib.sha256(data).hexdigest()!=GPL_SHA256:raise RuntimeError('GPL license digest mismatch')
    (destination/'licenses/GPL-3.0.txt').write_bytes(data)
    sources.append({'name':'GPL-3.0 license text','source':GPL_URL,'sha256':GPL_SHA256,'licenses':['licenses/GPL-3.0.txt']})
    (destination/'sources.json').write_text(json.dumps(sources,indent=2)+'\n',encoding='utf-8')
    print('Vendored terminal dependencies:',', '.join(row['name'] for row in sources))

if __name__=='__main__':main()
