import importlib.util
import json
import random
from pathlib import Path
import sys
import tempfile
import unittest

from PIL import Image, ImageSequence

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('package_payload', ROOT/'scripts/package_payload.py')
payload = importlib.util.module_from_spec(spec)
spec.loader.exec_module(payload)


class PackagePayloadTest(unittest.TestCase):
    def test_character_projection_keeps_pixels_and_shared_slots(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            folder = root/'app/icons/characters/fixture'
            folder.mkdir(parents=True)
            image = Image.new('RGBA', (128, 128), (60, 120, 200, 192))
            source = folder/'welcome.png'
            image.save(source, compress_level=0)
            manifest = folder/'manifest.json'
            manifest.write_text(json.dumps({'assets': {'welcome': 'welcome.png', 'background': 'welcome.png'}, 'name': '保留人设'}))
            report = payload.optimize_payload(root)
            data = json.loads(manifest.read_text())
            self.assertEqual(data['assets'], {'welcome': 'welcome.webp', 'background': 'welcome.webp'})
            self.assertEqual(data['name'], '保留人设')
            self.assertFalse(source.exists())
            with Image.open(folder/'welcome.webp') as encoded:
                self.assertEqual(encoded.convert('RGBA').tobytes(), image.tobytes())
            self.assertGreater(report['savedBytes'], 0)
            self.assertEqual(payload.optimize_payload(root)['savedBytes'], 0)

    def test_pet_projection_preserves_loop_durations_and_dialogue(self):
        for loop in (0, 1, 3):
            with self.subTest(loop=loop), tempfile.TemporaryDirectory() as temporary:
                folder = Path(temporary)
                frames = [Image.new('RGBA', (128,128), color) for color in ('red','blue','green')]
                source = folder/'idle.gif'
                frames[0].save(source, save_all=True, append_images=frames[1:], duration=[70,130,240], loop=loop)
                with Image.open(source) as original:
                    expected_durations = [frame.info['duration'] for frame in ImageSequence.Iterator(original)]
                (folder/'pet.json').write_text(json.dumps({'states': {'idle': 'idle.gif'}, 'rareIdle': {'image':'idle.gif', 'line':'你好'}, 'persona':'保持性格', 'images':{'idle.gif':{'contentTop':0.1, 'frames':3}}}))
                changes = payload.optimize_pet(folder)
                self.assertEqual(len(changes), 1)
                data = json.loads((folder/'pet.json').read_text())
                self.assertEqual(data['persona'], '保持性格')
                self.assertEqual(data['rareIdle'], {'image':'idle.webp', 'line':'你好'})
                self.assertEqual(data['images']['idle.webp']['contentTop'], 0.1)
                with Image.open(folder/'idle.webp') as encoded:
                    self.assertEqual(encoded.info['loop'], 0 if loop == 0 else loop + 1)
                    actual_durations = []
                    for frame in ImageSequence.Iterator(encoded):
                        frame.load()
                        actual_durations.append(frame.info['duration'])
                    self.assertEqual(actual_durations, expected_durations)
                self.assertEqual(data['images']['idle.webp']['width'], 128)
                self.assertEqual(data['images']['idle.webp']['height'], 128)
                self.assertFalse(source.exists())

    def test_scaled_art_is_bounded_and_receipt_prevents_recompression(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            folder = root/'app/icons/characters/fixture'
            folder.mkdir(parents=True)
            image = Image.new('RGBA', (1024, 768), (60, 120, 200, 192))
            image.save(folder/'welcome.png', compress_level=0)
            (folder/'manifest.json').write_text(json.dumps({'assets':{'welcome':'welcome.png','background':'welcome.png'}}))
            payload.optimize_payload(root)
            encoded = folder/'welcome.webp'
            with Image.open(encoded) as image:
                self.assertEqual(image.size, (768,576))
            before = encoded.read_bytes()
            self.assertTrue(payload.optimize_payload(root)['alreadyOptimized'])
            self.assertEqual(encoded.read_bytes(), before)
            encoded.write_bytes(before + b'changed')
            with self.assertRaisesRegex(ValueError, 'fresh staging'):
                payload.optimize_payload(root)

    def test_existing_webp_animation_is_resized_without_losing_alpha(self):
        with tempfile.TemporaryDirectory() as temporary:
            folder = Path(temporary)
            frames = []
            for alpha in (128,192):
                frame = Image.frombytes('RGB',(512,256),random.Random(alpha).randbytes(512*256*3)).convert('RGBA')
                frame.putalpha(alpha)
                frames.append(frame)
            source = folder/'idle.webp'
            frames[0].save(source,'WEBP',save_all=True,append_images=frames[1:],lossless=True,duration=[70,130],loop=2)
            (folder/'pet.json').write_text(json.dumps({'states':{'idle':'idle.webp'},'images':{'idle.webp':{'contentTop':0.1}}}))
            payload.optimize_pet(folder)
            data = json.loads((folder/'pet.json').read_text())
            self.assertEqual(data['images']['idle.webp']['width'],320)
            self.assertEqual(data['images']['idle.webp']['height'],160)
            with Image.open(source) as encoded:
                self.assertEqual(encoded.info['loop'],2)
                for index, frame in enumerate(ImageSequence.Iterator(encoded)):
                    self.assertEqual(frame.convert('RGBA').getchannel('A').getextrema(),(128,128) if index==0 else (192,192))

    def test_saturated_fine_lines_fall_back_to_lossless_after_scaling(self):
        with tempfile.TemporaryDirectory() as temporary:
            source = Path(temporary)/'lines.png'
            image = Image.new('RGBA',(512,512))
            image.putdata([(255,0,0,255) if (x+y)%2 else (0,0,255,255) for y in range(512) for x in range(512)])
            image.save(source)
            row = payload.encode_static(source,512,webp=True)
            self.assertEqual(row['quality'],'lossless')
            self.assertEqual(row['colorRms'],0)
            with Image.open(Path(temporary)/'lines.webp') as encoded:
                self.assertEqual(encoded.convert('RGBA').tobytes(),image.tobytes())

    def test_only_standard_source_maps_are_removed(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            folder = root/'runtime/releases/coding-test/node_modules/sdk'
            folder.mkdir(parents=True)
            for name, raw in {'code.js.map':'{"version":3,"mappings":"","sources":[]}', 'data.map':'{"user":"keep"}', 'types.d.ts':'export const x: number;', 'LICENSE':'retain', 'code.js':'export const x=1;'}.items():
                (folder/name).write_text(raw)
            rows = payload.prune_source_maps(root)
            self.assertEqual(len(rows), 1)
            self.assertEqual({p.name for p in folder.iterdir()}, {'data.map','types.d.ts','LICENSE','code.js'})

    def test_macos_framework_data_links_are_pruned_inside_the_bundle(self):
        with tempfile.TemporaryDirectory() as temporary:
            contents = Path(temporary)/'Umeko.app/Contents'
            frameworks = contents/'Frameworks'
            runtime = contents/'Resources/runtime'
            frameworks.mkdir(parents=True)
            runtime.mkdir(parents=True)
            try:
                (frameworks/'runtime').symlink_to('../Resources/runtime',target_is_directory=True)
            except OSError:
                self.skipTest('Creating a directory link is unavailable on this host')
            (runtime/'code.js.map').write_text('{"version":3,"mappings":""}')
            (runtime/'LICENSE').write_text('retain')
            self.assertEqual(len(payload.prune_source_maps(frameworks)),1)
            self.assertTrue((runtime/'LICENSE').is_file())

    def test_source_checkout_is_never_optimized(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root/'.git').write_text('gitdir: shared')
            with self.assertRaises(ValueError):
                payload.optimize_payload(root)

    def test_qt_reads_projected_animation(self):
        try:
            from PySide6.QtGui import QImageReader
        except ImportError:
            self.skipTest('Qt validation runs in the native application/package checks')
        with tempfile.TemporaryDirectory() as temporary:
            folder = Path(temporary)
            frames = [Image.new('RGBA',(128,128),color) for color in ('red','blue','green')]
            source = folder/'idle.gif'
            frames[0].save(source,save_all=True,append_images=frames[1:],duration=[70,130,240],loop=0)
            (folder/'pet.json').write_text(json.dumps({'states':{'idle':'idle.gif'}}))
            payload.optimize_pet(folder)
            reader = QImageReader(str(folder/'idle.webp'))
            self.assertTrue(reader.supportsAnimation())
            self.assertEqual(reader.imageCount(), 3)
            self.assertEqual(reader.loopCount(), -1)
            for duration in (70,130,240):
                self.assertFalse(reader.read().isNull())
                self.assertEqual(reader.nextImageDelay(), duration)


if __name__ == '__main__':
    unittest.main()
