"""Command-line entry and transport for the running Umeko profile."""
from __future__ import annotations

import argparse
from collections import deque
import json
import os
from pathlib import Path
import subprocess
import sys
import time

from PySide6.QtCore import QCoreApplication
from PySide6.QtNetwork import QLocalSocket

from .cli_path import WINDOWS_CLI
from .preview_launch import profile_directory
from .terminal_ipc import encode, endpoint, frames


class TerminalClient:
    def __init__(self, *, start=True):
        self.app = QCoreApplication.instance() or QCoreApplication([])
        self.socket = QLocalSocket()
        self.sequence = 0
        self.inbox = deque()
        name = endpoint(profile_directory())

        def connect(wait):
            self.socket.abort()
            self.socket.connectToServer(name)
            return self.socket.waitForConnected(wait)

        if not connect(200):
            if not start:
                raise OSError("The Umeko terminal host is not available")
            executable = Path(sys.executable)
            environment = os.environ.copy()
            command = [str(executable)]
            if getattr(sys, "frozen", False):
                if sys.platform == "win32" and executable.name.casefold() == WINDOWS_CLI.casefold():
                    command[0] = str(executable.with_name("Umeko.exe"))
                environment["PYINSTALLER_RESET_ENVIRONMENT"] = "1"
            else:
                command.append(str(Path(__file__).resolve().parents[1] / "main.py"))
            subprocess.Popen([*command, "--cli-host"], stdin=subprocess.DEVNULL,
                             stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                             cwd=str(Path.home()), env=environment, start_new_session=os.name != "nt",
                             creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0)
            deadline = time.monotonic() + 12
            while not connect(200):
                if time.monotonic() >= deadline:
                    raise OSError("Could not reach the Umeko terminal host. Start this Umeko build and retry.")
                time.sleep(0.08)

    @property
    def alive(self):
        return self.socket.state() == QLocalSocket.ConnectedState

    def send(self, operation, **parameters):
        if not self.alive:
            raise OSError("Disconnected from Umeko Desktop")
        self.sequence += 1
        self.socket.write(encode({"id": self.sequence, "op": operation, **parameters}))
        self.socket.flush()
        return self.sequence

    def read(self):
        self.app.processEvents()
        while self.inbox:
            yield self.inbox.popleft()
        yield from frames(self.socket)

    def call(self, operation, **parameters):
        identifier = self.send(operation, **parameters)
        deadline = time.monotonic() + 30
        while self.alive and time.monotonic() < deadline:
            self.app.processEvents()
            for frame in frames(self.socket):
                if frame.get("id") == identifier:
                    if "error" in frame:
                        raise ValueError(frame["error"])
                    return frame.get("result")
                if "event" in frame:
                    self.inbox.append(frame)
                    if len(self.inbox) > 256:
                        self.inbox.popleft()
            self.socket.waitForReadyRead(70)
        raise OSError("Timed out waiting for Umeko Desktop")

    def close(self):
        self.socket.abort()


def parser():
    program = Path(sys.executable).stem
    result = argparse.ArgumentParser(
        prog=program if program.casefold() == Path(WINDOWS_CLI).stem.casefold() else "umeko",
        description="Umeko sessions in your terminal",
    )
    sub = result.add_subparsers(dest="command")
    chat = sub.add_parser("chat", help="Open a terminal conversation")
    chat.add_argument("--cwd", default=os.getcwd())
    chat.add_argument("--resume", metavar="SESSION")
    chat.add_argument("--model", metavar="ALIAS")
    chat.add_argument("--effort", metavar="LEVEL")
    sub.add_parser("desktop", help="Open the Umeko Desktop window")
    sessions = sub.add_parser("session", help="List or resume a native Umeko session")
    session = sessions.add_subparsers(dest="action", required=True)
    session.add_parser("list")
    resume = session.add_parser("resume")
    resume.add_argument("resume")
    compact = session.add_parser("compact")
    compact.add_argument("resume")
    compact.add_argument("instructions", nargs="?", default="")
    providers = sub.add_parser("provider", help="Manage shared Umeko providers")
    provider = providers.add_subparsers(dest="action", required=True)
    for action in ("list", "packages"):
        provider.add_parser(action)
    provider.add_parser("install").add_argument("file", metavar="PLUGIN.zip")
    for action in ("config", "models"):
        arguments = provider.add_parser(action)
        arguments.add_argument("provider")
        arguments.add_argument("file", metavar="CONFIG.json")
    provider.add_parser("refresh").add_argument("provider")
    provider.add_parser("save").add_argument("file", metavar="CONFIG.json")
    sub.add_parser("acp", help="Start the experimental ACP stdio adapter")
    return result


