"""Resize generated subagent portraits; never redraw artwork."""
import json
from pathlib import Path
from PIL import Image

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]

def main():
    out = ROOT/'app/icons/characters/kazuhiko'
    out.mkdir(parents=True, exist_ok=True)
    for asset in json.loads((HERE/'generation.json').read_text())['assets']:
        image = Image.open(HERE/asset['file']).convert('RGBA')
        image.thumbnail((768, 768), Image.Resampling.LANCZOS)
        image.save(out/(asset['id']+'.png'), optimize=True)

if __name__ == '__main__':
    main()
