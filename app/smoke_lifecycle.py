"""Let the packaged preview verifier finish after its observable checks."""
from pathlib import Path

from PySide6.QtCore import QTimer


def watch_smoke_finish(app, window, finish_file, snapshot=""):
    """The verifier owns the deadline; ordinary application launches never use this."""
    marker = Path(finish_file)
    timer = QTimer(app)
    timer.setInterval(50)

    def check():
        if not marker.is_file():
            return
        timer.stop()
        try:
            if snapshot and not window.grabWindow().save(snapshot):
                app.exit(1)
                return
        except OSError:
            app.exit(1)
            return
        app.quit()

    timer.timeout.connect(check)
    timer.start()
    return timer
