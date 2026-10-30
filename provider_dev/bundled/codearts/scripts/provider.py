"""CodeArts Provider SDK API v1 entrypoint, account card and model transport."""
from __future__ import annotations

import threading

from umeko_provider_sdk import Provider, ProviderError

from .account import CodeartsAccount
from .i18n import CONSOLE_URL, tr
from .transport import CodeartsTransport


class CodeartsProvider(Provider):
    def __init__(self, context):
        super().__init__(context)
        self._message = self._text("status_unconnected")
        self._models = []
        self._fresh_catalog = False
        self._connected = False
        self._watch_stop = threading.Event()
        self._watcher = None
        self.account = CodeartsAccount(context, progress=self._progress)
        self.transport = CodeartsTransport(context, self.account)

    def _text(self, key):
        return tr(getattr(self.context, "language", "zh"), key)

    def _notify(self, **value):
        callback = getattr(self.context, "notify", None)
        if callback and not self.context.cancelled.is_set():
            callback(value)

    def _progress(self, message):
        self._message = message
        self._notify(message=message)

    def _accept(self, result):
        self._message = result["message"]
        if result["ready"]:
            self._connected = True
            self._models = [{"id": model} for model in result["models"]]
            self._fresh_catalog = True
        return result

    def authenticate(self, credentials):
        result = self._accept(self.account.begin())
        if not result["ready"] and result["message"] != self._text("guide"):
            raise ProviderError(result["message"])
        # The generic login worker immediately calls list_models(refresh=True).
        # Reuse this verified catalog instead of invoking the CLI twice.
        self._fresh_catalog = True
        return {"label": self._text("connected" if result["ready"] else "status_unconnected")}

    def list_models(self, refresh=False):
        if refresh and not self._fresh_catalog:
            self._accept(self.account.begin())
        self._fresh_catalog = False
        return list(self._models)

    def card_fields(self):
        return [{"key": "credentials", "label": self._text("credential_label"),
                 "hint": self._text("guide"), "hasValue": self._connected}]

    def card_actions(self):
        actions = [{"key": "open_console", "label": self._text("open_console")}]
        if self._watcher is not None and self._watcher.is_alive() and not self._watch_stop.is_set():
            actions.append({"key": "cancel_import", "label": self._text("import_cancel")})
        return actions

    def _stop_watch(self):
        self._watch_stop.set()
        if self._watcher and self._watcher is not threading.current_thread():
            self._watcher.join(timeout=2)
        self._watcher = None

    def card_action(self, key):
        if key == "cancel_import":
            self._stop_watch()
            self.account.cancel()
            self._message = self._text("cancelled_file")
            return {"message": self._message}
        if key != "open_console":
            raise ProviderError(self._text("invalid"))
        self._stop_watch()
        self.account.start_import()
        self._watch_stop = threading.Event()
        self._message = self._text("watching")

        def watch():
            while not self._watch_stop.wait(0.5) and not self.context.cancelled.is_set():
                result = self.account.poll_downloads()
                if result is not None:
                    self._accept(result)
                    if result["ready"]:
                        # Hide Cancel before notifying the host, even while this
                        # thread is still completing the import notification.
                        self._watch_stop.set()
                    self._notify(message=result["message"], refreshModels=bool(result["ready"]))
                    if result["ready"]:
                        return

        self._watcher = threading.Thread(target=watch, name="codearts-csv-import", daemon=True)
        self._watcher.start()
        return {"message": self._message, "url": CONSOLE_URL}

    def set_card_secret(self, key, value):
        if key != "credentials":
            raise ProviderError(self._text("invalid"))
        result = self._accept(self.account.import_text(value))
        if not result["ready"]:
            raise ProviderError(result["message"])
        self._stop_watch()
        return {"message": result["message"]}

    def events(self, model, messages, tools, max_tokens, parameters):
        yield from self.transport.events(model, messages, tools, max_tokens, parameters)

    def close(self):
        super().close()
        self._watch_stop.set()
        self.account.close()
        self.transport.close()
        self._stop_watch()


def create_provider(context):
    return CodeartsProvider(context)
