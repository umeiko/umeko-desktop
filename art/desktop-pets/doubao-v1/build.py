"""Pack generated full-body frames without redrawing or synthesizing pixels."""
import hashlib
import json
from pathlib import Path

from PIL import Image

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
OUT = ROOT / "umeko-plugins/desktop-pet/assets/doubao"
SIZE = (360, 360)
GRID = (4, 3)
DURATIONS = [450] + [120] * 10 + [450]


def frames_from_sheet(source):
    with Image.open(source) as original:
        if original.mode != "RGBA" or original.getchannel("A").getextrema()[0] != 0:
            raise ValueError("Expected generated transparent artwork: " + str(source))
        sheet = original.copy()
    cells, figures, anchors = [], [], []
    for index in range(GRID[0] * GRID[1]):
        column, row = index % GRID[0], index // GRID[0]
        cell = sheet.crop((round(column * sheet.width / GRID[0]),
                           round(row * sheet.height / GRID[1]),
                           round((column + 1) * sheet.width / GRID[0]),
                           round((row + 1) * sheet.height / GRID[1])))
        alpha = cell.getchannel("A").point(lambda a: 255 if a >= 32 else 0)
        box = alpha.getbbox()
        if not box or box[1] == 0 or box[3] >= cell.height:
            raise ValueError("Empty or vertically clipped cell: " + str((source, index, box)))
        lower_top = box[3] - max(4, round((box[3] - box[1]) * .055))
        feet = alpha.crop((0, lower_top, cell.width, box[3])).getbbox()
        if not feet:
            raise ValueError("Missing feet: " + str((source, index)))
        anchors.append((feet[0] + feet[2]) / 2)
        cells.append(box)
        figures.append(cell.crop(box))
    factor = min(SIZE[1] * .84 / max(p.height for p in figures),
                 SIZE[0] * .90 / max(p.width for p in figures))
    frames = []
    for figure, box, foot_x in zip(figures, cells, anchors):
        figure = figure.resize((round(figure.width * factor), round(figure.height * factor)),
                               Image.Resampling.LANCZOS)
        x = round(SIZE[0] / 2 + (box[0] - foot_x) * factor)
        y = round(SIZE[1] * .94) - figure.height
        if x < 0 or x + figure.width > SIZE[0]:
            raise ValueError("Pose exceeds the target canvas: " + str(source))
        frame = Image.new("RGBA", SIZE)
        frame.alpha_composite(figure, (x, y))
        frames.append(frame)
    return frames, cells


def main():
    specification = json.loads((HERE / "generation.json").read_text(encoding="utf-8"))
    OUT.mkdir(parents=True, exist_ok=True)
    images, packing = {}, []
    for asset in specification["assets"]:
        source = HERE / asset["file"]
        frames, boxes = frames_from_sheet(source)
        filename = asset["id"] + ".webp"
        target = OUT / filename
        frames[0].save(target, save_all=True, append_images=frames[1:],
                       duration=DURATIONS, loop=0, quality=92, method=6, exact=True)
        with Image.open(target) as result:
            count = result.n_frames
            if count != len(frames) or result.size != SIZE:
                raise ValueError("Encoder lost animation frames: " + filename)
            for index in range(count):
                result.seek(index)
                frame = result.convert("RGBA")
                if frame.getpixel((0, 0))[3] != 0:
                    raise ValueError("Lost alpha transparency: " + filename)
        content = frames[0].getchannel("A").point(lambda a: 255 if a >= 32 else 0).getbbox()
        images[filename] = {"animated": True, "width": SIZE[0], "height": SIZE[1],
                            "frames": count, "contentTop": content[1] / SIZE[1]}
        packing.append({"id": asset["id"], "sourceSha256": hashlib.sha256(source.read_bytes()).hexdigest(),
                        "cellBounds": boxes, "bytes": target.stat().st_size,
                        "sha256": hashlib.sha256(target.read_bytes()).hexdigest()})
    states = {name: name + ".webp" for name in ("idle", "thinking", "working", "waiting", "done", "error")}
    manifest = {
        "format": "umeko-pet", "version": 1, "id": "doubao", "name": "豆包",
        "states": states, "images": images,
        "dialogue": {
            "tap": ["我太懂你这种感觉了！", "你说，我听，咱们直接捋。", "清楚、实用、不绕弯。"],
            "hover": ["我就在这里，稳稳陪着你。", "稍等，我用大白话给你捋清楚。"],
            "drag": ["稳了，站稳了，咱们继续。"],
            "done": ["我直接说结论：完成啦。"],
            "error": ["对不起，这一步卡住了。我不躲，咱们找办法。"]
        },
        "rareIdle": {"image": "idle-rare.webp", "title": "稳稳接住你",
                      "line": "我就在这里，不躲、不藏、不绕、不逃，稳稳地接住你。"}
    }
    (OUT / "pet.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    public = {key: value for key, value in specification.items() if key != "assets"}
    public["assets"] = [{key: value for key, value in asset.items() if key != "generatedPath"}
                         for asset in specification["assets"]]
    public["encoding"] = {"canvas": list(SIZE), "grid": list(GRID), "frames": len(DURATIONS),
                          "durationsMs": DURATIONS, "loopMs": sum(DURATIONS), "loop": "infinite",
                          "quality": 92, "assets": packing}
    (OUT / "generation.json").write_text(json.dumps(public, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"output": str(OUT), "states": packing}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
