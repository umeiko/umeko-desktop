"""Exercise inline WAV playback with a real QMediaPlayer and the chat UI."""

import os
import faulthandler
from pathlib import Path
import sys
import tempfile
import wave

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
os.environ.setdefault('QT_QUICK_BACKEND', 'software')

from PySide6.QtCore import QPoint, QPointF, QRect, Qt
from PySide6.QtTest import QTest
from multimodal_ui_smoke import find
from main import create_application


def click(window, item):
    point = item.mapToScene(QPointF(item.width() / 2, item.height() / 2)).toPoint()
    QTest.mouseClick(window, Qt.LeftButton, Qt.NoModifier, point)


def until(predicate, detail):
    for _ in range(500):
        try:
            if predicate():
                return
        except AssertionError:
            pass
        QTest.qWait(10)
    assert predicate(), detail()


def drag(window, slider, start, end):
    def point(fraction):
        x = slider.property('leftPadding') + slider.property('availableWidth') * fraction
        return slider.mapToScene(QPointF(x, slider.height() / 2)).toPoint()
    QTest.mousePress(window, Qt.LeftButton, Qt.NoModifier, point(start))
    assert slider.property('pressed'), (slider.objectName(), point(start), slider.width(), slider.height())
    destination = point(end)
    QTest.mouseMove(window, QPoint(destination.x(), destination.y()), 50)
    QTest.mouseRelease(window, Qt.LeftButton, Qt.NoModifier, destination)


def run():
    faulthandler.dump_traceback_later(20)
    with tempfile.TemporaryDirectory(prefix='umeko-audio-ui-') as temp:
        os.environ['UMEKO_DATA_DIR'] = temp
        os.environ['PI_CODING_AGENT_DIR'] = str(Path(temp) / 'agent')
        fixture = Path(temp) / 'offline audio #1.wav'
        with wave.open(str(fixture), 'wb') as output:
            output.setparams((1, 2, 32000, 0, 'NONE', 'not compressed'))
            output.writeframes(b'\0\0' * 32000 * 8)
        app, engine, backend = create_application()
        window = engine.rootObjects()[0]
        window.resize(1050, 900)
        window.setProperty('page', 'chat')
        player = engine.rootContext().contextProperty('chatboxAudio')
        details = lambda: f'playing={player.playing} duration={player.duration} position={player.position} error={player.failed}'
        try:
            backend._view.messages = [
                {'role': 'user', 'text': 'Play the voice clip in this chat.'},
                {'role': 'assistant', 'text': '', 'tools': [
                    {'id': 'voice', 'name': 'voice_gen', 'state': 'done', 'media': [{'kind': 'audio', 'path': str(fixture), 'title': '离线语音试听.wav'}]},
                    {'id': 'manual', 'name': 'submit_to_chatbox', 'state': 'done', 'media': [{'kind': 'file', 'path': str(fixture)}]},
                ]},
            ]
            backend.chatChanged.emit()
            until(lambda: bool(find(window, 'chatboxAudioPlay_voice_0')), details)
            assert not player.activeKey and not player.playing
            play = find(window, 'chatboxAudioPlay_voice_0')
            assert play.isVisible()
            click(window, play)
            until(lambda: player.playing and player.seekable and player.position > 0, details)
            assert player.duration == 8000, details()
            click(window, play)
            until(lambda: not player.playing, details)
            seek = find(window, 'chatboxAudioSeek_voice_0')
            drag(window, seek, player.position / player.duration, .68)
            until(lambda: 4700 < player.position < 6300, details)
            assert not player.playing
            click(window, find(window, 'chatboxAudioVolumeButton_voice_0'))
            volume = find(window, 'chatboxAudioVolume_voice_0')
            assert volume.isVisible()
            drag(window, volume, .7, .32)
            assert .20 < player.volume < .43, player.volume
            if os.environ.get('UMEKO_AUDIO_CONTROLS_PREVIEW'):
                QTest.qWait(180)
                card = find(window, 'chatboxCard_voice_0')
                corner = card.mapToScene(QPointF(0, 0)).toPoint()
                image = window.grabWindow()
                ratio = image.devicePixelRatio()
                region = QRect(round((corner.x() - 18) * ratio), round((corner.y() - 12) * ratio),
                               round((card.width() + 36) * ratio), round((card.height() + 78) * ratio))
                assert image.copy(region).save(os.environ['UMEKO_AUDIO_CONTROLS_PREVIEW'])
            QTest.keyClick(window, Qt.Key_Escape)
            assert not volume.isVisible()
            backend.setTheme('dark')
            QTest.qWait(180)
            assert play.isVisible() and not player.playing
            second = find(window, 'chatboxAudioPlay_manual_0')
            assert second.isVisible()
            click(window, second)
            until(lambda: player.playing and player.activeKey.startswith('manual_0:'), details)
            backend.newSession()
            until(lambda: not player.playing and not player.activeKey, details)
            print('CHATBOX_AUDIO_UI_OK: WAV play, pause, seek, volume, both sources, and session switching')
        finally:
            player.deactivate(player.activeKey)
            backend.close()
            window.hide()
            import shiboken6
            shiboken6.delete(engine)


if __name__ == '__main__':
    run()
