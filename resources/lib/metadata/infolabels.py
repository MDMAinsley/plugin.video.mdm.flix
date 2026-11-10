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
        "duration": runtime or duration,
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

    labels = dict(info)
    unique_ids = labels.pop("uniqueid", None)
    resume_point = labels.pop("resume_point", None)
    listitem.setInfo("video", labels)
    if resume_point:
        tag = listitem.getVideoInfoTag() if hasattr(listitem,"getVideoInfoTag") else None
        if hasattr(tag,"setResumePoint"):
            tag.setResumePoint(*resume_point)
        else:
            listitem.setProperty("ResumeTime",str(resume_point[0]))
            listitem.setProperty("TotalTime",str(resume_point[1]))
    if isinstance(unique_ids, dict):
        # Keep identifiers in Kodi's dedicated field, not legacy setInfo labels.
        if hasattr(listitem, "getVideoInfoTag"):
            listitem.getVideoInfoTag().setUniqueIDs(unique_ids, "tmdb")
        else:
            listitem.setProperty("tmdb_id", unique_ids.get("tmdb", ""))
