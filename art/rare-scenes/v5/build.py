"""Package the selected waist-up portraits without redrawing or altering alpha."""
import json
from pathlib import Path

from PIL import Image

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]


def main():
    catalog = {}
    for asset in json.loads((HERE / "generation.json").read_text())["assets"]:
        identifier = asset["id"]
        with Image.open(HERE / asset["file"]) as original:
            image = original.convert("RGBA")
        image.thumbnail((768, 768), Image.Resampling.LANCZOS)
        metadata = {
            key: asset[key] for key in
            ("title", "line", "sourceUrl", "sourceStatus", "adaptedDialogue")
            if key in asset
        }
        folder = ROOT / "app/icons/characters/rare-scenes"
        folder.mkdir(parents=True, exist_ok=True)
        image.save(folder / f"{identifier}.png", optimize=True)
        catalog[identifier] = metadata
    (ROOT / "app/icons/characters/rare-scenes/catalog.json").write_text(
        json.dumps(catalog, ensure_ascii=False, indent=2) + "\n"
    )


if __name__ == "__main__":
    main()
