# MDM Flix 0.3.1

This batch connects the TMDB catalogue to MDM Link 0.1.1's real source API. Link supports Free, Debrid and Combined modes, Internet Archive direct files, Torrentio torrent metadata and three configurable stream-provider slots. See MDM Link's README for coverage and limitations. Core 1.0.0 and Link 0.1.1 are required dependencies.

Select MDM Link explicitly in Flix's General settings to use Link. Auto keeps the existing CocoScrapers behavior. Provider Settings and AllDebrid Tools actions follow the selected provider. Link imports existing Flix authorisation once inside Kodi; later account settings/disconnect remain separate. Free/direct playback does not require Flix AllDebrid credentials. Source labels distinguish Free/direct from AllDebrid/unchecked.

## CocoScrapers playback setup

Install/enable CocoScrapers 1.0.39 or later from its own repository. This is an optional
dependency: browsing works without it. Flix does not bundle or modify third-party scraper code.
Keep Scraper Provider on Auto or CocoScrapers. Tools â†’ Provider Settings opens CocoScrapers;
only enabled CocoScrapers torrent providers are searched.

Tools â†’ Authorise AllDebrid displays a PIN. Visit https://alldebrid.com/pin/ on your browser,
enter it, and keep the Kodi dialog open. Alternatively enter your own API key in Flix settings.
No credentials are required in chat. Check AllDebrid account shows subscription/auth status.
Disconnect removes the local key and source session; revoke keys separately in AllDebrid if needed.
Account identifiers, email addresses and keys are not shown in diagnostics.

Open a movie or episode's information folder, close the information dialog, then choose
Find playback sources. Pick a result to resolve and play; Link Free mode also supplies direct video. In Autoplay mode the
folder has a Play (Autoplay) item; it searches and resolves the top result only. If it fails,
choose Source Select and try another candidate. Debrid sources sort before free sources. When both types are returned, open AllDebrid sources, Free sources or All sources; each folder shows its count. These folders reuse the same search and source session. Results are a scrolling list, with no separate next page. Search again if a source list expires or another search replaces it.

Source labels say unchecked: the current documented AllDebrid API has no instant-availability
endpoint. Only a selected source is uploaded to your account, never every search result.
An uncached source can start an AllDebrid transfer; cancelling/timeout returns control but
does not delete that account transfer. Manage transfers in AllDebrid. Preparation is bounded
to 60 seconds per stage; retry the same result later when ready. Polls wait at least 5 seconds.

CocoScrapers search is bounded to 45 seconds with at most six daemon workers; Link search uses 30 seconds and at most five workers; individual third-party
requests already in flight cannot be forcibly stopped, but no further work starts on cancel.
Sessions expire after 30 minutes; a newer source search replaces the previous list.
Sessions contain original candidates and public title metadata, not local API keys or
AllDebrid-resolved signed URLs. Original direct-provider URLs can contain signed access
parameters and remain in the local session until replaced or cleared. Kodi settings mask the key but do not encrypt it on disk.

Torrent folders are flattened, non-video/sample/trailer files excluded, and episode numbers
matched explicitly (including season 0). Multiple matching files prompt for selection.
Ambiguous/unmatched episodes are never replaced with an arbitrary video. Movie results with
multiple videos also prompt; provider title filtering handles release matching.
Only ordinary HTTP(S) playable URLs reach Kodi. HLS plays natively; DASH requires enabled
InputStream Adaptive. Playback startup/runtime failures remain Kodi/platform acceptance.

API contracts: https://docs.alldebrid.com/
Third-party repository: https://github.com/CocoJoe2411/repository.cocoscrapers


## Setup

Install from the development repository with MDM Core 1.0.0 or later.
In Flix Settings â†’ TMDB, enter either your API Read Access Token (preferred)
or your v3 API key. When both are present, the token is used.
Obtain credentials from https://www.themoviedb.org/settings/api.
Enter credentials in Kodi only; do not share them in chat or screenshots.
Fields are masked in the UI; Kodi's settings storage is not an encrypted vault.
Metadata language defaults to en-GB; use a language-region code such as en-US.

## Browse

Movies and TV Shows provide Popular, weekly Trending and Search.
Next page preserves the query. Use Kodi Back to return to previous pages.
TV shows open seasons, including Specials (season 0), then episode lists.
Movies and episodes open information with TMDB IDs and episode coordinates.
Catalogue entries now expose the configured playback route.
Tools â†’ Test Playback retains the existing fixed demo stream.
Provider/playback settings control this batch.

Responses are cached through Core: lists/search for 10 minutes, details for one hour.
Changing credentials or language uses a different hashed cache namespace.
Failed responses are never cached. Artwork uses TMDB HTTPS image URLs.
Diagnostics shows configuration status only, never credentials.

## Credits and API references

This product uses the TMDB API but is not endorsed or certified by TMDB.
TMDB: https://www.themoviedb.org
Tools â†’ About / TMDB credits contains the attribution and official logo.
https://developer.themoviedb.org/docs/authentication-application
https://developer.themoviedb.org/reference/movie-popular-list
https://developer.themoviedb.org/docs/search-and-query-for-details
https://developer.themoviedb.org/docs/image-basics
https://developer.themoviedb.org/docs/faq

Local checks use simulated Kodi APIs and TMDB fixtures; authenticated live API,
Kodi UI/back navigation and Firestick acceptance are tracked separately.


## Device tuning
Device-local profiles, reversible tuning, bounded worker/search/request settings and reported-quality limits. Light Flix artwork reduces image size and omits catalogue fanart. Unknown quality is configurable. TV/decoder capability is not inferred from the Kodi screen. Portable builds exclude device tuning; external scraper requests may finish after a deadline. No bandwidth ranking or cache/widget tuning in this release.
Use Conf Device profiles to preview/apply Low memory or Balanced and undo the last application. Low memory: Flix 2 workers, Link 1 worker, 90s search, 30s requests, Light artwork. Balanced: Flix 6 / Link 5 workers, 45s / 30s search, 15s requests, Standard artwork. Total memory at or below 2048 MB suggests Low memory; free-memory fluctuations do not reapply settings. Quality filtering happens after provider retrieval and again before resolving; both Flix and Link limits apply to Link playback. Set unknown quality to Hide for strict filtering, at the cost of fewer results. This is a preset, not a measured performance optimisation.


## Connection and file-size preferences
Connection speed, maximum reported GiB, explicit missing-metadata controls, estimated average bitrate with 25% reserve, and Quality/Connection/Smallest ordering. Debrid priority preserved; manual selection and single-source autoplay use the same limits. Device-local preferences; no speed probe or stability guarantee. Whole episode-pack sizes do not produce episode bitrate estimates. Conf provides preview/apply/undo for both addons.
Size uses GiB (1024^3 bytes), not decimal GB. Mbps uses 1,000,000 bits/s. Enter your own connection capacity; 0 disables connection classification. Average bitrate = reported size * 8 / title duration; 75% of entered speed is the budget. Variable bitrate peaks, host throughput and runtime accuracy can differ. Connection order: debrid first, then within each access group Fits estimate, Unknown, Above budget; quality breaks ties. Smallest order: debrid first, smaller reported sizes first, unknown last. A positive size cap filters size before sorting, including in Connection mode. Hide unknown size only acts with a positive size cap; Hide unknown bitrate/Above budget only acts with a positive connection. Defaults preserve quality order without new filtering. Torrent/package-size caps are conservative; an excluded pack may contain smaller eligible files. Current source limits are checked again before resolution and against debrid file/stream metadata where supplied. Returned metadata is not a verified download quota.
