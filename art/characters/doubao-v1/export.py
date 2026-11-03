"""Export data-only preview packs for the character and its independent pet."""
import argparse
import importlib.util
import json
from pathlib import Path
import shutil
import tempfile
import zipfile

ROOT = Path(__file__).resolve().parents[3]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=True)
    specification = importlib.util.spec_from_file_location(
        "character_pack", ROOT / "character_dev/skills/create-umeko-character/scripts/package.py")
    sdk = importlib.util.module_from_spec(specification)
    specification.loader.exec_module(sdk)
    with tempfile.TemporaryDirectory(prefix="doubao-packs-", dir=ROOT / "build") as folder:
        stage = Path(folder).resolve()
        assert stage.is_relative_to((ROOT / "build").resolve())
        character = stage / "character"
        character.mkdir()
        source = ROOT / "app/icons/characters/doubao"
        manifest = json.loads((source / "manifest.json").read_text(encoding="utf-8"))
        manifest["id"] = "doubao-preview"
        manifest["name"] = "豆包（预览）"
        for filename in {*manifest["assets"].values(), manifest["dialogue"]}:
            shutil.copyfile(source / filename, character / filename)
        (character / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
        character_zip = sdk.package(character, output / "豆包-人设包.zip")

        source = ROOT / "umeko-plugins/desktop-pet/assets/doubao"
        manifest = json.loads((source / "pet.json").read_text(encoding="utf-8"))
        manifest["id"] = "doubao-preview"
        manifest["name"] = "豆包（预览）"
        pet_zip = output / "豆包-桌宠包.zip"
        filenames = {*manifest["states"].values(), manifest["rareIdle"]["image"]}
        with zipfile.ZipFile(pet_zip, "w", zipfile.ZIP_DEFLATED) as archive:
            archive.writestr("pet.json", json.dumps(manifest, ensure_ascii=False, indent=2))
            for filename in sorted(filenames):
                archive.write(source / filename, filename)
        for target in (character_zip, pet_zip):
            with zipfile.ZipFile(target) as archive:
                assert archive.testzip() is None
                assert all(Path(name).suffix in {".json", ".png", ".webp"} for name in archive.namelist())
            print(target)


if __name__ == "__main__":
    main()
