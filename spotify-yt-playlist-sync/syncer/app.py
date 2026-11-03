"""Experimental one-way YouTube -> Spotify playlist sync."""
import argparse
import base64
import hashlib
import hmac
import json
import logging
import os
from pathlib import Path
import re
import struct
import time
from difflib import SequenceMatcher
from urllib.parse import parse_qs, urlencode, urlparse, urlsplit, urlunsplit

import requests

LOG = logging.getLogger('sync')
UA = 'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/131.0 Safari/537.36'
STATE_PATH = Path('data/sync-state.json')
OVERRIDES_PATH = Path('data/track-overrides.json')
PROXY_URL = 'https://corsly-proxy2.camdvr.org/'
PARTNER_URL = 'https://api-partner.spotify.com/pathfinder/v2/query'
# Unofficial web-player persisted queries; Spotify can rotate these at any time.
GQL_HASHES = {
    'fetchPlaylist': '21ea11a6ac75a5f3e01fd365d29c18e0a4a8b7dc09f89bbb5d73910190c6acaf',
    'searchTracks': 'b02683192a98dde7966b5e6655a79eeb62713eab703eda9902c932818dd52751',
    'addToPlaylist': 'b907ad6b088d5bf7680fa81198996d58398c2d55dfcdf59fcc959e0be98a418a',
}

class SyncError(Exception):
    pass

class FatalError(SyncError):
    pass

class UncertainWrite(FatalError):
    pass

class HttpFatal(FatalError):
    def __init__(self, message, status):
        super().__init__(message)
        self.status = status

def playlist_id(value, kind):
    value = value.strip()
    if not value:
        raise FatalError(f'{kind} playlist ID/URL is missing')
    if kind == 'YouTube':
        ident = parse_qs(urlparse(value).query).get('list', [value])[0]
        if not re.fullmatch(r'[A-Za-z0-9_-]+', ident):
            raise FatalError('Invalid YouTube playlist ID/URL')
    else:
        if value.startswith('spotify:playlist:'):
            ident = value.split(':')[-1]
        elif '://' in value:
            match = re.search(r'/playlist/([A-Za-z0-9]+)', urlparse(value).path)
            ident = match.group(1) if match else ''
        else:
            ident = value
        if not re.fullmatch(r'[A-Za-z0-9]{22}', ident):
            raise FatalError('Invalid Spotify playlist ID/URL')
    return ident

def sp_dc_from_file(path):
    try:
        text = Path(path).read_text(encoding='utf-8-sig')
    except OSError as exc:
        raise FatalError('Cannot read Spotify cookie file; see instructions/spotify.md') from exc
    for line in text.splitlines():
        # HttpOnly Netscape cookies start with #HttpOnly_ and are not comments.
        line = line.removeprefix('#HttpOnly_')
        fields = line.split('\t')
        if len(fields) >= 7 and fields[0].lstrip('.').lower() in ('spotify.com', 'open.spotify.com') and fields[5] == 'sp_dc':
            if fields[6].strip():
                return fields[6].strip()
    raise FatalError('No Spotify sp_dc cookie found in Netscape cookie file')

