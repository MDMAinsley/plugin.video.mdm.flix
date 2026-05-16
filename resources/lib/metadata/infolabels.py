# -*- coding: utf-8 -*-


def build_video_info(
    media_type,
    title,
    originaltitle=None,
    plot=None,
    year=None,
    genre=None,
    rating=None,
    votes=None,
    runtime=None,
    duration=None,
    premiered=None,
    studio=None,
    mpaa=None,
    season=None,
    episode=None,
):
    info = {
        "mediatype": media_type,
        "title": title,
    }

    optional = {
        "originaltitle": originaltitle,
        "plot": plot,
        "year": year,
        "genre": genre,
        "rating": rating,
        "votes": votes,
        "runtime": runtime or duration,
        "premiered": premiered,
        "studio": studio,
        "mpaa": mpaa,
        "season": season,
        "episode": episode,
    }

    for key, value in optional.items():
        if value not in ("", None):
            info[key] = value

    return info


def apply_video_info(listitem, info):
    if not info:
        return

    listitem.setInfo("video", info)