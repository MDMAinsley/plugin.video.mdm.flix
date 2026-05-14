def build_source(
    source_id,
    label,
    url=None,
    provider_id=None,
    provider_name=None,
    quality=None,
    host=None,
    size=None,
    debrid=False,
    extra=None,
):
    return {
        "source_id": source_id,
        "label": label,
        "url": url or "",
        "provider_id": provider_id or "",
        "provider_name": provider_name or "",
        "quality": quality or "Unknown",
        "host": host or "",
        "size": size or "",
        "debrid": bool(debrid),
        "extra": extra or {},
    }


def normalise_source(raw, fallback_provider_id="", fallback_provider_name=""):
    return build_source(
        source_id=raw.get("source_id") or raw.get("id") or "",
        label=raw.get("label") or raw.get("name") or "Unknown Source",
        url=raw.get("url", ""),
        provider_id=raw.get("provider_id") or fallback_provider_id,
        provider_name=raw.get("provider_name") or raw.get("provider") or fallback_provider_name,
        quality=raw.get("quality", "Unknown"),
        host=raw.get("host", ""),
        size=raw.get("size", ""),
        debrid=raw.get("debrid", False),
        extra=raw.get("extra", {}),
    )


def normalise_sources(raw_sources, fallback_provider_id="", fallback_provider_name=""):
    return [
        normalise_source(
            raw,
            fallback_provider_id=fallback_provider_id,
            fallback_provider_name=fallback_provider_name,
        )
        for raw in raw_sources or []
    ]