def totp(cipher):
    key = ''.join(str(x ^ ((i % 33) + 9)) for i, x in enumerate(cipher)).encode('ascii')
    digest = hmac.new(key, struct.pack('>Q', int(time.time() // 30)), hashlib.sha1).digest()
    offset = digest[-1] & 15
    return f'{(struct.unpack(">I", digest[offset:offset+4])[0] & 0x7fffffff) % 1000000:06d}'

class Client:
    def __init__(self, delay):
        self.http = requests.Session()
        self.http.headers.update({'User-Agent': UA})
        self.delay = delay
        self.spotify_backend = None
        self.partner_proxy = True

    def request(self, method, url, *, fatal=False, write=False, label='Service', proxy=False, **kwargs):
        if proxy:
            # Only Spotify API targets may be routed through this proxy. Keep query
            # parameters inside the encoded target URL, not on the proxy request.
            parts = urlsplit(url)
            if parts.scheme != 'https' or parts.netloc not in ('api.spotify.com', 'api-partner.spotify.com'):
                raise FatalError('Refusing to send a non-Spotify target through the proxy')
            params = kwargs.pop('params', None)
            query = parts.query
            if params:
                query = '&'.join(filter(None, [query, urlencode(params, doseq=True)]))
            target = urlunsplit((parts.scheme, parts.netloc, parts.path, query, ''))
            url = PROXY_URL + '?' + urlencode({'url': target})
            # A redirect could forward the bearer token to an untrusted host.
            kwargs['allow_redirects'] = False
        if self.delay:
            time.sleep(self.delay)
        try:
            response = self.http.request(method, url, timeout=30, **kwargs)
        except requests.RequestException as exc:
            if write:
                raise UncertainWrite('Spotify add request had a network error; outcome unknown. Check the playlist before clearing the pending entry.') from exc
            raise (FatalError if fatal else SyncError)(f'{label}: network error during {method} request') from exc
        if proxy and 300 <= response.status_code < 400:
            if write:
                raise UncertainWrite('Proxy redirected Spotify add; outcome unknown. Check the playlist before clearing pending')
            raise HttpFatal(f'{label}: proxy returned HTTP {response.status_code} redirect; refusing to forward credentials', response.status_code)
        if response.status_code >= 400:
            # Never log response bodies, request URLs, query parameters, or headers: they may contain secrets.
            message = f'{label}: {method} request failed (HTTP {response.status_code})'
            if response.status_code in (401, 403) or fatal:
                raise HttpFatal(message + '; check access, credentials, quota and service restrictions', response.status_code)
            if write and response.status_code >= 500:
                raise UncertainWrite(message + '; add outcome unknown. Check playlist before clearing pending entry')
            raise SyncError(message)
        try:
            return response.json()
        except ValueError as exc:
            if write:
                raise UncertainWrite('Spotify add response was invalid; outcome unknown. Check playlist before clearing pending entry') from exc
            raise (FatalError if fatal else SyncError)('Service returned invalid JSON') from exc

    def token(self, cookie):
        # Community-maintained web-player TOTP versions. This is an unofficial, fragile flow.
        response = self.request('GET', 'https://api.github.com/repos/xyloflake/spot-secrets-go/contents/secrets/secretDict.json', fatal=True, label='Spotify TOTP list')
        try:
            versions = json.loads(base64.b64decode(response['content']))
            choices = sorted((int(k), v) for k, v in versions.items() if str(k).isdigit() and isinstance(v, list))[-3:]
        except (KeyError, ValueError, TypeError) as exc:
            raise FatalError('Could not parse the community Spotify TOTP version list') from exc
        for version, cipher in reversed(choices):
            code = totp(cipher)
            # 400 can indicate an old TOTP version; do not print its response or the cookie.
            try:
                r = self.http.get('https://open.spotify.com/api/token', params={'reason': 'transport', 'productType': 'web-player', 'totp': code, 'totpServer': code, 'totpVer': version}, headers={'Referer': 'https://open.spotify.com/', 'App-Platform': 'WebPlayer'}, cookies={'sp_dc': cookie}, timeout=30)
            except requests.RequestException as exc:
                raise FatalError('Could not reach Spotify token endpoint') from exc
            if r.status_code == 400:
                continue
            if r.status_code != 200:
                raise FatalError(f'Spotify token request failed (HTTP {r.status_code}); check cookie or service restrictions')
            try:
                data = r.json()
            except ValueError as exc:
                raise FatalError('Invalid Spotify token response') from exc
            if data.get('isAnonymous') or not data.get('accessToken'):
                raise FatalError('Spotify returned an anonymous session; export a fresh cookie')
            return data['accessToken']
        raise FatalError('Spotify rejected the available TOTP versions; the unofficial login flow may have changed')

    def youtube(self, key, playlist):
        videos = []
        page = None
        while True:
            params = {'part': 'snippet', 'maxResults': 50, 'playlistId': playlist, 'key': key}
            if page:
                params['pageToken'] = page
            data = self.request('GET', 'https://www.googleapis.com/youtube/v3/playlistItems', params=params, fatal=True, label='YouTube playlist')
            for item in data.get('items', []):
                snippet = item.get('snippet', {})
                video = snippet.get('resourceId', {}).get('videoId')
                if video:
                    videos.append({'id': video, 'title': snippet.get('title', ''), 'channel': snippet.get('videoOwnerChannelTitle', '')})
            page = data.get('nextPageToken')
            if not page:
                break

        # playlistItems does not reliably supply the original video description.
        # videos.list gets it for normal uploads and music videos in batches of 50.
        by_id = {}
        for video in videos:
            by_id.setdefault(video['id'], []).append(video)
        ids = list(by_id)
        for start in range(0, len(ids), 50):
            details = self.request('GET', 'https://www.googleapis.com/youtube/v3/videos',
                    params={'part': 'snippet,contentDetails', 'id': ','.join(ids[start:start + 50]), 'key': key},
                    fatal=True, label='YouTube video details')
            if not isinstance(details, dict) or not isinstance(details.get('items'), list):
                raise FatalError('YouTube video details returned an invalid response')
            for item in details['items']:
                snippet = item.get('snippet') or {}
                if not isinstance(snippet, dict):
                    continue
                for video in by_id.get(item.get('id'), []):
                    video['title'] = snippet.get('title') or video['title']
                    video['channel'] = snippet.get('channelTitle') or video['channel']
                    video['description'] = snippet.get('description') or ''
                    content = item.get('contentDetails') or {}
                    if isinstance(content, dict):
                        video['duration_ms'] = youtube_duration_ms(content.get('duration'))
        return videos

    def gql(self, operation, variables, token, *, write=False):
        headers = {'Authorization': f'Bearer {token}', 'Origin': 'https://open.spotify.com',
                   'Referer': 'https://open.spotify.com/', 'app-platform': 'WebPlayer'}
        payload = {'operationName': operation, 'variables': variables,
                   'extensions': {'persistedQuery': {'version': 1, 'sha256Hash': GQL_HASHES[operation]}}}
        data = self.request('POST', PARTNER_URL, headers=headers, json=payload,
                            fatal=not write, write=write, proxy=self.partner_proxy,
                            label=f'Spotify web player ({"proxy" if self.partner_proxy else "direct"}) {operation}')
        if not isinstance(data, dict) or data.get('errors') or not isinstance(data.get('data'), dict):
            if write:
                # HTTP 200 may contain GraphQL errors, partial data, or an unknown
                # response; never assume it was not applied and retry automatically.
                raise UncertainWrite('Spotify web player add returned an error or unrecognized response; outcome unknown. Check the playlist before clearing pending.')
            raise FatalError(f'Spotify web player {operation}: GraphQL error or invalid response; the unofficial operation may have changed')
        return data['data']

    def existing_tracks(self, playlist, token):
        # A successful proxied REST read selects REST for the entire run. If it
        # is rejected, switch before making any write, never after one.
        try:
            tracks = self.rest_existing_tracks(playlist, token)
            self.spotify_backend = 'rest'
            LOG.info('Spotify backend: proxied Web API')
            return tracks
        except HttpFatal as exc:
            if exc.status not in (401, 403, 404, 405, 429, 501):
                raise
            LOG.warning('Proxied Spotify Web API read returned HTTP %s; trying web-player backend', exc.status)
        try:
            tracks = self.gql_existing_tracks(playlist, token)
        except HttpFatal as exc:
            # A proxy may strip Authorization or not implement POST. Compare a
            # direct read before deciding authentication has failed. Never do this
            # for a playlist write, which could already have been applied.
            if exc.status not in (401, 403, 405, 501):
                raise
            LOG.warning('Proxied web-player read returned HTTP %s; trying web-player directly', exc.status)
            self.partner_proxy = False
            tracks = self.gql_existing_tracks(playlist, token)
        self.spotify_backend = 'web-player'
        LOG.info('Spotify backend: web player (%s)', 'proxy' if self.partner_proxy else 'direct')
        return tracks

    def rest_existing_tracks(self, playlist, token):
        ids = set()
        url = f'https://api.spotify.com/v1/playlists/{playlist}/items'
        headers = {'Authorization': f'Bearer {token}'}
        while url:
            data = self.request('GET', url, headers=headers, params={'limit': 50} if '?' not in url else None,
                                fatal=True, proxy=True, label='Spotify proxied playlist read')
            if not isinstance(data, dict) or not isinstance(data.get('items'), list) or 'next' not in data:
                raise FatalError('Spotify proxied playlist read returned an invalid page; refusing to risk duplicates')
            for item in data['items']:
                if not isinstance(item, dict):
                    raise FatalError('Spotify playlist has an invalid item; refusing to risk duplicates')
                track = item.get('item') or item.get('track') or {}
                if track.get('id'):
                    ids.add(track['id'])
            next_url = data['next']
            if next_url and (urlparse(next_url).scheme != 'https' or urlparse(next_url).netloc != 'api.spotify.com'):
                raise FatalError('Unexpected Spotify pagination URL')
            url = next_url
        return ids

    def gql_existing_tracks(self, playlist, token):
        ids, offset = set(), 0
        while True:
            data = self.gql('fetchPlaylist', {'uri': f'spotify:playlist:{playlist}', 'offset': offset,
                    'limit': 100, 'enableWatchFeedEntrypoint': True, 'includeEpisodeContentRatingsV2': True}, token)
            content = (data.get('playlistV2') or {}).get('content')
            if not isinstance(content, dict) or not isinstance(content.get('items'), list) or not isinstance(content.get('totalCount'), int) or content['totalCount'] < 0:
                raise FatalError('Spotify web-player playlist response is incomplete; refusing to risk duplicates')
            items = content['items']
            for entry in items:
                if not isinstance(entry, dict):
                    raise FatalError('Spotify playlist contains an invalid item; refusing to risk duplicates')
                wrapper = entry.get('itemV2') or {}
                if not isinstance(wrapper, dict):
                    raise FatalError('Spotify playlist contains an unreadable item; refusing to risk duplicates')
                track = wrapper.get('data') or {}
                if not isinstance(track, dict):
                    raise FatalError('Spotify playlist contains an unreadable item; refusing to risk duplicates')
                uri = track.get('uri') or wrapper.get('uri') or wrapper.get('_uri') or ''
                if not isinstance(uri, str):
                    raise FatalError('Spotify playlist contains an unreadable URI; refusing to risk duplicates')
                if uri.startswith('spotify:track:'):
                    ids.add(uri.removeprefix('spotify:track:'))
                elif not uri and (track.get('__typename') == 'Track' or wrapper.get('__typename') == 'TrackResponseWrapper'):
                    raise FatalError('Spotify playlist track has no URI; refusing to risk duplicates')
            offset += len(items)
            if offset >= content['totalCount']:
                return ids
            if not items:
                raise FatalError('Spotify web-player playlist pagination ended early; refusing to risk duplicates')

    def search(self, artist, title, token):
        # Discard presentation-only labels, while keeping the version in the query.
        query = ' '.join(part for part in (artist, canonical_track_title(title)) if part)
        if self.spotify_backend == 'rest':
            data = self.request('GET', 'https://api.spotify.com/v1/search', headers={'Authorization': f'Bearer {token}'},
                    params={'q': query, 'type': 'track', 'limit': 10}, proxy=True, label='Spotify search')
            return data.get('tracks', {}).get('items', [])
        if self.spotify_backend != 'web-player':
            raise FatalError('Spotify backend was not initialized')
        data = self.gql('searchTracks', {'searchTerm': query, 'offset': 0,
                 'limit': 10, 'numberOfTopResults': 5, 'includeAudiobooks': False,
                 'includeArtistHasConcertsField': False, 'includePreReleases': False,
                 'includeLocalConcertsField': False, 'includeAuthors': False}, token)
        section = (data.get('searchV2') or {}).get('tracksV2')
        if not isinstance(section, dict) or not isinstance(section.get('items'), list):
            raise FatalError('Spotify web-player search response is incomplete')
        results = []
        for entry in section['items']:
            wrapper = entry.get('item') or entry
            item = wrapper.get('data') or {}
            uri = item.get('uri') or wrapper.get('uri') or wrapper.get('_uri') or ''
            if not uri.startswith('spotify:track:'):
                continue
            artists = item.get('artists') or {}
            duration = item.get('duration') or item.get('trackDuration') or {}
            duration_ms = duration.get('totalMilliseconds') if isinstance(duration, dict) else None
            result = {'id': uri.removeprefix('spotify:track:'), 'name': item.get('name', ''),
                'artists': [{'name': (a.get('profile') or {}).get('name', '')} for a in artists.get('items', [])]}
            if isinstance(duration_ms, (int, float)) and duration_ms > 0:
                result['duration_ms'] = duration_ms
            results.append(result)
        return results

    def add(self, playlist, track, token):
        if self.spotify_backend == 'rest':
            self.request('POST', f'https://api.spotify.com/v1/playlists/{playlist}/items',
                    headers={'Authorization': f'Bearer {token}'}, json={'uris': [f'spotify:track:{track}']},
                    write=True, proxy=True, label='Spotify proxied playlist add')
            return
        if self.spotify_backend != 'web-player':
            raise FatalError('Spotify backend was not initialized')
        data = self.gql('addToPlaylist', {'playlistUri': f'spotify:playlist:{playlist}',
                  'playlistItemUris': [f'spotify:track:{track}'],
                  'newPosition': {'moveType': 'BOTTOM_OF_PLAYLIST', 'fromUid': None},
                  'interactionId': None}, token, write=True)
        result = data.get('addItemsToPlaylist')
        if not isinstance(result, dict) or result.get('__typename') != 'AddItemsToPlaylistPayload':
            raise UncertainWrite('Spotify web-player add did not confirm success; check the playlist before clearing pending')

    def telegram(self, token, chat, message):
        if not token or not chat:
            LOG.warning('Telegram not configured; summary only in Actions log')
            return
        try:
            r = self.http.post(f'https://api.telegram.org/bot{token}/sendMessage', json={'chat_id': chat, 'text': message, 'disable_web_page_preview': True}, timeout=20)
            if not r.ok:
                LOG.warning('Telegram delivery failed (HTTP %s)', r.status_code)
        except requests.RequestException:
            LOG.warning('Telegram delivery failed (network error)')

def youtube_duration_ms(value):
    """Read the ISO-8601 duration returned by YouTube videos.list."""
    if not isinstance(value, str):
        return None
    match = re.fullmatch(r'P(?:(\d+)D)?(?:T(?:(\d+)H)?(?:(\d+)M)?(?:(\d+(?:\.\d+)?)S)?)?', value)
    if not match or not any(group is not None for group in match.groups()):
        return None
    days, hours, minutes, seconds = match.groups()
    total = int(days or 0) * 86400 + int(hours or 0) * 3600 + int(minutes or 0) * 60 + float(seconds or 0)
    return int(total * 1000) if total > 0 else None

def normalized(s):
    # Remove non-musical labels, but retain mix/version labels such as Slowed.
    s = re.sub(r'\([^)]*(?:official|video|audio|lyrics|visualizer)[^)]*\)|\[[^]]*(?:official|video|audio|lyrics|visualizer)[^]]*\]', ' ', s, flags=re.I)
    s = re.sub(r'\s*[|–—-]\s*(?:official\s+)?(?:music\s+)?(?:video|audio|lyrics|visualizer)\s*$', '', s, flags=re.I)
    return ' '.join(re.findall(r'[^\W_]+', s.casefold()))

def title_similarity(a, b):
    left, right = normalized(a), normalized(b)
    if not left or not right:
        return 0.0
    return SequenceMatcher(None, left, right).ratio()

def canonical_track_title(title):
    """Normalize presentation, not music-version or title differences.

    Never drop a whole bracket: e.g. (Official Video - Slowed) still says
    Slowed. Exact normalized title equality is deliberately conservative.
    """
    text = title.casefold()
    text = re.sub(r'\b(?:official\s+(?:(?:music|lyric|lyrics)\s+)?(?:video|audio|visualizer|visualiser|lyrics)|music\s+video|(?:lyric|lyrics)\s+video)\b', ' ', text)
    text = re.sub(r'[\[(]\s*(?:lyrics|visualizer|visualiser|audio)\s*[\])]', ' ', text)
    text = ' '.join(re.findall(r'[^\W_]+', text))
    text = re.sub(r'\b(?:speed up|speedup|spedup)\b', 'sped up', text)
    text = re.sub(r'\b(slowed|sped up) and reverb\b', r'\1 reverb', text)
    text = re.sub(r'\b(slowed|remix|extended|acoustic|instrumental|live|nightcore|edit) version\b', r'\1', text)
    text = re.sub(r'\bsped up version\b', 'sped up', text)
    return ' '.join(text.split())

def description_artist(title, description):
    """Accept only an explicit artist credit or an artist/title line matching the video title."""
    lines = [line.strip() for line in description.splitlines() if line.strip()][:12]
    for line in lines:
        # Avoid interpreting URLs, marketing text, or arbitrarily long prose as artist names.
        if len(line) > 200 or '://' in line:
            continue
        credit = re.match(r'^(?:artist|artists|performed by)\s*:\s*(.{1,100})$', line, re.I)
        if credit and normalized(credit.group(1)):
            return credit.group(1).strip()
        # YouTube's autogenerated music descriptions commonly use
        # "Song · Artist 1 · Artist 2". Require the song title to match before
        # treating any of the names as artists.
        music_credits = [part.strip() for part in re.split(r'\s*[·•]\s*', line)]
        if (len(music_credits) >= 2 and title_similarity(title, music_credits[0]) >= .9
                and all(0 < len(name) <= 100 and normalized(name) for name in music_credits[1:])):
            return ', '.join(music_credits[1:])
        parts = re.split(r'\s+[-–—]\s+', line, maxsplit=1)
        if len(parts) == 2 and len(parts[0]) <= 100 and normalized(parts[0]):
            if title_similarity(title, parts[1]) >= .85:
                return parts[0].strip()
    return None

def metadata(video):
    title = video['title'].strip()
    channel = video.get('channel', '').strip()
    if not normalized(title) or title.casefold() in ('private video', 'deleted video'):
        return None
    parts = re.split(r'\s+[-–—]\s+', title, maxsplit=1)
    # Prefer an explicit artist credit, including autogenerated music credits,
    # over an uploader or generic distributor Topic channel name.
    artist = description_artist(title, video.get('description', ''))
    if artist:
        primary = re.split(r'\s*(?:,|&|\bfeat(?:uring)?\.?\b|\bft\.?\b)', artist, maxsplit=1, flags=re.I)[0]
        if len(parts) == 2 and title_similarity(parts[0], primary) >= .8:
            return artist, parts[1]
        return artist, title
    # A named Topic channel can identify an artist, including for titles such
    # as "Song - Slowed". Generic release channels are not an artist credit.
    topic = re.fullmatch(r'(.+?)\s*-\s*Topic', channel, flags=re.I)
    if topic:
        artist = topic.group(1).strip()
        if normalized(artist) and normalized(artist) not in {'release', 'releases', 'various artists'}:
            if len(parts) == 2 and title_similarity(parts[0], artist) >= .8:
                return artist, parts[1]
            return artist, title
    if len(parts) == 2 and all(normalized(x) for x in parts):
        # Do not mistake "Song - Slowed" or "Song - Official Video" for
        # an artist/song pair when no artist credit has been found.
        suffix = normalized(parts[1])
        non_song_suffixes = {'official video', 'official music video', 'official audio', 'lyrics', 'lyric video'}
        version_words = {'slowed', 'super', 'ultra', 'sped', 'speed', 'up', 'extended',
                         'instrumental', 'remix', 'live', 'acoustic', 'reverb', 'edit', 'version'}
        only_version = bool(suffix) and set(suffix.split()).issubset(version_words)
        if suffix not in non_song_suffixes and not only_version:
            return parts[0], parts[1]
    return None

def version_signature(title):
    """Avoid mixing distinct edits, remixes, and performances of a track."""
    words = ' '.join(re.findall(r'[^\W_]+', title.casefold()))
    patterns = {
        'slowed': r'\bslowed\b',
        'sped-up': r'\b(?:sped up|spedup|speed up|speedup)\b',
        'super-slowed': r'\bsuper slowed\b',
        'ultra-slowed': r'\bultra slowed\b',
        'over-slowed': r'\bover slowed\b',
        'extra-slowed': r'\bextra slowed\b',
        'reverb': r'\breverb\b',
        'extended': r'\bextended\b',
        'remix': r'\bremix\b',
        'mix': r'\bmix\b',
        'edit': r'\bedit\b',
        'remastered': r'\bremaster(?:ed)?\b',
        '8d': r'\b8d\b',
        'chopped': r'\bchopped\b',
        'screwed': r'\bscrewed\b',
        'live': r'\blive\b',
        'acoustic': r'\bacoustic\b',
        'instrumental': r'\binstrumental\b',
        'cover': r'\bcover\b',
        'nightcore': r'\bnightcore\b',
        'radio': r'\bradio\b',
        'clean': r'\bclean\b',
        'explicit': r'\bexplicit\b',
        'karaoke': r'\bkaraoke\b',
        'demo': r'\bdemo\b',
        'acapella': r'\b(?:acapella|a cappella)\b',
        'rework': r'\brework\b',
        'original': r'\boriginal\b',
    }
    return {name for name, pattern in patterns.items() if re.search(pattern, words)}

def choose_match(artist, title, tracks):
    a, t = normalized(artist), normalized(title)
    if not a or not t:
        return None
    # Compare Spotify's credited artists against the primary credited artist,
    # not the entire "A, B & C" string as though it were one artist.
    primary_artist = re.split(r'\s*(?:,|&|\bfeat(?:uring)?\.?\b|\bft\.?\b)\s*', artist, maxsplit=1, flags=re.I)[0]
    a = normalized(primary_artist)
    if not a:
        return None
    expected_title = canonical_track_title(title)
    if not expected_title:
        return None
    matches = {}
    for track in tracks:
        if not track.get('id') or not track.get('name'):
            continue
        if version_signature(title) != version_signature(track['name']):
            continue
        if canonical_track_title(track['name']) != expected_title:
            continue
        if not any(normalized(x.get('name', '')) == a for x in track.get('artists', [])):
            continue
        matches[track['id']] = track
    # Identical metadata can describe different recordings. Without stronger
    # evidence it is safer to skip than choose one arbitrarily.
    return next(iter(matches.values())) if len(matches) == 1 else None

def choose_title_fallback(video_title, song_title, tracks, *, has_artist):
    """Looser title search, retaining version checks and rejecting close ties.

    Artist is deliberately not a hard requirement here: when metadata is poor,
    the uploader may not be the artist. This is heuristic, not audio matching.
    """
    if video_title.strip().casefold() in ('private video', 'deleted video'):
        return None
    expected = canonical_track_title(song_title)
    if len(expected) < 4:
        return None
    expected_version = version_signature(song_title)
    expected_numbers = set(re.findall(r'\b(?:\d+[a-z]*|ii|iii|iv|v)\b', expected))
    ranked = {}
    for track in tracks:
        if not isinstance(track, dict) or not track.get('id') or not track.get('name'):
            continue
        name = track['name']
        if version_signature(name) != expected_version:
            continue
        candidate = canonical_track_title(name)
        if not candidate or set(re.findall(r'\b(?:\d+[a-z]*|ii|iii|iv|v)\b', candidate)) != expected_numbers:
            continue
        # A fuzzy comparison must not swap named remixes or edited recordings.
        # Without matching the complete title there is not enough evidence.
        if expected_version & {'remix', 'mix', 'edit', 'remastered'} and candidate != expected:
            continue
        comparisons = [candidate]
        if not has_artist:
            # A video's title can contain its artist even when our metadata
            # parser could not separate them reliably.
            for artist in track.get('artists', []):
                if isinstance(artist, dict) and artist.get('name'):
                    comparisons.append(canonical_track_title(f"{artist['name']} {name}"))
        score = max(SequenceMatcher(None, expected, item).ratio() for item in comparisons)
        if score >= .86:
            previous = ranked.get(track['id'])
            if previous is None or score > previous[0]:
                ranked[track['id']] = (score, track)
    options = sorted(ranked.values(), key=lambda item: item[0], reverse=True)
    if not options or (len(options) > 1 and options[0][0] - options[1][0] < .05):
        return None
    return options[0][1]

# These words can make Spotify search overly specific; they are removed only
# for the third query and core-title comparison, never for the version check.
SEARCH_VARIANT_WORDS = {
    'slowed', 'reverb', 'extended', 'remix', 'mix', 'edit', 'remastered', 'remaster', '8d',
    'chopped', 'screwed', 'live', 'acoustic', 'instrumental', 'cover', 'nightcore',
    'radio', 'clean', 'explicit', 'karaoke', 'demo', 'acapella', 'rework', 'original',
}

def search_core(title):
    text = canonical_track_title(title)
    # Only strip modifiers when they form a recognized version phrase; a song
    # whose actual name is "Super" or "Down" must not lose those words.
    text = re.sub(r'\b(?:ultra|super|over|extra) slowed\b', ' ', text)
    text = re.sub(r'\bslowed down\b|\bsped up\b', ' ', text)
    words = text.split()
    core = [word for word in words if word not in SEARCH_VARIANT_WORDS]
    # "Slowed and Reverb" should not leave a dangling conjunction in a query.
    while core and core[-1] in ('and', 'with'):
        core.pop()
    return ' '.join(core)

def choose_detail_fallback(video, parsed, tracks):
    """Pick a unique broader-search candidate with guarded version metadata.

    Video duration includes possible intros/outros; it is used only as a loose
    plausibility check when both services provide it, not as audio proof.
    """
    source_title = parsed[1] if parsed else video['title']
    expected = canonical_track_title(source_title)
    core = search_core(source_title)
    if len(core) < 4:
        return None
    version = version_signature(source_title)
    numbers = set(re.findall(r'\b(?:\d+[a-z]*|ii|iii|iv|v)\b', expected))
    artist = None
    if parsed:
        artist = normalized(re.split(r'\s*(?:,|&|\bfeat(?:uring)?\.?\b|\bft\.?\b)', parsed[0], maxsplit=1, flags=re.I)[0])
    ranked = {}
    for track in tracks:
        if not isinstance(track, dict) or not track.get('id') or not track.get('name'):
            continue
        name = track['name']
        if version_signature(name) != version:
            continue
        candidate = canonical_track_title(name)
        if set(re.findall(r'\b(?:\d+[a-z]*|ii|iii|iv|v)\b', candidate)) != numbers:
            continue
        if version & {'remix', 'mix', 'edit', 'remastered'} and candidate != expected:
            continue
        artists = [normalized(a.get('name', '')) for a in track.get('artists', []) if isinstance(a, dict)]
        artist_match = bool(artist and artist in artists)
        candidate_core = search_core(name)
        if not candidate_core:
            continue
        # Some distributors place the same song words in a different order.
        ordered = SequenceMatcher(None, core, candidate_core).ratio()
        unordered = SequenceMatcher(None, ' '.join(sorted(core.split())), ' '.join(sorted(candidate_core.split()))).ratio()
        score = max(ordered, unordered)
        # A channel/credit may differ from Spotify's artists. Keep artist as
        # supporting evidence, not a requirement, and require a stronger title
        # match if the artists do not agree.
        if score < (.86 if artist_match else .93):
            continue
        video_duration = video.get('duration_ms')
        spotify_duration = track.get('duration_ms')
        if (isinstance(video_duration, (int, float)) and not isinstance(video_duration, bool) and video_duration > 0
                and isinstance(spotify_duration, (int, float)) and not isinstance(spotify_duration, bool) and spotify_duration > 0):
            if abs(video_duration - spotify_duration) > max(30000, video_duration * .25):
                continue
        previous = ranked.get(track['id'])
        if previous is None or score > previous[0]:
            ranked[track['id']] = (score, track)
    options = sorted(ranked.values(), key=lambda item: item[0], reverse=True)
    if not options or (len(options) > 1 and options[0][0] - options[1][0] < .05):
        return None
    return options[0][1]

def detail_search(client, video, parsed, token, earlier):
    """Search a broader core title after the two existing methods miss."""
    source_title = parsed[1] if parsed else video['title']
    core = search_core(source_title)
    if len(core) < 4:
        return None
    candidates = list(earlier)
    # Avoid repeating an identical Spotify query already made by methods 1/2.
    tried = {('', canonical_track_title(video['title']))}
    if parsed:
        tried.add((normalized(parsed[0]), canonical_track_title(parsed[1])))
    for artist in ([parsed[0], ''] if parsed else ['']):
        key = (normalized(artist), canonical_track_title(core))
        if key in tried:
            continue
        tried.add(key)
        candidates.extend(client.search(artist, core, token))
    return choose_detail_fallback(video, parsed, candidates)

def load_overrides(path):
    """Read explicitly user-selected YouTube video ID -> Spotify track ID pairs."""
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding='utf-8'))
        if not isinstance(data, dict):
            raise ValueError('not an object')
        for video_id, track_id in data.items():
            if (not isinstance(video_id, str) or not re.fullmatch(r'[A-Za-z0-9_-]{11}', video_id)
                    or not isinstance(track_id, str) or not re.fullmatch(r'[A-Za-z0-9]{22}', track_id)):
                raise ValueError('invalid ID')
        return data
    except (OSError, ValueError, TypeError) as exc:
        raise FatalError('Invalid data/track-overrides.json; expected YouTube video IDs mapped to Spotify track IDs') from exc

def load_state(path):
    if not path.exists():
        return {'version': 1, 'playlists': {}}
    try:
        data = json.loads(path.read_text(encoding='utf-8'))
        if data.get('version') != 1 or not isinstance(data.get('playlists'), dict):
            raise ValueError('invalid state format')
        return data
    except (OSError, ValueError, AttributeError) as exc:
        raise FatalError('Database file is invalid; restore it from Git history') from exc

def save_state(path, state):
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix('.tmp')
    temp.write_text(json.dumps(state, indent=2, ensure_ascii=False) + '\n', encoding='utf-8')
    temp.replace(path)

def log_text(value):
    """Keep public metadata on one short line, without control characters."""
    return ' '.join(str(value).split())[:120]

def issue_text(value, limit=600):
    """Keep untrusted video metadata on one line and within message limits."""
    text = ' '.join(str(value or '').split())
    text = ''.join(ch for ch in text if ch.isprintable())
    return text if len(text) <= limit else text[:limit - 1] + '…'

def report_issue(issues, status, video, reason, track_id=None):
    if issues is not None:
        issues.append({'status': status, 'title': issue_text(video.get('title')) or '(title unavailable)',
                       'channel': issue_text(video.get('channel')), 'video_id': video.get('id'),
                       'reason': issue_text(reason), 'track_id': track_id})

def telegram_messages(summary, issues):
    """Split at issue boundaries; Telegram allows at most 4096 UTF-16 units."""
    limit = 4000  # Leave a small margin for platform differences.
    def size(text):
        return len(text.encode('utf-16-le')) // 2
    messages = [summary]
    for issue in issues:
        lines = [f"{issue['status']}: {issue['title']}"]
        if issue['channel']:
            lines.append(f"Channel: {issue['channel']}")
        video_id = issue['video_id']
        if isinstance(video_id, str) and re.fullmatch(r'[A-Za-z0-9_-]{11}', video_id):
            lines.append(f'YouTube: https://www.youtube.com/watch?v={video_id}')
        else:
            lines.append(f"YouTube ID: {issue_text(video_id, 100) or '(unavailable)'}")
        track_id = issue['track_id']
        if isinstance(track_id, str) and re.fullmatch(r'[A-Za-z0-9]{22}', track_id):
            lines.append(f'Spotify: https://open.spotify.com/track/{track_id}')
        lines.append(f"Reason: {issue['reason']}")
        block = '\n'.join(lines)
        if size(messages[-1] + '\n\n' + block) > limit:
            messages.append('YouTube → Spotify: skip/fail details (continued)')
        messages[-1] += '\n\n' + block
    return messages

def sync(client, videos, playlist, token, state, dry_run, counts, overrides=None, issues=None):
    overrides = overrides or {}
    db = state['playlists'].setdefault(playlist, {'videos': {}, 'pending': None})
    existing = client.existing_tracks(playlist, token)  # Fail closed if we cannot check duplicates.
    planned = set()
    pending = db.get('pending')
    if pending:
        if pending['track'] in existing:
            LOG.warning('Previous uncertain add is present in Spotify; recording it')
            if not dry_run:
                db['videos'][pending['video']] = pending['track']
                db['pending'] = None
                save_state(STATE_PATH, state)
        else:
            raise FatalError('Previous add outcome is uncertain and track was not found. Check Spotify manually, then clear pending in data/sync-state.json before retrying.')
    for video in videos:
        vid = video['id']
        if vid in db['videos']:
            counts['skip'] += 1
            report_issue(issues, 'SKIP', video, 'Already recorded in the sync database', db['videos'][vid])
            LOG.info('SKIP %s: already recorded', vid)
            continue
        if video['title'].strip().casefold() in ('', 'private video', 'deleted video'):
            counts['skip'] += 1
            report_issue(issues, 'SKIP', video, 'Unavailable or missing video title')
            LOG.info('SKIP %s: unavailable or missing video title', vid)
            continue
        tid = None
        try:
            tid = overrides.get(vid)
            if tid:
                # Explicit user choice bypasses automatic metadata matching; it
                # must still follow the same duplicate and pending-write logic.
                LOG.info('MANUAL MATCH %s -> %s (user-selected; version not automatically verified)', vid, tid)
            else:
                parsed = metadata(video)
                strict_candidates = client.search(*parsed, token) if parsed else []
                track = choose_match(*parsed, strict_candidates) if parsed else None
                method = 'STRICT'
                if not track:
                    # Search the complete title if the strict method misses.
                    candidates = client.search('', video['title'], token)
                    track = choose_title_fallback(video['title'], parsed[1] if parsed else video['title'],
                                                  candidates, has_artist=bool(parsed))
                    method = 'LOOSE'
                if not track:
                    track = detail_search(client, video, parsed, token, strict_candidates + candidates)
                    method = 'DETAIL'
                if not track:
                    counts['skip'] += 1
                    report_issue(issues, 'SKIP', video, 'No confident artist/title/version match')
                    LOG.info('SKIP %s: no confident artist/title/version match (video: %s)', vid, log_text(video['title']))
                    continue
                tid = track['id']
                artist_names = ', '.join(a.get('name', '') for a in track.get('artists', []))
                LOG.info('%s MATCH %s: %s — %s', method, vid, log_text(track['name']), log_text(artist_names))
            if tid in existing:
                counts['skip'] += 1
                reason = ('Same track already planned in this dry run' if tid in planned
                          else 'Track already in Spotify playlist')
                report_issue(issues, 'SKIP', video, reason, tid)
                LOG.info('SKIP %s: %s', vid, reason)
                if not dry_run:
                    db['videos'][vid] = tid
                    save_state(STATE_PATH, state)
                continue
            if dry_run:
                counts['add'] += 1
                existing.add(tid)
                planned.add(tid)
                LOG.info('WOULD ADD %s -> %s', vid, tid)
                continue
            db['pending'] = {'video': vid, 'track': tid}
            save_state(STATE_PATH, state)
            try:
                client.add(playlist, tid, token)
            except UncertainWrite:
                raise
            except SyncError:
                db['pending'] = None
                save_state(STATE_PATH, state)
                raise
            existing.add(tid)
            db['videos'][vid] = tid
            db['pending'] = None
            save_state(STATE_PATH, state)
            counts['add'] += 1
            LOG.info('ADD %s -> %s', vid, tid)
        except FatalError as exc:
            counts['fail'] += 1
            report_issue(issues, 'FAIL', video, str(exc), tid)
            raise
        except SyncError as exc:
            counts['fail'] += 1
            report_issue(issues, 'FAIL', video, str(exc), tid)
            LOG.warning('FAIL %s: %s', vid, exc)
        except OSError:
            counts['fail'] += 1
            report_issue(issues, 'FAIL', video, 'Database file I/O error; sync stopped', tid)
            raise

def main():
    parser = argparse.ArgumentParser(description='Experimental one-way YouTube to Spotify sync')
    parser.add_argument('--dry-run', action='store_true', help='preview without writing to Spotify or the database')
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format='%(levelname)s %(message)s')
    counts = {'add': 0, 'skip': 0, 'fail': 0}
    issues = []
    result = 'SUCCESS'
    fatal_reason = None
    client = Client(0)
    try:
        delay = float(os.environ.get('REQUEST_DELAY_SECONDS', '2'))
        if delay < 0 or delay > 60 or not delay < float('inf'):
            raise ValueError('delay out of range')
        client.delay = delay
        yt = playlist_id(os.environ.get('YOUTUBE_PLAYLIST', ''), 'YouTube')
        spotify = playlist_id(os.environ.get('SPOTIFY_PLAYLIST', ''), 'Spotify')
        key = os.environ.get('YOUTUBE_API_KEY', '')
        if not key:
            raise FatalError('YOUTUBE_API_KEY is missing')
        state = load_state(STATE_PATH)
        overrides = load_overrides(OVERRIDES_PATH)
        cookie = sp_dc_from_file(os.environ.get('SPOTIFY_COOKIE_FILE', 'cookies/spotify.txt'))
        videos = client.youtube(key, yt)
        token = client.token(cookie)
        sync(client, videos, spotify, token, state, args.dry_run, counts, overrides=overrides, issues=issues)
        if counts['fail']:
            result = 'PARTIAL FAILURE'
    except (FatalError, ValueError, OSError) as exc:
        result = 'FAILED'
        if not counts['fail']:
            counts['fail'] += 1
        # Error strings are deliberately sanitized and never include HTTP response data.
        fatal_reason = str(exc) if isinstance(exc, FatalError) else 'Invalid configuration or state file I/O error'
        LOG.error('%s', fatal_reason)
    finally:
        summary = f"YouTube → Spotify {'DRY RUN' if args.dry_run else 'SYNC'}: {result}\n{'Would add' if args.dry_run else 'Added'}: {counts['add']} | Skipped: {counts['skip']} | Failed: {counts['fail']}"
        if fatal_reason:
            summary += f'\nRun stopped: {issue_text(fatal_reason)}'
        LOG.info(summary)
        for message in telegram_messages(summary, issues):
            client.telegram(os.environ.get('TELEGRAM_BOT_TOKEN'), os.environ.get('TELEGRAM_CHAT_ID'), message)
    return 0 if result == 'SUCCESS' else 1

if __name__ == '__main__':
    raise SystemExit(main())
