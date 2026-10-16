"""Small atomic, URL-free latest Autoplay report, read fresh across plugin invocations."""
import json
import os
import re
import tempfile
import time
import uuid
import xbmcvfs

STATUSES = {"resolving", "handoff", "no_sources", "sources_failed", "stopped", "preparing", "budget", "cancelled", "unexpected"}
COUNTS = {"attempted": 3, "failed": 3, "not_ready": 3, "duplicate_skipped": 10000}


def path(addon):
    return os.path.join(xbmcvfs.translatePath(addon.getAddonInfo("profile")), "last_autoplay_resolution.json")


def new(addon):
    return dict(schema=1, run_id=uuid.uuid4().hex[:12], updated_utc=int(time.time()),
                version=addon.getAddonInfo("version"), status="resolving",
                attempted=0, failed=0, not_ready=0, duplicate_skipped=0)


def validated(value):
    if not isinstance(value, dict) or value.get("schema") != 1 or value.get("status") not in STATUSES:
        return {}
    if not isinstance(value.get("run_id"), str) or not re.fullmatch(r"[0-9a-f]{12}", value["run_id"]):
        return {}
    if type(value.get("updated_utc")) is not int or not 0 < value["updated_utc"] <= int(time.time()) + 60:
        return {}
    if not isinstance(value.get("version"), str) or not re.fullmatch(r"[0-9]+(?:\.[0-9]+){1,3}", value["version"]):
        return {}
    if any(type(value.get(key)) is not int or not 0 <= value[key] <= limit for key, limit in COUNTS.items()):
        return {}
    return {key:value[key] for key in ("schema", "run_id", "updated_utc", "version", "status", *COUNTS)}


def write(addon, report):
    temporary = None
    try:
        report["updated_utc"] = int(time.time())
        safe = validated(report)
        if not safe:
            return False
        destination = path(addon)
        os.makedirs(os.path.dirname(destination), exist_ok=True)
        with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=os.path.dirname(destination), prefix=".mdm-autoplay-", delete=False) as stream:
            temporary = stream.name
            json.dump(safe, stream, sort_keys=True)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, destination)
        return True
    except Exception:
        return False
    finally:
        if temporary and os.path.exists(temporary):
            try:
                os.remove(temporary)
            except OSError:
                pass


def read(addon):
    try:
        with open(path(addon), encoding="utf-8") as stream:
            raw = stream.read(4097)
        return validated(json.loads(raw)) if len(raw) <= 4096 else {}
    except Exception:
        return {}
