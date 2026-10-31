"""Resize/pad generated transparent art and package the built-in character."""
import json
import shutil
from pathlib import Path

from PIL import Image

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
OUT = ROOT / "app/icons/characters/whale-girl"


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    provenance = json.loads((HERE / "generation.json").read_text())
    slots = {}
    for asset in provenance["assets"]:
        with Image.open(HERE / asset["file"]) as source:
            figure = source.convert("RGBA")
        figure.thumbnail((704, 704), Image.Resampling.LANCZOS)
        # Deterministic layout padding only; preserves the generated pixels.
        image = Image.new("RGBA", (768, 768))
        image.alpha_composite(figure, ((768 - figure.width) // 2,
                                       (768 - figure.height) // 2))
        file = asset["id"] + ".png"
        image.save(OUT / file, optimize=True)
        slots[asset["id"]] = file
    slots["background"] = slots["welcome"]
    shutil.copy2(HERE / "dialogue.json", OUT / "dialogue.json")
    manifest = {"format": "umeko-character", "version": 1,
                "id": "whale-girl", "name": "鲸鱼娘", "assets": slots,
                "dialogue": "dialogue.json"}
    (OUT / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n")
    provenance["sourceArtwork"] = "art/characters/whale-girl-v1"
    provenance["communityReferenceLicenseText"] = (
        HERE / "reference/LICENSE.txt").read_text()
    (OUT / "provenance.json").write_text(
        json.dumps(provenance, ensure_ascii=False, indent=2) + "\n")
    print("Packaged", len(provenance["assets"]), "artworks,", len(slots), "slots")


if __name__ == "__main__":
    main()