def _read_json(path):
    if path == "-":
        return json.load(sys.stdin)
    return json.loads(Path(path).expanduser().read_text(encoding="utf-8"))


def _environment_secret(name):
    value = os.environ.get(name)
    if not value:
        raise ValueError(f"Required environment variable {name} is empty")
    return value


def _provider_command(client, args):
    action = args.action
    call = lambda operation, **data: client.call("provider", action=operation, **data)
    if action in ("list", "packages"):
        return call("providers" if action == "list" else action)
    if action == "install":
        return {"account": call("install", path=str(Path(args.file).expanduser().resolve(strict=True)))}
    if action == "refresh":
        return call("refresh", provider=args.provider)
    config = _read_json(args.file)
    if action == "save":
        if not isinstance(config, dict):
            raise ValueError("Provider configuration must be an object")
        return call("save-provider", provider=config.get("id", ""), api=config["api"], name=config["name"],
                    baseUrl=config["baseUrl"], models=config["models"],
                    key=_environment_secret(config["keyEnv"]) if "keyEnv" in config else "")
    name, field = {"config": ("save-config", "config"), "models": ("save-models", "models")}[action]
    return call(name, provider=args.provider, **{field: config})


def main(argv):
    chat_options = {"--cwd", "--resume", "--model", "--effort"}
    if not argv or argv[0].split("=", 1)[0] in chat_options:
        argv = ["chat", *argv]
    args = parser().parse_args(argv)
    try:
        # JSON and ACP use UTF-8 over pipes, independently of the console code page.
        for stream in (sys.stdin, sys.stdout, sys.stderr):
            if stream is not None and not stream.isatty() and hasattr(stream, "reconfigure"):
                stream.reconfigure(encoding="utf-8")
        if args.command == "acp":
            from .terminal_acp import run_acp
            return run_acp()
        interactive = args.command == "chat" or (args.command == "session" and args.action == "resume")
        if interactive and not (sys.stdin.isatty() and sys.stdout.isatty()):
            raise ValueError("umeko chat needs an interactive terminal")
        client = TerminalClient()
        try:
            if interactive:
                state = client.call("attach", cwd=getattr(args, "cwd", os.getcwd()), session=getattr(args, "resume", None), protocol="tui")
                if getattr(args, "model", None):
                    client.call("model", model=args.model)
                if getattr(args, "effort", None):
                    client.call("effort", effort=args.effort)
                if getattr(args, "model", None) or getattr(args, "effort", None):
                    state = client.call("state")
                from .terminal_ui import run
                run(client, state)
                return 0
            if args.command == "desktop":
                client.call("show")
                return 0
            if args.command == "provider":
                result = _provider_command(client, args)
            elif args.action == "compact":
                state = client.call("attach", session=args.resume)
                client.call("compact", text=args.instructions)
                state = client.call("state")
                deadline = time.monotonic() + 120
                while (state["busy"] or state["queue"]) and time.monotonic() < deadline:
                    time.sleep(0.15)
                    state = client.call("state")
                if state["busy"] or state["queue"]:
                    raise OSError("Compaction is still pending")
                if state["failed"] or state.get("historyError"):
                    raise OSError(state.get("historyError") or "Compaction failed")
                result = {"session": args.resume, "compacted": True}
            else:
                result = client.call("sessions")
            print(json.dumps(result, ensure_ascii=False, indent=2))
            return 1 if result is False else 0
        finally:
            client.close()
    except (ValueError, OSError, RuntimeError, KeyError, TypeError) as error:
        print(f"umeko: {error}", file=sys.stderr)
        return 1
