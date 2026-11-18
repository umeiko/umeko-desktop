"""Size and encode staged release artwork for its UI roles; retain source assets."""
from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor
import hashlib
import json
import math
import os
from pathlib import Path
import tempfile

POLICY = {'schema': 2, 'staticQuality': 92, 'animationQuality': 90,
          'petEdge': 320, 'portraitEdge': 512, 'maxColorRms': 4.5}
RECEIPT = 'payload-assets.json'
ROLE_EDGES = {'welcome': 768, 'background': 768, 'loading': 384,
              'catch': 384, 'push': 384, 'pull': 384}


def resized(image, edge):
    from PIL import Image
    rgba = image.convert('RGBA')
    rgba.thumbnail((edge, edge), Image.Resampling.LANCZOS)
    return rgba


def plays(image):
    loop = image.info.get('loop')
    if image.format == 'GIF':
        return 0 if loop == 0 else loop + 1 if loop is not None else 1
    return 1 if loop is None else loop


def color_error(reference, encoded):
    """Check exact resized alpha and RMS on both light and dark backgrounds."""
    from PIL import Image, ImageChops, ImageStat
    encoded = encoded.convert('RGBA')
    if reference.size != encoded.size:
        raise RuntimeError('Encoded image dimensions changed')
    if ImageChops.difference(reference.getchannel('A'), encoded.getchannel('A')).getbbox():
        raise RuntimeError('Encoded alpha changed')
    visible = max(1, sum(reference.getchannel('A').histogram()[1:]))
    errors = []
    for color in ('white', 'black'):
        base = Image.new('RGBA', reference.size, color)
        before = Image.alpha_composite(base, reference).convert('RGB')
        after = Image.alpha_composite(base, encoded).convert('RGB')
        errors.append(math.sqrt(sum(ImageStat.Stat(ImageChops.difference(before, after)).sum2) / (visible * 3)))
    return max(errors)


def metadata(image):
    return {key: image.info[key] for key in ('icc_profile', 'exif') if key in image.info}


def encode_static(source, edge, webp=False, force=False):
    from PIL import Image
    target = source.with_suffix('.webp') if webp else source
    before = source.stat().st_size
    if target != source and target.exists():
        before += target.stat().st_size
    with Image.open(source) as original:
        if getattr(original, 'n_frames', 1) != 1:
            raise RuntimeError('Animated icon needs a declared animation role: ' + str(source))
        original_size = original.size
        reference = resized(original, edge)
        options = metadata(original)
    quality, error = 'lossless', 0.0
    with tempfile.TemporaryDirectory(prefix='encode-', dir=source.parent) as temporary:
        candidate = Path(temporary) / target.name
        if target.suffix.lower() == '.webp':
            # Small avatars and glyph-sized art keep exact colors after scaling.
            qualities = [POLICY['staticQuality'], 96, 'lossless'] if max(reference.size) > 256 else ['lossless']
            for quality in qualities:
                reference.save(candidate, 'WEBP', lossless=quality == 'lossless',
                               quality=75 if quality == 'lossless' else quality,
                               method=4, alpha_quality=100, exact=True, **options)
                with Image.open(candidate) as encoded:
                    error = color_error(reference, encoded)
                if error <= POLICY['maxColorRms']:
                    break
        else:
            # Preserve hard-coded legacy PNG URLs, with a smaller pixel canvas.
            reference.save(candidate, 'PNG', optimize=True, compress_level=9, **options)
            with Image.open(candidate) as encoded:
                if encoded.convert('RGBA').tobytes() != reference.tobytes():
                    raise RuntimeError('PNG pixels changed after resizing: ' + str(source))
        if error > POLICY['maxColorRms']:
            raise RuntimeError('Static encoding exceeds the color error budget')
        after = candidate.stat().st_size
        if after >= before and not force:
            return None
        candidate.replace(target)
    if target != source:
        source.unlink()
    return {'path': str(source), 'target': str(target), 'before': before, 'after': after,
            'originalSize': list(original_size), 'size': list(reference.size),
            'quality': quality, 'colorRms': error}


def animation_error(frames, durations, filename, expected_plays):
    """Compare every source time interval, including coalesced identical holds."""
    from PIL import Image, ImageSequence
    encoded_frames, encoded_durations = [], []
    with Image.open(filename) as image:
        if plays(image) != expected_plays:
            raise RuntimeError('Animation loop count changed')
        for frame in ImageSequence.Iterator(image):
            frame.load()
            encoded_frames.append(frame.convert('RGBA'))
            encoded_durations.append(frame.info.get('duration', 0))
    if sum(durations) != sum(encoded_durations) or any(d <= 0 for d in encoded_durations):
        raise RuntimeError('Animation duration changed')
    original_index = encoded_index = 0
    original_left, encoded_left = durations[0], encoded_durations[0]
    worst = 0.0
    while original_index < len(frames) and encoded_index < len(encoded_frames):
        worst = max(worst, color_error(frames[original_index], encoded_frames[encoded_index]))
        elapsed = min(original_left, encoded_left)
        original_left -= elapsed
        encoded_left -= elapsed
        if original_left == 0:
            original_index += 1
            if original_index < len(frames):
                original_left = durations[original_index]
        if encoded_left == 0:
            encoded_index += 1
            if encoded_index < len(encoded_frames):
                encoded_left = encoded_durations[encoded_index]
    if original_index != len(frames) or encoded_index != len(encoded_frames):
        raise RuntimeError('Animation timeline changed')
    return worst, len(encoded_frames)


