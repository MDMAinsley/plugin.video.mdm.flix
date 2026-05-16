# -*- coding: utf-8 -*-

_SOURCE_SESSION = {}


def clear_sources():
    _SOURCE_SESSION.clear()


def store_sources(sources):
    clear_sources()

    for index, source in enumerate(sources):
        source_id = source.get("source_id") or str(index)
        _SOURCE_SESSION[source_id] = source

    return _SOURCE_SESSION


def get_source(source_id):
    return _SOURCE_SESSION.get(source_id)