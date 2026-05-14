def build_media_item(
    media_type,
    title,
    tmdb_id=None,
    imdb_id=None,
    tvdb_id=None,
    year=None,
    season=None,
    episode=None,
    extra=None,
):
    return {
        "media_type": media_type,
        "title": title,
        "tmdb_id": tmdb_id or "",
        "imdb_id": imdb_id or "",
        "tvdb_id": tvdb_id or "",
        "year": year or "",
        "season": season or "",
        "episode": episode or "",
        "extra": extra or {},
    }


def from_params(params):
    return build_media_item(
        media_type=params.get("media_type", "movie"),
        title=params.get("title", "Unknown Title"),
        tmdb_id=params.get("tmdb_id", ""),
        imdb_id=params.get("imdb_id", ""),
        tvdb_id=params.get("tvdb_id", ""),
        year=params.get("year", ""),
        season=params.get("season", ""),
        episode=params.get("episode", ""),
    )