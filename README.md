# MDM Flix 0.1.0

This development batch implements TMDB catalogue browsing, not real-title playback.

## Setup

Install from the development repository with MDM Core 1.0.0 or later.
In Flix Settings → TMDB, enter either your API Read Access Token (preferred)
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
No stream provider is connected to these catalogue entries yet.
Tools → Test Playback retains the existing fixed demo stream.
Provider/playback settings are retained for the later playback batch.

Responses are cached through Core: lists/search for 10 minutes, details for one hour.
Changing credentials or language uses a different hashed cache namespace.
Failed responses are never cached. Artwork uses TMDB HTTPS image URLs.
Diagnostics shows configuration status only, never credentials.

## Credits and API references

This product uses the TMDB API but is not endorsed or certified by TMDB.
TMDB: https://www.themoviedb.org
Tools → About / TMDB credits contains the attribution and official logo.
https://developer.themoviedb.org/docs/authentication-application
https://developer.themoviedb.org/reference/movie-popular-list
https://developer.themoviedb.org/docs/search-and-query-for-details
https://developer.themoviedb.org/docs/image-basics
https://developer.themoviedb.org/docs/faq

Local checks use simulated Kodi APIs and TMDB fixtures; authenticated live API,
Kodi UI/back navigation and Firestick acceptance are tracked separately.