def encode_animation(source, edge):
    from PIL import Image, ImageSequence
    target = source.with_suffix('.webp')
    if target != source and target.exists():
        raise RuntimeError('Animation target already exists: ' + str(target))
    before = source.stat().st_size
    with Image.open(source) as image:
        original_size, expected_plays, options = image.size, plays(image), metadata(image)
        frames, durations = [], []
        for frame in ImageSequence.Iterator(image):
            frame.load()
            frames.append(resized(frame, edge))
            durations.append(frame.info.get('duration', 0))
    if len(frames) < 2 or any(d <= 0 for d in durations):
        return None
    with tempfile.TemporaryDirectory(prefix='animation-', dir=source.parent) as temporary:
        candidate = Path(temporary) / target.name
        for quality in (POLICY['animationQuality'], 95, 'lossless'):
            frames[0].save(candidate, 'WEBP', save_all=True, append_images=frames[1:],
                           lossless=quality == 'lossless', quality=75 if quality == 'lossless' else quality,
                           method=3, alpha_quality=100, exact=True, duration=durations,
                           loop=expected_plays, kmin=9, kmax=17, **options)
            error, count = animation_error(frames, durations, candidate, expected_plays)
            if error <= POLICY['maxColorRms']:
                break
        if error > POLICY['maxColorRms']:
            raise RuntimeError('Animation encoding exceeds the color error budget')
        after = candidate.stat().st_size
        if after >= before:
            return None
        candidate.replace(target)
    if source != target:
        source.unlink()
    return {'path': str(source), 'target': str(target), 'before': before, 'after': after,
            'originalSize': list(original_size), 'size': list(frames[0].size),
            'quality': quality, 'colorRms': error, 'frames': count,
            'originalFrames': len(frames), 'durationMs': sum(durations), 'plays': expected_plays}


