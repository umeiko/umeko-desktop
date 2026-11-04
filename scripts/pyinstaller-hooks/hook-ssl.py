"""Keep interpreter-specific SSL trust resources beside frozen ssl.py."""
from pathlib import Path

from PyInstaller.utils.hooks import get_module_file_attribute


ssl_directory = Path(get_module_file_attribute('ssl')).parent
rejected_ca = ssl_directory / 'codex-rejected-cas.pem'
datas = [(str(rejected_ca), '.')] if rejected_ca.is_file() else []
