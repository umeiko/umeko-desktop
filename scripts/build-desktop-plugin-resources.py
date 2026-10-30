"""Export the SDK with editable session UI and application service examples."""
from pathlib import Path
import shutil,tempfile,zipfile
ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/'build/desktop-plugin-resources'
def main():
    OUT.parent.mkdir(parents=True,exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='desktop-plugin-sdk-',dir=OUT.parent) as tmp:
        output=Path(tmp)/'umeko-plugin-sdk.zip'
        with zipfile.ZipFile(output,'w',zipfile.ZIP_DEFLATED) as stream:
            for source,prefix in ((ROOT/'plugin-runtime',''),(ROOT/'umeko-plugins','examples')):
                for p in sorted(source.rglob('*')):
                    if p.is_file() and '__pycache__' not in p.parts and p.suffix!='.pyc':stream.write(p,str(Path(prefix)/p.relative_to(source)))
        OUT.mkdir(exist_ok=True);shutil.copy2(output,OUT/output.name)
    print(OUT/'umeko-plugin-sdk.zip')
if __name__=='__main__':main()
