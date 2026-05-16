# -*- coding: utf-8 -*-


def build_artwork(
    poster=None,
    fanart=None,
    thumb=None,
    icon=None,
    clearlogo=None,
    banner=None,
):
    return {
        "poster": poster or "",
        "fanart": fanart or "",
        "thumb": thumb or poster or icon or "",
        "icon": icon or thumb or poster or "DefaultVideo.png",
        "clearlogo": clearlogo or "",
        "banner": banner or "",
    }


def apply_artwork(listitem, artwork):
    if not artwork:
        return

    clean_art = {}

    for key, value in artwork.items():
        if value:
            clean_art[key] = value

    if clean_art:
        listitem.setArt(clean_art)