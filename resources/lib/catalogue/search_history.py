"""Device-local history of submitted film and TV searches."""
from contextlib import closing
from pathlib import Path
import sqlite3

import xbmc
import xbmcgui


LIMIT = 10
SETTING = "device_search_history"
TITLE = "Recent searches"
ROUTES = {"search", "search_movies", "search_tv"}


def history_path(addon):
    location = addon.getAddonInfo("profile")
    if not location:
        raise OSError("Kodi profile path unavailable")
    import xbmcvfs

    profile = xbmcvfs.translatePath(location)
    if not profile:
        raise OSError("Kodi profile path unavailable")
    return Path(profile) / "search_history.sqlite"


def remember(addon, query, route):
    if addon.getSetting(SETTING) == "false":
        return
    query = " ".join(query.split())[:200]
    if not query or route not in ROUTES:
        return
    try:
        path = history_path(addon)
        path.parent.mkdir(parents=True, exist_ok=True)
        with closing(sqlite3.connect(path, timeout=0.5)) as db, db:
            db.execute("""
                CREATE TABLE IF NOT EXISTS searches (
                    id INTEGER PRIMARY KEY, term_key TEXT NOT NULL UNIQUE,
                    term TEXT NOT NULL, route TEXT NOT NULL
                )
            """)
            db.execute("DELETE FROM searches WHERE term_key = ?", (query.casefold(),))
            db.execute("INSERT INTO searches (term_key, term, route) VALUES (?, ?, ?)",
                       (query.casefold(), query, route))
            db.execute("DELETE FROM searches WHERE id IN "
                       "(SELECT id FROM searches ORDER BY id DESC LIMIT -1 OFFSET ?)", (LIMIT,))
    except (OSError, sqlite3.Error):
        xbmc.log("MDM Flix could not save recent searches.", xbmc.LOGWARNING)


def clear(dialog, path):
    if not path.is_file():
        return True
    if not dialog.yesno(TITLE, "Clear the saved searches on this device?"):
        return False
    with closing(sqlite3.connect(path, timeout=0.5)) as db, db:
        db.execute("DELETE FROM searches")
    dialog.notification(TITLE, "Search history cleared.")
    return True


def show(nav, addon, clear_only=False):
    dialog = xbmcgui.Dialog()
    if not clear_only and addon.getSetting(SETTING) == "false":
        dialog.ok(TITLE, "Search history is off. You can turn it on in Flix settings.")
        return
    try:
        path = history_path(addon)
        if clear_only:
            clear(dialog, path)
            return
        if not path.is_file():
            dialog.ok(TITLE, "No recent searches yet.")
            return
        with closing(sqlite3.connect(path, timeout=0.5)) as db:
            rows = db.execute("SELECT term, route FROM searches ORDER BY id DESC LIMIT ?", (LIMIT,)).fetchall()
        rows = [(term, route) for term, route in rows if route in ROUTES]
        if not rows:
            dialog.ok(TITLE, "No recent searches yet.")
            return
        labels = [term.replace("[", "［").replace("]", "］") for term, _ in rows]
        while True:
            choice = dialog.select(TITLE, labels + ["Clear history"])
            if choice == len(rows):
                if clear(dialog, path):
                    return
            elif 0 <= choice < len(rows):
                term, route = rows[choice]
                url = nav.build_url(action=route, query=term, recent=1)
                xbmc.executebuiltin(f"ActivateWindow(Videos,{url},return)")
                return
            else:
                return
    except (OSError, sqlite3.Error):
        dialog.ok(TITLE, "Could not access search history. Try again.")