def optimize_pet(folder):
    manifest = folder / 'pet.json'
    spec = json.loads(manifest.read_text(encoding='utf-8'))
    names = set(spec['states'].values())
    if spec.get('rareIdle', {}).get('image'):
        names.add(spec['rareIdle']['image'])
    changes = []
    for name in sorted(names):
        if Path(name).name != name or Path(name).suffix.lower() not in ('.gif', '.webp'):
            continue
        row = encode_animation(folder / name, POLICY['petEdge'])
        if not row:
            continue
        target = Path(row['target']).name
        spec['states'] = {state: target if value == name else value for state, value in spec['states'].items()}
        if spec.get('rareIdle', {}).get('image') == name:
            spec['rareIdle']['image'] = target
        if name in spec.get('images', {}):
            info = spec['images'].pop(name)
            info.update(width=row['size'][0], height=row['size'][1],
                        frames=row['frames'], animated=row['frames'] > 1)
            spec['images'][target] = info
        changes.append(row)
    if changes:
        manifest.write_text(json.dumps(spec, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    return changes


def optimize_character(manifest):
    spec = json.loads(manifest.read_text(encoding='utf-8'))
    limits = {}
    for slot, name in spec.get('assets', {}).items():
        if Path(name).name != name or Path(name).suffix.lower() not in ('.png', '.webp'):
            continue
        limits[name] = max(limits.get(name, 0), ROLE_EDGES.get(slot, 256))
    changes = []
    for name, edge in sorted(limits.items()):
        # Direct robot tray/fallback URLs remain PNG.
        row = encode_static(manifest.parent / name, edge, webp=manifest.parent.name != 'system')
        if not row:
            continue
        target = Path(row['target']).name
        spec['assets'] = {slot: target if value == name else value for slot, value in spec['assets'].items()}
        changes.append(row)
    if changes:
        manifest.write_text(json.dumps(spec, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    return changes


def optimize_portraits(resources):
    qml = resources / 'app/qml/WelcomeMascot.qml'
    if not qml.is_file():
        return []
    text = qml.read_text(encoding='utf-8')
    png_line = 'fallbackSource: "../icons/portraits/" + (root.portraitIndex + 1).toString().padStart(2, "0") + ".png"'
    webp_line = png_line.replace('.png"', '.webp"')
    if png_line not in text and webp_line not in text:
        raise RuntimeError('Welcome portrait source changed; update payload projection')
    sources = []
    for index in range(1, 13):
        png = resources / 'app/icons/portraits' / f'{index:02}.png'
        source = png if png.is_file() else png.with_suffix('.webp')
        if not source.is_file():
            raise RuntimeError('Incomplete welcome portrait set')
        sources.append(source)
    changes = [row for source in sources
               if (row := encode_static(source, POLICY['portraitEdge'], webp=True, force=True))]
    qml.write_text(text.replace(png_line, webp_line), encoding='utf-8')
    return changes


def icon_edge(path):
    name = path.stem
    if 'fluent' in path.parts or 'providers' in path.parts:
        return 128
    if 'subagents' in path.parts:
        return 384 if name.endswith('-catch') else 256
    if 'avatars' in path.parts or name == 'yanami-pixel':
        return 256
    if 'rare-scenes' in path.parts or name == 'yanami-chat-watermark':
        return 768
    return 512


def prune_source_maps(resources):
    changes = []
    allowed = [resources.resolve()]
    # PyInstaller macOS puts data in Resources, exposed through Frameworks links.
    if resources.name == 'Frameworks' and resources.parent.name == 'Contents':
        allowed.append((resources.parent / 'Resources').resolve())
    for source in sorted((resources / 'runtime').rglob('*.map')):
        if source.is_symlink() or not any(source.resolve().is_relative_to(root) for root in allowed):
            continue
        try:
            data = json.loads(source.read_text(encoding='utf-8'))
        except (UnicodeError, ValueError):
            continue
        if not isinstance(data, dict) or data.get('version') != 3 or not ('mappings' in data or 'sections' in data):
            continue
        changes.append({'path': str(source), 'before': source.stat().st_size, 'after': 0})
        source.unlink()
    return changes


def optimize_payload(resources, workers=4):
    resources = resources.resolve()
    if os.name == 'nt':
        native = str(resources)
        prefix = "\\\\?\\"
        if not native.startswith(prefix):
            resources = Path(prefix + ('UNC\\' + native[2:] if native.startswith('\\\\') else native))
    if (resources / 'runtime/package-lock.json').exists() or (resources / '.git').exists():
        raise ValueError('Expected a staged distribution, not a source checkout')
    receipt = resources / RECEIPT
    if receipt.exists():
        recorded = json.loads(receipt.read_text(encoding='utf-8'))
        if recorded.get('policy') != POLICY:
            raise ValueError('Encoding policy changed; create a fresh staging tree')
        for name, digest in recorded['files'].items():
            file = resources / name
            if not file.is_file() or hashlib.sha256(file.read_bytes()).hexdigest() != digest:
                raise ValueError('Optimized assets changed; create a fresh staging tree')
        return {'schema': 2, 'policy': POLICY, 'categories': {}, 'savedBytes': 0, 'alreadyOptimized': True}
    manifests = sorted((resources / 'app/icons/characters').glob('*/manifest.json'))
    pets = sorted((resources / 'umeko-plugins/desktop-pet/assets').glob('*/pet.json'))
    with ThreadPoolExecutor(max_workers=workers) as pool:
        characters = [row for rows in pool.map(optimize_character, manifests) for row in rows]
        portraits = optimize_portraits(resources)
        handled = {Path(row[key]) for row in characters + portraits for key in ('path', 'target')}
        remaining = [file for file in (resources / 'app/icons').rglob('*')
                     if file.is_file() and file.suffix.lower() in ('.png', '.webp') and file not in handled]
        static = [row for row in pool.map(lambda file: encode_static(file, icon_edge(file)), remaining) if row]
        animations = [row for rows in pool.map(optimize_pet, [file.parent for file in pets]) for row in rows]
    maps = prune_source_maps(resources)
    obsolete = resources / 'app/icons/lossless-assets.json'
    removed_metadata = []
    if obsolete.is_file():
        removed_metadata.append({'path': str(obsolete), 'before': obsolete.stat().st_size, 'after': 0})
        obsolete.unlink()
    categories = {'characters': characters, 'portraits': portraits, 'otherArtwork': static,
                  'petAnimations': animations, 'sourceMaps': maps, 'obsoleteMetadata': removed_metadata}
    checked = {Path(row['target']) for rows in categories.values() for row in rows if 'target' in row}
    checked.update(manifests)
    checked.update(pets)
    welcome = resources / 'app/qml/WelcomeMascot.qml'
    if welcome.is_file():
        checked.add(welcome)
    hashes = {file.relative_to(resources).as_posix(): hashlib.sha256(file.read_bytes()).hexdigest()
              for file in sorted(checked)}
    receipt.write_text(json.dumps({'policy': POLICY, 'files': hashes}, indent=2) + '\n', encoding='utf-8')
    for rows in categories.values():
        for row in rows:
            for key in ('path', 'target'):
                if key in row:
                    row[key] = Path(row[key]).relative_to(resources).as_posix()
    return {'schema': 2, 'policy': POLICY, 'categories': categories,
            'savedBytes': sum(row['before'] - row['after'] for rows in categories.values() for row in rows)}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--resources', type=Path, required=True)
    parser.add_argument('--report', type=Path, required=True)
    args = parser.parse_args()
    report = optimize_payload(args.resources)
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(json.dumps(report, indent=2) + '\n', encoding='utf-8')
    print('Verified compact release resources:', report['savedBytes'], 'expanded bytes saved')


if __name__ == '__main__':
    main()
