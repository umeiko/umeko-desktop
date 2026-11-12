"""Export the SDK with editable session UI and application service examples."""
from pathlib import Path
import shutil,sys,tempfile,zipfile
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from app.builtin_widgets import WITHHELD_BUILTIN_WIDGETS
OUT=ROOT/'build/desktop-plugin-resources'
BUILTINS=ROOT/'build/builtin-widgets'

def build_resources(root, output, builtins):
    output.parent.mkdir(parents=True,exist_ok=True)
    builtins.parent.mkdir(parents=True,exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='desktop-plugin-sdk-',dir=output.parent) as tmp:
        staged=Path(tmp)/'widgets'
        staged.mkdir()
        for folder in sorted((root/'umeko-plugins').iterdir()):
            if folder.is_dir() and folder.name not in WITHHELD_BUILTIN_WIDGETS:
                shutil.copytree(folder,staged/folder.name,ignore=shutil.ignore_patterns('__pycache__','*.pyc'))
        archive=Path(tmp)/'umeko-plugin-sdk.zip'
        with zipfile.ZipFile(archive,'w',zipfile.ZIP_DEFLATED) as stream:
            for source,prefix in ((root/'plugin-runtime',''),(staged,'examples')):
                for p in sorted(source.rglob('*')):
                    # The native official pet is not a portable Python worker
                    # example; do not duplicate its 25 MiB of art into the SDK.
                    if prefix=='examples' and p.relative_to(source).parts[0] in ('desktop-pet','global-agents'):continue
                    if p.is_file() and '__pycache__' not in p.parts and p.suffix!='.pyc':stream.write(p,str(Path(prefix)/p.relative_to(source)))
        # Replace staging rather than merge it: an earlier build may contain a
        # Widget that is now withheld. The checked-in source stays untouched.
        if builtins.exists():shutil.rmtree(builtins)
        shutil.copytree(staged,builtins)
        output.mkdir(exist_ok=True)
        shutil.copy2(archive,output/archive.name)
        return output/archive.name

def main():
    print(build_resources(ROOT,OUT,BUILTINS))
if __name__=='__main__':main()
