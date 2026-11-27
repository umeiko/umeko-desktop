"""One lazy, local-only audio player shared by chat and widget cards."""

from pathlib import Path

from PySide6.QtCore import QObject, Property, QUrl, Signal, Slot

from .chatbox import AUDIO_SUFFIXES


class ChatboxAudio(QObject):
    activeChanged = Signal()
    stateChanged = Signal()
    positionChanged = Signal()
    volumeChanged = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._key = ""
        self._failed = False
        self._volume = 0.7
        self._player = None
        self._output = None

    def _init_player(self):
        # Headless and minimal Linux installations need not have the native
        # multimedia dependencies until playback is actually requested.
        from PySide6.QtMultimedia import QAudioOutput, QMediaPlayer

        self._output = QAudioOutput(self)
        self._output.setVolume(self._volume)
        self._player = QMediaPlayer(self)
        self._player.setAudioOutput(self._output)
        self._player.positionChanged.connect(self.positionChanged)
        for signal in (self._player.durationChanged, self._player.seekableChanged,
                       self._player.playbackStateChanged):
            signal.connect(self.stateChanged)
        self._player.errorOccurred.connect(self._on_error)

    def _on_error(self, *_):
        self._failed = True
        self.stateChanged.emit()

    @Property(str, notify=activeChanged)
    def activeKey(self):
        return self._key

    @Property(bool, notify=stateChanged)
    def failed(self):
        return self._failed

    @Property(bool, notify=stateChanged)
    def playing(self):
        return bool(self._player and self._player.playbackState() == self._player.PlaybackState.PlayingState)

    @Property(float, notify=stateChanged)
    def duration(self):
        return self._player.duration() if self._player else 0

    @Property(float, notify=positionChanged)
    def position(self):
        return self._player.position() if self._player else 0

    @Property(bool, notify=stateChanged)
    def seekable(self):
        return bool(self._player and self._player.isSeekable())

    @Property(float, notify=volumeChanged)
    def volume(self):
        return self._volume

    @Slot(str, str)
    def toggle(self, key, raw):
        if not key:
            return
        if key == self._key and self._player and not self._failed:
            if self.playing:
                self._player.pause()
            else:
                if self._player.mediaStatus() == self._player.MediaStatus.EndOfMedia:
                    self._player.setPosition(0)
                self._player.play()
            return
        self.deactivate(self._key)
        self._key, self._failed = key, False
        self.activeChanged.emit()
        self.stateChanged.emit()
        try:
            path = Path(raw)
            if not path.is_absolute() or raw.startswith(("//", "\\\\", "/\\", "\\/")):
                raise ValueError("expected local path")
            path = path.resolve(strict=True)
            if (str(path).startswith(("//", "\\\\")) or not path.is_file()
                    or path.suffix.lower() not in AUDIO_SUFFIXES):
                raise ValueError("expected supported local audio file")
        except (ValueError, OSError, RuntimeError):
            self._on_error()
            return
        if not self._player:
            try:
                self._init_player()
            except (ImportError, OSError):
                self._on_error()
                return
        self._player.setSource(QUrl.fromLocalFile(str(path)))
        self._player.play()

    @Slot(str)
    def deactivate(self, key):
        if not key or key != self._key:
            return
        self._key, self._failed = "", False
        self.activeChanged.emit()
        if self._player:
            self._player.stop()
            self._player.setSource(QUrl())

    @Slot(str, float)
    def seek(self, key, position):
        if key == self._key and self.seekable and 0 <= position <= self.duration:
            self._player.setPosition(round(position))

    @Slot(float)
    def setVolume(self, volume):
        if 0 <= volume <= 1:
            self._volume = volume
            if self._output:
                self._output.setVolume(volume)
            self.volumeChanged.emit()
