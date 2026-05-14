from resources.lib.providers.base import BaseProvider


class MDMLinkProvider(BaseProvider):
    provider_id = "mdm_link"
    name = "MDM Link"

    def is_available(self):
        return True

    def search_sources(self, item):
        return [
            {
                "source_id": "mdm_test_hls",
                "label": "MDM Link Test Source",
                "quality": "720p",
                "host": "Mux Test",
                "provider_id": self.provider_id,
                "provider_name": self.name,
                "url": "https://test-streams.mux.dev/x36xhzz/x36xhzz.m3u8",
            }
        ]

    def resolve_source(self, source):
        return source.get("url")