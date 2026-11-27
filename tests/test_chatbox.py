import copy
import struct
import sys
import tempfile
import unittest
import zlib
from pathlib import Path
from unittest.mock import patch
from PySide6.QtCore import QCoreApplication
from app.chatbox import media_view
from app.chat_model import ChatModel
from app.controller import Controller

ROOT = Path(__file__).resolve().parents[1]
APP = QCoreApplication.instance() or QCoreApplication([])


class ChatboxTests(unittest.TestCase):
    def test_audio_backend_is_optional_until_explicit_play(self):
        with tempfile.TemporaryDirectory() as temp, patch.dict(sys.modules, {'PySide6.QtMultimedia': None}):
            from app.chatbox_audio import ChatboxAudio

            path = Path(temp) / 'fixture.wav'
            path.touch()
            player = ChatboxAudio()
            self.assertFalse(player.failed)
            player.toggle('fixture', str(path))
            self.assertTrue(player.failed)
            self.assertFalse(player.playing)
            player.deactivate('fixture')
            self.assertEqual(player.activeKey, '')
            self.assertFalse(player.failed)

    def test_generation_waiting_active_terminal_and_restored(self):
        for name in ('image_gen', 'voice_gen'):
            for state, pending, active in (('running', False, False), ('running', True, True),
                                           ('error', True, False), ('done', True, False)):
                tool = {'name': name, 'state': state, 'id': 'call', 'generationPending': pending}
                row, = ChatModel.project([{'role': 'assistant', 'tools': [tool]}])
                cards = [step for step in row['activity'] if step['kind'] == 'generation']
                self.assertEqual(bool(cards), active)
                if active:
                    self.assertEqual((cards[0]['toolName'], cards[0]['toolId']), (name, 'call'))

    def test_new_and_legacy_audio_cards(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / '听写 #1.WAV'
            path.touch()
            for kind in ('audio', 'file'):
                row, = media_view([{'kind':kind, 'path':str(path)}])
                self.assertEqual(row['kind'], 'audio')
                self.assertIn('%23', row['url'])
            raw = path.with_suffix('.pcm')
            self.assertEqual(media_view([{'kind':'file', 'path':str(raw)}])[0]['kind'], 'file')
            self.assertEqual(media_view([{'kind':'audio', 'path':'https://example.invalid/a.wav'}]), [])

    def test_projection_preview_limits_and_metadata_cache(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "large # 图.png"
            # A valid header is enough to reject a huge image before decoding.
            def chunk(kind, data): return struct.pack('>I', len(data)) + kind + data + struct.pack('>I', zlib.crc32(kind + data))
            path.write_bytes(b'\x89PNG\r\n\x1a\n' + chunk(b'IHDR', struct.pack('>IIBBBBB', 20000,20000,8,2,0,0,0)) + chunk(b'IDAT',zlib.compress(b'\0')) + chunk(b'IEND',b''))
            items=[{"path":str(path),"title":"Large image", "kind":"image"}, {"path":str(Path(temp)),"kind":"folder"}]
            messages=[{"role":"assistant","text":"", "tools":[{"id":"delivery", "name":"submit_to_chatbox", "media":items, "state":"done"}]}, {"role":"assistant","text":"Done"}]
            original=copy.deepcopy(messages)
            row=ChatModel.project(messages)[0]
            self.assertEqual([step["kind"] for step in row["activity"]], ["tools","media","text"])
            delivered=row["activity"][1]["items"]
            self.assertFalse(delivered[0]["preview"])
            self.assertIn("%23",delivered[0]["url"])
            with patch('app.chatbox.QImageReader',side_effect=AssertionError('streaming must not rescan')):
                self.assertEqual(media_view(items), delivered)
            self.assertEqual(messages,original)
            self.assertEqual(media_view([{"kind":"image","path":"https://example.invalid/a.png"}]),[])

    def test_open_actions_are_explicit_and_local(self):
        with tempfile.TemporaryDirectory() as temp, patch.dict(__import__('os').environ,{"UMEKO_DATA_DIR":temp}):
            controller=Controller(ROOT)
            path=Path(temp)/'report.txt'; path.write_text('fixture')
            try:
                with patch('app.controller.QDesktopServices.openUrl', return_value=True) as opened:
                    controller.openChatboxPath(str(path),False)
                    self.assertEqual(Path(opened.call_args.args[0].toLocalFile()),path)
                    with patch('app.controller.sys.platform','linux'):
                        controller.openChatboxPath(str(path),True)
                    self.assertEqual(Path(opened.call_args.args[0].toLocalFile()),path.parent)
                    controller.openChatboxPath('https://example.invalid/file',False)
                    self.assertEqual(opened.call_count,2)
            finally: controller.close()
