"""Resize generated RGBA artwork; preserve the generated alpha channel."""
import hashlib
import json
import shutil
from pathlib import Path

from PIL import Image

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
OUT = ROOT / "app/icons/characters/doubao"


def main():
    specification = json.loads((HERE / "generation.json").read_text(encoding="utf-8"))
    OUT.mkdir(parents=True, exist_ok=True)
    manifest = json.loads((OUT / "manifest.json").read_text(encoding="utf-8"))
    used = set(manifest["assets"].values())
    if "picker" in specification:
        shutil.copyfile(HERE / specification["picker"]["file"], OUT / "picker.png")
    output = []
    for asset in specification["assets"]:
        if asset["id"] + ".png" not in used:
            continue
        source = HERE / asset["file"]
        with Image.open(source) as original:
            if original.mode != "RGBA" or original.getchannel("A").getextrema()[0] != 0:
                raise ValueError("Expected generated alpha transparency: " + asset["id"])
            image = original.copy()
        image.thumbnail((744, 744), Image.Resampling.LANCZOS)
        padded = Image.new("RGBA", (768, 768))
        padded.alpha_composite(image, ((768 - image.width) // 2, (768 - image.height) // 2))
        image = padded
        target = OUT / (asset["id"] + ".png")
        image.save(target, optimize=True)
        output.append({"id": asset["id"], "size": list(image.size),
                       "sourceSha256": hashlib.sha256(source.read_bytes()).hexdigest(),
                       "sha256": hashlib.sha256(target.read_bytes()).hexdigest(),
                       "bytes": target.stat().st_size})
    if "rareScene" in specification:
        source = HERE / specification["rareScene"]["file"]
        with Image.open(source) as original:
            if original.mode != "RGBA" or original.getchannel("A").getextrema()[0] != 0:
                raise ValueError("Expected generated alpha transparency: rare scene")
            image = original.copy()
        image.thumbnail((992, 992), Image.Resampling.LANCZOS)
        padded = Image.new("RGBA", (1024, 1024))
        padded.alpha_composite(image, ((1024 - image.width) // 2, (1024 - image.height) // 2))
        image = padded
        image.save(ROOT / "app/icons/characters/rare-scenes/doubao.png", optimize=True)
    print(json.dumps(output, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
