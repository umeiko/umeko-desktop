"""Slice generated keyframes and encode full-body rare-idle WebP animations.

Only deterministic cropping, registration, resizing and encoding; no drawing.
Each pet uses its own existing idle artwork as the scale/baseline reference.
"""
import hashlib
import json
import sys
from pathlib import Path
from statistics import median

from PIL import Image

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
DURATIONS = [600, 500, 1400, 120, 880, 700]


def bounds(image):
    # Threshold is used for bounds only. Source RGBA pixels remain unmodified.
    box = image.getchannel("A").point(lambda a: 255 if a >= 16 else 0).getbbox()
    if not box:
        raise ValueError("Empty animation frame")
    return box


def cells(sheet):
    if sheet.width % 3 or sheet.height % 2:
        raise ValueError("Expected a regular 3x2 sheet")
    width = sheet.width // 3
    splits = []
    for column in range(3):
        alpha = sheet.getchannel("A").crop(
            (column * width, 0, (column + 1) * width, sheet.height))
        candidates, start = [], None
        for y in range(round(sheet.height * .40), round(sheet.height * .60)):
            occupied = sum(a >= 64 for a in
                           alpha.crop((0, y, width, y + 1)).getdata())
            if occupied <= 2:
                if start is None:
                    start = y
            elif start is not None:
                if y - start >= 3:
                    candidates.append((start, y))
                start = None
        if start is not None:
            candidates.append((start, round(sheet.height * .60)))
        if not candidates:
            raise ValueError("No transparent gutter between animation rows")
        gap = max(candidates, key=lambda pair: pair[1] - pair[0])
        splits.append(sum(gap) // 2)
    for index in range(6):
        column = index % 3
        top, bottom = ((0, splits[column]) if index < 3 else
                       (splits[column], sheet.height))
        yield sheet.crop((column * width, top,
                          (column + 1) * width, bottom))


def main(identifiers=()):
    provenance = json.loads((HERE / "generation.json").read_text())
    for asset in provenance["assets"]:
        identifier = asset["id"]
        if identifiers and identifier not in identifiers:
            continue
        folder = ROOT / f"umeko-plugins/desktop-pet/assets/{identifier}"
        with Image.open(HERE / asset["reference"]) as source:
            reference = source.convert("RGBA")
        canvas = reference.size
        ref_box = bounds(reference)
        with Image.open(HERE / asset["file"]) as source:
            source_frames = list(cells(source.convert("RGBA")))
        boxes = [bounds(frame) for frame in source_frames]
        figures = [frame.crop(box) for frame, box in zip(source_frames, boxes)]
        ref_height = ref_box[3] - ref_box[1]
        # One scale for all six frames prevents height/size pulsing.
        scale = min(ref_height / median(f.height for f in figures),
                    canvas[1] * .94 / max(f.height for f in figures),
                    canvas[0] * .94 / max(f.width for f in figures))
        center, baseline = sum(ref_box[::2]) / 2, ref_box[3]
        frames = []
        for figure in figures:
            figure = figure.resize(
                (round(figure.width * scale), round(figure.height * scale)),
                Image.Resampling.LANCZOS)
            frame = Image.new("RGBA", canvas)
            x = max(0, min(canvas[0] - figure.width,
                           round(center - figure.width / 2)))
            y = baseline - figure.height
            if y < 0:
                raise ValueError("Frame would clip the head")
            frame.alpha_composite(figure, (x, y))
            frames.append(frame)
        target = folder / "idle-rare.webp"
        frames[0].save(target, save_all=True, append_images=frames[1:],
                       duration=DURATIONS, loop=0, quality=92, method=6,
                       exact=True, minimize_size=True)
        with Image.open(target) as encoded:
            if encoded.n_frames != 6 or encoded.size != canvas:
                raise ValueError("Animation encoder lost frames or canvas")
            for index in range(encoded.n_frames):
                encoded.seek(index)
                rgba = encoded.convert("RGBA")
                if rgba.getpixel((0, 0))[3] != 0:
                    raise ValueError("Lost transparency")
                if bounds(rgba)[3] != baseline:
                    raise ValueError("Unstable foot baseline")
        path = folder / "pet.json"
        value = json.loads(path.read_text())
        value["rareIdle"] = {"image": target.name, "line": asset["line"],
                             "title": asset["title"]}
        value.setdefault("images", {}).pop("idle-rare.png", None)
        value["images"][target.name] = {
            "animated": True, "width": canvas[0], "height": canvas[1],
            "frames": 6, "contentTop": min(b[1] for b in map(bounds, frames)) / canvas[1],
        }
        path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n")
        (folder / "idle-rare.png").unlink(missing_ok=True)
        public = dict(asset, sourceAsset="art/desktop-pets/rare-idle-v1/" + asset["file"],
                      tool="built-in image_gen", canvas=list(canvas),
                      durationsMs=DURATIONS, baseline=baseline, cellBounds=boxes,
                      sha256=hashlib.sha256(target.read_bytes()).hexdigest(),
                      bytes=target.stat().st_size)
        (folder / "rare-idle.provenance.json").write_text(
            json.dumps(public, ensure_ascii=False, indent=2) + "\n")
        print(identifier, canvas, "6 frames", target.stat().st_size, "bytes")


if __name__ == "__main__":
    main(sys.argv[1:])
