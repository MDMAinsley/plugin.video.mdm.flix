# -*- coding: utf-8 -*-

from resources.lib.constants import (
    PLAYBACK_MODE_AUTOPLAY,
    PLAYBACK_MODE_SOURCE_SELECT,
)


def get_playback_mode(addon):
    raw = addon.getSetting("playback_mode")

    if raw == "Autoplay":
        return PLAYBACK_MODE_AUTOPLAY

    return PLAYBACK_MODE_SOURCE_SELECT


def sort_sources(sources):
    quality_rank = {
        "4K": 500,
        "2160p": 500,
        "1080p": 400,
        "720p": 300,
        "480p": 200,
        "SD": 100,
        "Unknown": 0,
    }

    def score(source):
        quality = source.get("quality", "Unknown")
        debrid_bonus = 100 if source.get("debrid") else 0
        return quality_rank.get(quality, 0) + debrid_bonus

    return sorted(sources or [], key=score, reverse=True)


def pick_best_source(sources):
    sorted_sources = sort_sources(sources)
    if not sorted_sources:
        return None

    return sorted_sources[0]