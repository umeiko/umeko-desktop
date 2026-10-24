"""Create and mount-verify a drag-to-Applications disk image on macOS."""
import hashlib
import os
import subprocess
import sys
import tempfile
from pathlib import Path


def finder_layout(path, application):
    from ds_store import DSStore
    with DSStore.open(str(path), 'w+') as store:
        store['.']['bwsp'] = {'ShowStatusBar':False, 'ShowToolbar':False, 'ShowPathbar':False,
            'ShowSidebar':False, 'ShowTabView':False, 'ContainerShowSidebar':False,
            'WindowBounds':'{{200, 160}, {600, 360}}'}
        store['.']['icvp'] = {'viewOptionsVersion':1, 'backgroundType':1,
            'backgroundColorRed':1.0, 'backgroundColorGreen':1.0, 'backgroundColorBlue':1.0,
            'iconSize':96.0, 'textSize':13.0, 'gridSpacing':100.0, 'gridOffsetX':0.0,
            'gridOffsetY':0.0, 'arrangeBy':'none', 'labelOnBottom':True,
            'showItemInfo':False, 'showIconPreview':True}
        store['.']['vSrn'] = ('long', 1)
        store['.']['icvl'] = ('type', b'icnv')
        store[application]['Iloc'] = (160, 160)
        store['Applications']['Iloc'] = (440, 160)


def create_dmg(application, output, volume):
    if sys.platform != 'darwin': raise RuntimeError('DMG creation requires macOS')
    application, output = Path(application).resolve(), Path(output).resolve()
    if not application.is_dir() or application.suffix != '.app': raise ValueError('A verified .app bundle is required')
    output.parent.mkdir(parents=True, exist_ok=True)
    def run(*args): subprocess.run([str(arg) for arg in args], check=True)
    with tempfile.TemporaryDirectory(prefix='umeko-dmg-') as temporary:
        staging = Path(temporary)/'contents'; staging.mkdir()
        run('/usr/bin/ditto', application, staging/application.name)
        os.symlink('/Applications', staging/'Applications')
        finder_layout(staging/'.DS_Store', application.name)
        image = Path(temporary)/'install.dmg'
        run('/usr/bin/hdiutil', 'create', '-fs', 'HFS+', '-volname', volume, '-srcfolder', staging,
            '-format', 'UDZO', '-imagekey', 'zlib-level=9', image)
        run('/usr/bin/hdiutil', 'verify', image)
        mount = Path(temporary)/'verify'; mount.mkdir()
        attached = False
        try:
            run('/usr/bin/hdiutil', 'attach', '-readonly', '-nobrowse', '-noautoopen', '-mountpoint', mount, image)
            attached = True
            if not (mount/application.name/'Contents/Info.plist').is_file(): raise RuntimeError('DMG application is missing')
            if not (mount/'Applications').is_symlink() or os.readlink(mount/'Applications') != '/Applications':
                raise RuntimeError('DMG Applications shortcut is invalid')
            if not (mount/'.DS_Store').is_file(): raise RuntimeError('DMG Finder layout is missing')
            run('/usr/bin/codesign', '--verify', '--deep', '--strict', mount/application.name)
        finally:
            if attached or os.path.ismount(mount): run('/usr/bin/hdiutil', 'detach', mount)
        # Move only a fully verified image to the release assets directory.
        import shutil
        shutil.copy2(image, output)
    with output.open('rb') as source: digest = hashlib.file_digest(source, 'sha256').hexdigest()
    output.with_name(output.name+'.sha256').write_text(digest+'  '+output.name+'\n', encoding='ascii')
    return {'name':output.name, 'bytes':output.stat().st_size, 'sha256':digest}
