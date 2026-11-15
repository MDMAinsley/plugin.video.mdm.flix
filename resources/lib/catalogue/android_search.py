"""One-use loopback channel for a confirmed Android search phrase."""
import json
import re
import secrets
import socket
from contextlib import contextmanager
from time import monotonic

import xbmc
import xbmcgui

HELPER = "dev.mdm.firetvvoiceprobe"
VERSION_PROPERTY = "MDM.Flix.VoiceHelperVersion"
NEW_HELPER_TASK = 0x10008000  # Android FLAG_ACTIVITY_NEW_TASK | FLAG_ACTIVITY_CLEAR_TASK


@contextmanager
def search_session():
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as listener:
        listener.bind(("127.0.0.1", 0))
        listener.listen(2)
        token = secrets.token_hex(32)
        yield listener, token


def read_query(listener, token, seconds=90, aborted=lambda: False, ready_timeout=7):
    deadline = monotonic() + seconds
    deadline_to_connect = min(deadline, monotonic() + ready_timeout)
    ready = False
    while monotonic() < (deadline if ready else deadline_to_connect) and not aborted():
        remaining = (deadline if ready else deadline_to_connect) - monotonic()
        listener.settimeout(min(0.25, max(0.001, remaining)))
        try:
            connection, _ = listener.accept()
        except socket.timeout:
            continue
        with connection:
            try:
                line = bytearray()
                receive_by = min(deadline if ready else deadline_to_connect, monotonic() + 0.75)
                while len(line) <= 2048 and not line.endswith(b"\n"):
                    connection.settimeout(max(0.001, receive_by - monotonic()))
                    chunk = connection.recv(2049 - len(line))
                    if not chunk or monotonic() >= receive_by:
                        break
                    line.extend(chunk)
                if not line.endswith(b"\n") or len(line) > 2048:
                    continue
                result = json.loads(line)
                if not isinstance(result, dict) or result.get("token") != token or "query" not in result:
                    continue
                query = result["query"]
                if query is not None and (not isinstance(query, str) or len(query) > 200):
                    continue
                version = result.get("version")
                if not isinstance(version, str) or not re.fullmatch(r"[0-9]{1,3}(?:\.[0-9]{1,3}){1,2}", version):
                    version = "Update to check"
                xbmcgui.Window(10000).setProperty(VERSION_PROPERTY, version)
                if query is None:
                    connection.sendall(b"1")
                    ready = True
                    continue
                connection.sendall(b"1")
                return True, query.strip()
            except (OSError, ValueError):
                continue
    return ready, ""


def prompt(addon, heading):
    if (addon.getSetting("device_voice_search") == "true"
            and xbmc.getCondVisibility("System.Platform.Android")):
        xbmcgui.Window(10000).clearProperty(VERSION_PROPERTY)
        monitor = xbmc.Monitor()
        try:
            with search_session() as (listener, token):
                port = listener.getsockname()[1]
                uri = f"mdmvoice://search:{port}/{token}"
                xbmc.executebuiltin(f"StartAndroidActivity({HELPER},,,{uri},{NEW_HELPER_TASK})")
                connected, query = read_query(listener, token, aborted=monitor.abortRequested)
                if connected or monitor.abortRequested():
                    return query
        except (OSError, RuntimeError):
            pass
    keyboard = xbmc.Keyboard("", heading)
    keyboard.doModal()
    return keyboard.getText().strip() if keyboard.isConfirmed() else ""
