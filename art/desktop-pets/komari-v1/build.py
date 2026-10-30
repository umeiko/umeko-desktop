"""Pack the generated 3x2 animation sheets; no image API is needed to rebuild.

Development dependency: Pillow with animated WebP support. This script only
slices, registers, scales and encodes the supplied artwork; it draws no art.
"""
import hashlib
import json
from pathlib import Path

from PIL import Image

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
OUT = ROOT / 'umeko-plugins/desktop-pet/assets/komari'
SIZE = (384, 576)
DURATIONS = [1700, 1200, 100, 100, 100, 1000]


def main():
    provenance = json.loads((HERE / 'generation.json').read_text(encoding='utf-8'))
    OUT.mkdir(parents=True, exist_ok=True)
    images = {}
    packing = []
    for asset in provenance['assets']:
        source = HERE / asset['file']
        sheet = Image.open(source).convert('RGBA')
        if sheet.width % 3 or sheet.height % 2:
            raise ValueError('Expected exactly divisible 3x2 sheet: ' + asset['id'])
        width, height = sheet.width // 3, sheet.height // 2
        frames, boxes = [], []
        for index in range(6):
            x, y = index % 3 * width, index // 3 * height
            cell = sheet.crop((x, y, x + width, y + height))
            bounds = cell.getchannel('A').point(lambda a: 255 if a >= 16 else 0).getbbox()
            if not bounds:
                raise ValueError('Empty animation cell')
            boxes.append(bounds)
            figure = cell.crop(bounds)
            factor = min(SIZE[1] * .84 / figure.height, SIZE[0] * .9 / figure.width)
            figure = figure.resize((round(figure.width * factor), round(figure.height * factor)), Image.Resampling.LANCZOS)
            frame = Image.new('RGBA', SIZE)
            frame.alpha_composite(figure, ((SIZE[0] - figure.width) // 2, round(SIZE[1] * .94) - figure.height))
            frames.append(frame)
        name = asset['id'] + '.webp'
        target = OUT / name
        frames[0].save(target, save_all=True, append_images=frames[1:], duration=DURATIONS,
                       loop=0, quality=92, method=6, exact=True, minimize_size=True)
        with Image.open(target) as result:
            if result.n_frames != 6 or result.size != SIZE:
                raise ValueError('Encoder lost animation frames')
            for frame in range(result.n_frames):
                result.seek(frame)
                if result.convert('RGBA').getpixel((0, 0))[3] != 0:
                    raise ValueError('Animation lost its transparent background')
        images[name] = {'animated': True, 'width': SIZE[0], 'height': SIZE[1], 'frames': 6}
        packing.append({'id': asset['id'], 'sourceSha256': hashlib.sha256(source.read_bytes()).hexdigest(),
                        'cellBounds': boxes, 'bytes': target.stat().st_size,
                        'sha256': hashlib.sha256(target.read_bytes()).hexdigest()})
    manifest = {'format': 'umeko-pet', 'version': 1, 'id': 'komari', 'name': '小鞠知花',
                'states': {asset['id']: asset['id'] + '.webp' for asset in provenance['assets']},
                'images': images,
                'dialogue': {'tap': ['有、有在认真帮忙的。', '再检查一遍……就好了。', '你叫我？我在。'],
                             'hover': ['我会在这里等你。'], 'drag': ['这、这里也可以。']}}
    (OUT / 'pet.json').write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    public = {key: value for key, value in provenance.items() if key != 'assets'}
    public['sourceArtwork'] = 'art/desktop-pets/komari-v1/source/'
    public['assets'] = [{key: value for key, value in asset.items() if key != 'generatedPath'} for asset in provenance['assets']]
    public['encoding'] = {'canvas': list(SIZE), 'durationsMs': DURATIONS, 'loopMs': sum(DURATIONS),
                          'frames': 6, 'loop': 'infinite', 'quality': 92, 'assets': packing}
    (OUT / 'generation.json').write_text(json.dumps(public, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print(json.dumps({'output': str(OUT), 'bytes': sum(p['bytes'] for p in packing), 'states': packing}, ensure_ascii=False))


if __name__ == '__main__':
    main()
