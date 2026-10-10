import re
from resources.lib.catalogue.tmdb import TMDB, number
from resources.lib.models.media_item import build_media_item
from resources.lib.playback.errors import PlaybackError


def load(addon, core, params):
    client = TMDB(addon, core)
    media = params.get('media_type', 'movie')
    if media not in ('movie', 'tv', 'episode'):
        raise PlaybackError('This playback link has an invalid media type.')
    tmdb_id = number(params.get('tmdb_id'), 1)
    is_episode = media in ('tv', 'episode')
    kind = 'tv' if is_episode else 'movie'
    data = client.request('{}/{}'.format(kind, tmdb_id), {'language':'en-US','append_to_response':'external_ids,alternative_titles'}, ttl=3600)
    external = data.get('external_ids')
    imdb = external.get('imdb_id') if isinstance(external,dict) else data.get('imdb_id')
    if not isinstance(imdb,str) or not re.fullmatch(r'tt[0-9]+',imdb):
        if addon.getSetting('scraper_provider')!='MDM Link':
            raise PlaybackError('TMDB has no IMDb ID for this title. CocoScrapers cannot search it yet.')
        imdb=None
    date = data.get('first_air_date' if is_episode else 'release_date') or ''
    year = int(date[:4]) if isinstance(date,str) and date[:4].isdigit() else None
    title = data.get('name' if is_episode else 'title')
    if not isinstance(title,str) or not title or not year:
        raise PlaybackError('TMDB title/year information is incomplete. Choose another title or try again later.')
    alternatives = data.get('alternative_titles')
    alternatives = alternatives if isinstance(alternatives,dict) else {}
    rows = alternatives.get('results' if is_episode else 'titles', [])
    aliases = [row['title'] for row in (rows if isinstance(rows,list) else []) if isinstance(row,dict) and isinstance(row.get('title'),str) and row.get('iso_3166_1') in ('US','GB')]
    item = build_media_item('episode' if is_episode else 'movie',title,tmdb_id=tmdb_id,imdb_id=imdb,year=year)
    item['extra']={'aliases':aliases}
    if is_episode:
        season, episode = number(params.get('season')), number(params.get('episode'),1)
        episode_data = client.request('tv/{}/season/{}/episode/{}'.format(tmdb_id,season,episode), {'language':'en-US'},ttl=3600)
        episode_title=episode_data.get('name')
        episode_title=episode_title if isinstance(episode_title,str) and episode_title else 'Episode {}'.format(episode)
        item.update(tvshowtitle=title, title=episode_title, season=season,episode=episode)
    return item
