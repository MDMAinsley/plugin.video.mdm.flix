from resources.lib.providers.base import BaseProvider


class MDMLinkProvider(BaseProvider):
    provider_id = "mdm_link"
    name = "MDM Link"

    def is_available(self):
        # Development fallback for now.
        # Later this will check whether external script.mdm.link is installed.
        return True

    def search_sources(self, item):
        return [
            {
                "id": "mdm_test_hls",
                "provider_id": self.provider_id,
                "label": "MDM Link Test Source - HLS",
                "quality": "720p",
                "provider": self.name,
                "url": "https://test-streams.mux.dev/x36xhzz/x36xhzz.m3u8",
            }
        ]

    def resolve_source(self, source):
        return source.get("url")