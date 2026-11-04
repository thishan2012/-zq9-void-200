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
import unicodedata
from difflib import SequenceMatcher
from urllib.parse import parse_qs, urlencode, urlparse, urlsplit, urlunsplit

import requests

LOG = logging.getLogger('sync')
UA = 'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/131.0 Safari/537.36'
STATE_PATH = Path('data/sync-state.json')
OVERRIDES_PATH = Path('data/track-overrides.json')
BATCH_MAX = 100  # Spotify accepts at most 100 URIs per playlist add request.
SEARCH_CACHE_MAX = 5000  # cap on cached search results per run (memory guard).
TELEGRAM_MAX_MESSAGES = 6  # hard cap on messages per run (spam / rate-limit guard).
MAX_REPORTED_FAILURES = 2  # a failing song is logged at most twice, then goes quiet.
MATCHER_VERSION = 6  # bump when matching rules change: skipped songs get one more try.
# Real reasons that are worth remembering in the database.
SKIP_REASONS = ('No confident artist/title/version match', 'Unavailable or missing video title',
                'Same track already planned in this run', 'Same track already planned in this dry run')
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

def backoff_seconds(response, attempt):
    """Honour Retry-After, otherwise exponential backoff capped at 60 seconds."""
    value = (getattr(response, 'headers', None) or {}).get('Retry-After')
    if value:
        try:
            return max(1.0, min(float(value), 120.0))
        except (TypeError, ValueError):
            pass
    return min(60.0, 5.0 * (2 ** (attempt - 1)))


class Client:
    def __init__(self, delay):
        self.http = requests.Session()
        self.http.headers.update({'User-Agent': UA})
        self.delay = delay
        self.spotify_backend = None
        self.partner_proxy = True
        self.retries = 3

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
        # Read-only requests are retried after HTTP 429/5xx, honouring Retry-After.
        # Writes are never retried: an add may already have been applied.
        attempt = 0
        while True:
            if self.delay:
                time.sleep(self.delay)
            try:
                response = self.http.request(method, url, timeout=30, **kwargs)
            except requests.RequestException as exc:
                if write:
                    raise UncertainWrite('Spotify add request had a network error; outcome unknown. Check the playlist before clearing the pending entry.') from exc
                raise (FatalError if fatal else SyncError)(f'{label}: network error during {method} request') from exc
            if not write and (response.status_code == 429 or response.status_code >= 500) and attempt < self.retries:
                attempt += 1
                wait = max(self.delay, backoff_seconds(response, attempt))
                LOG.warning('%s: HTTP %s; retrying in %.0fs (attempt %d/%d)', label, response.status_code, wait, attempt, self.retries)
                time.sleep(wait)
                continue
            break
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

    def youtube_playlist(self, key, playlist):
        """Read the playlist's own metadata: title, channel and public link."""
        data = self.request('GET', 'https://www.googleapis.com/youtube/v3/playlists',
                            params={'part': 'snippet', 'id': playlist, 'key': key},
                            fatal=True, label='YouTube playlist name')
        items = data.get('items') if isinstance(data, dict) else None
        if not isinstance(items, list) or not items:
            raise FatalError('YouTube playlist not found (or it is private); check YOUTUBE_PLAYLIST')
        snippet = items[0].get('snippet') or {}
        if not isinstance(snippet, dict):
            snippet = {}
        return {'id': playlist,
                'title': log_text(snippet.get('title') or '') or 'YouTube playlist',
                'channel': log_text(snippet.get('channelTitle') or ''),
                'url': f'https://www.youtube.com/playlist?list={playlist}'}

    def youtube(self, key, playlist):
        videos = []
        page = None
        pages = 0
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
            pages += 1
            LOG.info('YouTube played items read: page %d, %d video(s) so far', pages, len(videos))
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
        LOG.info('YouTube playlist loaded: %d item(s) in %d page(s), %d unique video(s)',
                 len(videos), pages, len({video['id'] for video in videos}))
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
            # Ranking evidence for the looser steps (never shown in the report).
            playcount = item.get('playcount')
            if isinstance(playcount, (int, float)) and playcount > 0:
                result['popularity'] = playcount
            album = item.get('albumOfTrack') or {}
            album_name = album.get('name') if isinstance(album, dict) else None
            if isinstance(album_name, str) and album_name:
                result['album'] = album_name
            results.append(result)
        return results

    def add(self, playlist, track, token):
        self.add_batch(playlist, [track], token)

    def add_batch(self, playlist, tracks, token):
        """Add up to BATCH_MAX tracks in one request (Spotify allows 100 per call)."""
        uris = [f'spotify:track:{track}' for track in tracks]
        if not uris or len(uris) > BATCH_MAX:
            raise FatalError('Spotify batch add size is out of range')
        if self.spotify_backend == 'rest':
            self.request('POST', f'https://api.spotify.com/v1/playlists/{playlist}/items',
                    headers={'Authorization': f'Bearer {token}'}, json={'uris': uris},
                    write=True, proxy=True, label='Spotify proxied playlist add')
            return
        if self.spotify_backend != 'web-player':
            raise FatalError('Spotify backend was not initialized')
        data = self.gql('addToPlaylist', {'playlistUri': f'spotify:playlist:{playlist}',
                  'playlistItemUris': uris,
                  'newPosition': {'moveType': 'BOTTOM_OF_PLAYLIST', 'fromUid': None},
                  'interactionId': None}, token, write=True)
        result = data.get('addItemsToPlaylist')
        if not isinstance(result, dict) or result.get('__typename') != 'AddItemsToPlaylistPayload':
            raise UncertainWrite('Spotify web-player add did not confirm success; check the playlist before clearing pending')

    def telegram(self, token, chat, message, quiet=False):
        """Send one message (split if needed). Returns True when Telegram accepted it."""
        if not token or not chat:
            if not quiet:
                LOG.warning('Telegram not configured; summary only in Actions log')
            return False
        delivered = True
        for chunk in utf16_chunks(message):
            try:
                r = self.http.post(f'https://api.telegram.org/bot{token}/sendMessage',
                                   json={'chat_id': chat, 'text': chunk, 'disable_web_page_preview': True},
                                   timeout=20)
                if not r.ok:
                    if not quiet:
                        LOG.warning('Telegram delivery failed (HTTP %s)', r.status_code)
                    delivered = False
            except requests.RequestException:
                if not quiet:
                    LOG.warning('Telegram delivery failed (network error)')
                delivered = False
        return delivered

    def telegram_many(self, token, chat, messages, max_messages=TELEGRAM_MAX_MESSAGES):
        """Send the report as a handful of messages, never as a burst.

        Whole messages are packed together (never cut in half) up to the
        per-message limit, and one run sends at most ``max_messages`` messages.
        If there would be more, the tail is summarised and the detail stays in
        the Actions log - several small messages in a row look like spam and can
        get a bot rate limited or reported.
        """
        if not token or not chat:
            LOG.warning('Telegram not configured; report only in the Actions log')
            return False
        limit = 4000

        def size(text):
            return len(text.encode('utf-16-le')) // 2

        packets, current = [], ''
        for message in [chunk for message in messages for chunk in utf16_chunks(message or '', limit)]:
            candidate = f'{current}\n\n{message}' if current else message
            if current and size(candidate) > limit:
                packets.append(current)
                current = message
            else:
                current = candidate
        if current:
            packets.append(current)
        if len(packets) > max_messages:
            dropped = len(packets) - (max_messages - 1)
            packets = packets[:max_messages - 1] + [
                f'… {dropped} more message(s) omitted to keep this run at {max_messages} '
                f'messages. Full per-song log: the Actions run log.']
        LOG.info('Telegram: sending %d message(s)', len(packets))
        for index, packet in enumerate(packets, start=1):
            if not self.telegram(token, chat, packet, quiet=True):
                LOG.warning('Telegram delivery stopped at message %d/%d', index, len(packets))
                return False
        return True


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

# ---------------------------------------------------------------- wording --
# Words that describe an upload, never the song itself ("HDN | VIRAL PHONK").
MARKETING_WORDS = {
    'viral', 'tiktok', 'trending', 'phonk', 'funk', 'slowed', 'reverb', 'sped', 'speed',
    'nightcore', 'bass', 'boosted', 'edit', 'version', 'official', 'music', 'video', 'audio',
    'lyrics', 'lyric', 'visualizer', 'tropical', 'phonksongs', 'hd', 'hq', '4k',
}
# Upload labels only. Version words (slowed, reverb, sped up …) are NOT tags: a
# "(Slowed + Reverb)" bracket names a different recording and must be kept.
# Words an uploader adds to its own name: "HDN Music", "HDN Official".
UPLOAD_SUFFIX_WORDS = {'music', 'official', 'records', 'label', 'channel', 'topic', 'tv'}
TAG_WORDS = {'official', 'video', 'audio', 'lyric', 'lyrics', 'visualizer', 'visualiser',
             'music', 'phonk', 'funk', 'tropical', 'viral', 'tiktok', 'trending',
             'phonksongs', 'hd', 'hq', '4k'}
# "A x B", "A × B", "A, B", "A & B", "A + B", "A feat. B", "A ft. B", "A / B".
# A lone "x" only counts between two words ("WUYS x KIT"), never as a name by
# itself ("DJ X" is one artist, not "DJ" and "").
COLLAB_SEPARATOR = re.compile(r'\s+(?:x|×)\s+|\s*(?:,|&|\+|\bfeat(?:uring)?\.?\b|\bft\.?\b|/)\s*', re.I)
# "… (Slowed)", "… [Super Slowed]" at the end of the song half of a title.
VERSION_TAG_TAIL = re.compile(r'[\[(]\s*(?:super |ultra |over |extra )?'
                              r'(?:slowed|sped up|speed up|reverb|nightcore)\s*[\])]\s*$', re.I)

def tag_words(text):
    """True when a bracketed block is a tag (all its words are upload labels)."""
    words = normalized(text).split()
    return bool(words) and all(word in TAG_WORDS for word in words)

def drop_tags(text):
    """Remove trailing upload tags: "HUEGO [TROPICAL PHONK\\FUNK]" -> "HUEGO"."""
    while True:
        match = re.search(r'\s*[\[(]\s*([^\])}]*?)\s*[\])}]\s*$', text)
        if not match or not tag_words(match.group(1)):
            return text.strip()
        text = text[:match.start()].strip()

def strip_marketing(title):
    """Cut uploader marketing off a title: "HDN | VIRAL PHONK" -> "HDN".

    Only whole words from a fixed list are removed, and only after a separator,
    so a song whose real name contains "Funk" or "Phonk" keeps it.
    """
    text = title.strip()
    match = re.match(r'^(.+?)\s*[|~]\s*(.+)$', text)
    if match:
        tail = normalized(match.group(2)).split()
        if tail and all(word in MARKETING_WORDS for word in tail):
            text = match.group(1).strip()
    return drop_tags(text)

def is_domain_like(text):
    """True when a dot is really part of a name ("A.R.T.", "Mr.Kitty", "kud.ai").

    Two letters on either side are treated as a file extension ("Signals.yt"),
    not as a name, so a plain word never counts as a domain.
    """
    for left, right in re.findall(r'(\w)\.(\w)', text):
        if not (len(left) <= 2 and len(right) <= 2):
            return True
    return False


def artist_candidates(credit):
    """Split an artist credit into individual names.

    "A, B, C", "A & B", "A x B", "A × B", "A + B", "A feat. B" and "A / B" all
    become separate names, so a collab credit can match Spotify's artist list.
    """
    names = []
    for part in COLLAB_SEPARATOR.split(credit or ''):
        part = part.strip(' ,.')
        if part.endswith('.') and not is_domain_like(part):
            # "Mr.Kitty ." / "Signals.yt" pasted from a filename: the dot is not
            # part of the artist name.
            part = part.rstrip(' .')
        if part and normalized(part) and normalized(part) not in {'x', 'ft', 'feat'}:
            names.append(part)
    return names

def is_collab_credit(credit):
    """True when the text looks like more than one artist name."""
    return len(artist_candidates(credit)) > 1

def is_artist_only_part(text):
    """True when a dash-separated part is artists alone, e.g. "WUYS x KIT"."""
    words = normalized(text).split()
    return bool(words) and is_collab_credit(text) and not all(word in MARKETING_WORDS for word in words)

def split_credit_title(title):
    """Split "Song || Artists" / "Artists ~ Song" into (song, artists) or None."""
    for separator in ('||', '~'):
        if separator not in title:
            continue
        left, right = (drop_tags(part.strip(' |~-')) for part in title.split(separator, 1))
        if not left or not right:
            continue
        if is_artist_only_part(right) and not is_artist_only_part(left):
            return strip_marketing(left), right
        if is_artist_only_part(left) and not is_artist_only_part(right):
            return strip_marketing(right), left
    return None

def canonical_track_title(title):
    """Normalize presentation, not music-version or title differences.

    Version words are kept (a Slowed edit is a different recording), while
    upload labels are removed:
      "Song (Official Video)"            -> "song"
      "Song - Slowed"                    -> "song"          (the version is read
                                                            by version_signature)
      "CORTA NO SALÃO (Slowed) [VIDEO]"  -> "corta no salao slowed"
      "HDN | VIRAL PHONK"                -> "hdn"            (marketing suffix)
    """
    text = title.casefold()
    text = re.sub(r'\b(?:official\s+(?:(?:music|lyric|lyrics)\s+)?(?:video|audio|visualizer|visualiser|lyrics)|music\s+video|(?:lyric|lyrics)\s+video)\b', ' ', text)
    text = re.sub(r'[\[(]\s*(?:lyrics|visualizer|visualiser|audio)\s*[\])]', ' ', text)
    text = ' '.join(re.findall(r'[^\W_]+', text))
    # Upload tags ("[ TROPICAL PHONK\FUNK ]", "[ PHONKSONGS ]") are not the song.
    text = re.sub(r'[\[({]\s*([^\])}]*?)\s*[\])}]',
                  lambda match: ' ' if tag_words(match.group(1)) else match.group(0), text)
    text = re.sub(r'\b(?:speed up|speedup|spedup)\b', 'sped up', text)
    # "Slowed + Reverb" and "Slowed and Reverb" are the same edit: the sign is
    # not part of the name, the words are.
    text = re.sub(r'\b(slowed|sped up|reverb) (?:and|\+) (slowed|sped up|reverb)\b',
                  lambda match: ' '.join(dict.fromkeys([match.group(1), match.group(2)])), text)
    text = re.sub(r'\b(slowed|remix|extended|acoustic|instrumental|live|nightcore|edit) version\b', r'\1', text)
    text = re.sub(r'\bsped up version\b', 'sped up', text)
    # "Song - Slowed" says it is the slowed version, not that the name ends there.
    text = re.sub(r'\s+-\s+(?:super |ultra |over |extra )?(?:slowed|sped up|reverb|nightcore)$', ' ', text)
    # A featured credit belongs to the artist field (Spotify lists it there),
    # but the featured name itself stays: it is part of the song's identity.
    text = re.sub(r'[\[(]\s*(?:feat(?:uring)?|ft)\.?\s+', ' ', text)
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
        parts = re.split(r'\s+[-–—]\s*', line, maxsplit=1)
        if len(parts) == 2 and len(parts[0]) <= 100 and normalized(parts[0]):
            if title_similarity(title, parts[1]) >= .85:
                return parts[0].strip()
    return None

# Polish marks that look like ASCII letters but are not ("Ł" as "L").
POLISH_MARKS = str.maketrans({'ł': 'l', 'Ł': 'L', 'ø': 'o', 'Ø': 'O', 'đ': 'd', 'Đ': 'D',
                              'ß': 'ss', 'æ': 'ae', 'Æ': 'AE', 'œ': 'oe', 'Œ': 'OE'})

def ascii_fold(text):
    """Fold accents/marks so "CORTA NO SALÃO" and "CORTA NO SALAO" are equal."""
    text = str(text).translate(POLISH_MARKS)
    decomposed = unicodedata.normalize('NFKD', text)
    return ''.join(char for char in decomposed if not unicodedata.combining(char))

def channel_names(parsed, video):
    """Artist names we can also try as a search term, most specific first."""
    names = []
    if parsed:
        names.extend(artist_candidates(parsed[0]))
    # An uploader's own name can be the artist credit the title does not carry.
    names.extend(artist_candidates(video.get('channel', '')))
    topic = re.fullmatch(r'(.+?)\s*-\s*Topic', video.get('channel', ''), flags=re.I)
    if topic:
        names.append(topic.group(1).strip())
    # An uploader often signs the name with a glyph: "HDN🎹", "HDN Music". The
    # search term must be the plain form, "HDN" - the decorated name is not a
    # name Spotify knows.
    names = [plain_name(name) or name for name in names]
    seen, ordered = set(), []
    for name in names:
        key = normalized(name)
        if key and key not in seen and not generic_channel(key):
            seen.add(key)
            ordered.append(name.strip())
    return ordered

def generic_channel(text):
    """True for release/compilation pages: "Release", "Releases", "Various Artists".

    These are channels, not artists, so they must never become a search term.
    """
    words = set(normalized(text).split())
    return (not words or 'release' in words or 'releases' in words
            or words.issubset(TAG_WORDS | {'topic', 'records', 'label'}))

def plain_name(name):
    """The bare word of an uploader name: "HDN🎹" -> "HDN", "Espato." -> "Espato".

    Decoration (emoji, ♪, ★) and the upload suffix ("HDN Music", "HDN - Topic")
    are dropped. A name that has nothing left is not used as a search term.
    """
    text = unicodedata.normalize('NFKC', name or '')
    text = re.sub(r'\s*-\s*topic$', '', text, flags=re.I)
    text = ''.join(ch for ch in text if ch.isalnum() or ch.isspace() or ch in ".'-&")
    text = ' '.join(text.split()).strip(" .'-&")
    tail = normalized(text).split()
    while len(tail) > 1 and tail[-1] in UPLOAD_SUFFIX_WORDS:
        tail.pop()
    if len(tail) < len(normalized(text).split()):
        text = re.sub(r'\s+\S+$', '', text) if len(normalized(text).split()) - len(tail) == 1 else text
    return text.strip(" .'-&")

def with_featured(artist, title):
    """Move a "(feat. X)" credit from the title to the artist string."""
    found = re.search(r'[\[(]\s*(?:feat(?:uring)?|ft)\.?\s+([^\])}]*)[\])}]', title, re.I)
    if not found or not normalized(found.group(1)):
        return artist, title
    return f'{artist}, {found.group(1).strip()}', title

def metadata(video):
    """Guess (artist credit, song title) from a YouTube title.

    Uploaders write "Artist - Song" just as often as "Song - Artist", so both
    orders are recognised: the artist side is the one that is only names
    ("WUYS x KIT", "DJ ALEX, MC LOCKED"), or the side without a version tag.
    """
    title = video['title'].strip()
    channel = video.get('channel', '').strip()
    if not normalized(title) or title.casefold() in ('private video', 'deleted video'):
        return None
    # "Song || Artists" and "Artists ~ Song" both appear in phonk uploads.
    credited_split = split_credit_title(title)
    if credited_split:
        song, credit = credited_split      # metadata() returns (artist, title)
        return credit, song
    parts = re.split(r'\s+[-–—]\s+', title, maxsplit=1)
    # Prefer an explicit artist credit, including autogenerated music credits,
    # over an uploader or generic distributor Topic channel name.
    artist = description_artist(title, video.get('description', ''))
    if artist:
        primary = artist_candidates(artist)[0] if artist_candidates(artist) else artist
        if len(parts) == 2 and title_similarity(parts[0], primary) >= .8:
            return artist, parts[1]
        return artist, title
    # A named Topic channel can identify an artist, including for titles such
    # as "Song - Slowed". Generic release channels are not an artist credit.
    topic = re.fullmatch(r'(.+?)\s*-\s*Topic', channel, flags=re.I)
    if topic:
        # A "… - Topic" channel is autogenerated from a label's release, so the
        # part before "- Topic" *is* the artist - even a generic one such as
        # "Release", where the video title ("Song (Ultra Slowed)") carries no
        # credit at all. A named channel is a stronger hint than "no credit".
        artist = topic.group(1).strip()
        if normalized(artist) and normalized(artist) not in {'release', 'releases', 'various artists'}:
            if len(parts) == 2 and title_similarity(parts[0], artist) >= .8:
                return artist, parts[1]
            return artist, title
        # "Release - Topic" is a compilation: it says nothing about the artist,
        # so fall through and let the title speak for itself.
    if len(parts) == 2 and all(normalized(x) for x in parts):
        # Do not mistake "Song - Slowed" or "Song - Official Video" for
        # an artist/song pair when no artist credit has been found.
        suffix = normalized(parts[1])
        non_song_suffixes = {'official video', 'official music video', 'official audio', 'lyrics', 'lyric video'}
        version_words = {'slowed', 'super', 'ultra', 'sped', 'speed', 'up', 'extended',
                         'instrumental', 'remix', 'live', 'acoustic', 'reverb', 'edit', 'version'}
        only_version = bool(suffix) and set(suffix.split()).issubset(version_words)
        if suffix in non_song_suffixes or only_version:
            return None
        if is_artist_only_part(parts[1]) or VERSION_TAG_TAIL.search(parts[0]):
            # "QUERO AMOR - SXYGX x FYU", "MONTAGEM MANADO (Slowed) - IXZIYOL"
            return parts[1], strip_marketing(parts[0])
        return with_featured(parts[0], parts[1])
    # "FUNK TONTO (feat. Mc Ombrinho) [Slowed]": no dash, but the feat. credit
    # says who the artists are.
    found = re.search(r'[\[(]\s*(?:feat(?:uring)?|ft)\.?\s+([^\])}]*)[\])}]', title, re.I)
    if found and normalized(found.group(1)):
        return found.group(1).strip(), title
    # No credit at all (a lyrics upload, or a title that is only the song). The
    # channel is then the best artist hint there is, and the title is the song.
    if title_only_channel(channel):
        return None
    return channel, title

def title_only_channel(channel):
    """Generic upload channels are not an artist credit."""
    words = set(normalized(channel).split())
    return (not words or words.issubset(TAG_WORDS | {'topic', 'release', 'releases', 'music', 'records',
                                                     'label', 'vibes', 'phonk', 'funk', 'slowed', 'edit'}))

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

SLOWED_LADDER = {'slowed': 0, 'super-slowed': 1, 'ultra-slowed': 2, 'over-slowed': 2, 'extra-slowed': 2}

def version_tokens(title):
    """Version words as they appear, plus the slowed family they belong to.

    "super slowed" yields {'super-slowed', 'slowed'}: two uploads agree when the
    raw markers are equal, or when both sit in the same slowed family.
    """
    found = version_signature(title)
    for name in ('super-slowed', 'ultra-slowed', 'over-slowed', 'extra-slowed'):
        if name in found:
            found.add('slowed')
    return found

def versions_agree(a, b):
    """True when two titles describe the same edit (see version_tokens)."""
    return version_tokens(a) == version_tokens(b)

def upgraded_edit(a, b):
    """True when one side is a harder slowed edit of the same song.

    Spotify often carries only the harder edit ("VOCE NA MIRA - Ultra Slowed")
    while the video says "Super Slowed". Same song, same family, one step up the
    slowed ladder - a better match than skipping it. Only the looser methods use
    this, and a remix/reverb/extended edit is never swapped for another one.
    """
    left, right = version_signature(a), version_signature(b)
    if not left or not right or (left | right) - set(SLOWED_LADDER):
        return False
    steps_left = {SLOWED_LADDER[x] for x in left if x in SLOWED_LADDER}
    steps_right = {SLOWED_LADDER[y] for y in right if y in SLOWED_LADDER}
    if not steps_left or not steps_right:
        return False
    step_a, step_b = max(steps_left), max(steps_right)
    if step_a == step_b:
        return True
    # Uploaders use Super and Ultra interchangeably: both mean "harder than
    # slowed", so one of those two labels may stand in for the other.
    return {step_a, step_b} == {1, 2}

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

DRY_STATE = {}

def save_skip_changes(state, dry_run):
    """Skip/failure bookkeeping: saved at once in a live run, at the end in a dry run."""
    if dry_run:
        DRY_STATE[STATE_PATH] = state
    else:
        save_state(STATE_PATH, state)

def save_deferred(dry_run):
    """Write the bookkeeping gathered during a dry run, so the next run goes quiet."""
    if not dry_run:
        return
    for path, state in list(DRY_STATE.items()):
        save_state(path, state)
    DRY_STATE.clear()

def failures(db):
    """video id -> number of times a song reported FAIL (capped per run later)."""
    value = db.get('failures')
    return value if isinstance(value, dict) else {}

def record_failure(db, video_id):
    """Count one failed attempt in the database (any type is tolerated)."""
    counts = failures(db)
    tried = counts.get(video_id)
    tried = tried if isinstance(tried, int) and tried > 0 else 0
    counts[video_id] = tried + 1
    db['failures'] = counts
    return counts[video_id]

def is_retired(db, video_id):
    """True when a song failed too many times: not retried, not reported."""
    return failures(db).get(video_id, 0) >= MAX_REPORTED_FAILURES

def remember_skip(db, video):
    """Save a real skip in the database so it is never searched or reported again."""
    items = db.get('skipped')
    items = items if isinstance(items, dict) else {}
    entry = {'title': log_text(video.get('title'))}
    if video.get('channel'):
        entry['channel'] = log_text(video.get('channel'))
    items[video['id']] = entry
    db['skipped'] = items

def log_text(value):
    """Keep public metadata on one short line, without control characters."""
    return ' '.join(str(value).split())[:120]

def issue_text(value, limit=600):
    """Keep untrusted video metadata on one line and within message limits."""
    text = ' '.join(str(value or '').split())
    text = ''.join(ch for ch in text if ch.isprintable())
    return text if len(text) <= limit else text[:limit - 1] + '…'

def report_issue(issues, status, video, reason, track_id=None, method=None, quiet=False):
    """Record one outcome. quiet=True keeps it out of the Telegram reports."""
    if issues is not None:
        issues.append({'status': status, 'title': issue_text(video.get('title')) or '(title unavailable)',
                       'channel': issue_text(video.get('channel')), 'video_id': video.get('id'),
                       'reason': issue_text(reason), 'track_id': track_id, 'method': method,
                       'quiet': quiet})

def utf16_chunks(text, limit=4000):
    """Split plain text on line boundaries so Telegram limits are never exceeded."""
    chunks, current = [], ''
    for line in str(text).split('\n'):
        while len(line.encode('utf-16-le')) // 2 > limit:
            # A single over-long line: cut it without splitting a surrogate pair.
            cut = len(line)
            while cut > 1 and len(line[:cut].encode('utf-16-le')) // 2 > limit:
                cut -= 1
            if current:
                chunks.append(current)
                current = ''
            chunks.append(line[:cut])
            line = line[cut:]
        candidate = f'{current}\n{line}' if current else line
        if len(candidate.encode('utf-16-le')) // 2 > limit:
            chunks.append(current)
            current = line
        else:
            current = candidate
    if current:
        chunks.append(current)
    return [chunk for chunk in chunks if chunk.strip()]


def summary_message(summary, events):
    """One compact message: the counts plus why songs were skipped, no song list.

    Songs that were already synced or already in the playlist are not counted
    and not listed here - they only live in the database.
    """
    reasons = {}
    for event in events:
        if event['status'] == 'ADD' or event['status'] == 'WOULD ADD' or event.get('quiet'):
            continue
        reasons[event['reason']] = reasons.get(event['reason'], 0) + 1
    lines = [summary]
    if reasons:
        lines += ['', 'Why songs were skipped:']
        lines += [f'  • {number} × {reason}'
                  for reason, number in sorted(reasons.items(), key=lambda item: -item[1])]
    lines += ['', 'Per-song details follow.', 'Full log: the Actions run log.']
    return '\n'.join(lines)


def activity_messages(header, events, limit=4000):
    """Compact per-song log for Telegram: one short block per reported song.

    Two short lines per song keep a 200-song run inside a couple of Telegram
    messages, so the bot never fires a burst of small messages.
    """
    def size(text):
        return len(text.encode('utf-16-le')) // 2

    messages = [header]
    for event in events:
        if event.get('quiet'):
            # Already synced / already in the playlist: database only.
            continue
        bits = []
        video_id = event.get('video_id')
        if isinstance(video_id, str) and re.fullmatch(r'[A-Za-z0-9_-]{11}', video_id):
            bits.append(f'youtu.be/{video_id}')
        if event.get('method'):
            bits.append(event['method'])
        track_id = event.get('track_id')
        if isinstance(track_id, str) and re.fullmatch(r'[A-Za-z0-9]{22}', track_id):
            bits.append(f'open.spotify.com/track/{track_id}')
        if event['status'] not in ('ADD', 'WOULD ADD'):
            # For a successful add the reason is the same sentence every time;
            # the status already says it.
            bits.append(event['reason'])
        block = f"#{event['n']} {event['status']}: {event['title']}"
        if bits:
            block += ' — ' + ' · '.join(bits)
        if size(block) + 2 > limit:
            # A single enormous block (only possible with 150+ events) would
            # otherwise be cut; keep it whole as its own message instead.
            messages.append(block[:limit])
            messages.append(header + ' (continued)')
            continue
        if size(messages[-1]) > len(header) + 1 and size(messages[-1] + '\n\n' + block) > limit:
            messages.append(header + ' (continued)')
        messages[-1] += '\n\n' + block
    return messages


def telegram_messages(summary, issues):
    """Split at issue boundaries; Telegram allows at most 4096 UTF-16 units."""
    limit = 4000  # Leave a small margin for platform differences.
    def size(text):
        return len(text.encode('utf-16-le')) // 2
    messages = [summary]
    for issue in issues:
        if issue['status'] in ('ADD', 'WOULD ADD') or issue.get('quiet'):
            # Successful additions only appear in the per-song log.
            continue
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

def pending_items(db):
    """Read the pending write record, accepting the older single-item format."""
    pending = db.get('pending')
    if not pending:
        return []
    items = pending.get('items')
    if isinstance(items, list):
        return [i for i in items if isinstance(i, dict) and isinstance(i.get('track'), str)]
    if isinstance(pending.get('track'), str):
        return [{'video': pending.get('video'), 'track': pending['track']}]
    raise FatalError('Invalid pending entry in data/sync-state.json; inspect it manually')


def flush_batch(client, playlist, token, state, db, queue, chunk_size, counts, issues):
    """Send the head of the queue as one Spotify request, then persist the result."""
    chunk = queue[:chunk_size]
    tracks = [item['track'] for item in chunk]
    db['pending'] = {'items': [{'video': i['video'], 'track': i['track']} for i in chunk]}
    save_state(STATE_PATH, state)
    try:
        if hasattr(client, 'add_batch'):
            client.add_batch(playlist, tracks, token)
        else:  # duck-typed clients that only expose single-track adds
            for track in tracks:
                client.add(playlist, track, token)
    except UncertainWrite as exc:
        # The batch may have been applied (fully or partly). Report every item
        # in it, leave pending set, and stop: never retry an ambiguous write.
        for item in chunk:
            counts['fail'] += 1
            record_failure(db, item['video'])
            report_issue(issues, 'FAIL', item['meta'], str(exc), item['track'], item.get('method'))
        save_skip_changes(state, False)
        raise
    except SyncError as exc:
        # A definite rejection means nothing was written; clear pending so the
        # next run can retry these tracks instead of stopping the whole sync.
        db['pending'] = None
        for item in chunk:
            tried = record_failure(db, item['video'])
            counts['fail'] += 1
            if tried >= MAX_REPORTED_FAILURES:
                # Second (last) time: this is the final message this song gets.
                report_issue(issues, 'FAIL', item['meta'], f'{exc} (last time logged; retried silently from now on)',
                             item['track'])
            else:
                report_issue(issues, 'FAIL', item['meta'], f'{exc} (this will be logged once more, then go quiet)',
                             item['track'])
            LOG.warning('FAIL %s: %s (attempt %d)', item['video'], exc, tried)
        save_state(STATE_PATH, state)
    else:
        for item in chunk:
            db['videos'][item['video']] = item['track']
            failures(db).pop(item['video'], None)
            counts['add'] += 1
            report_issue(issues, 'ADD', item['meta'], 'Added to Spotify', item['track'], item.get('method'))
            LOG.info('ADD %s -> %s', item['video'], item['track'])
        db['pending'] = None
        save_state(STATE_PATH, state)
    del queue[:len(chunk)]


def sync(client, videos, playlist, token, state, dry_run, counts, overrides=None, issues=None,
         batch_size=BATCH_MAX):
    overrides = overrides or {}
    batch_size = max(1, min(int(batch_size or BATCH_MAX), BATCH_MAX))
    db = state['playlists'].setdefault(playlist, {'videos': {}, 'pending': None})
    existing = client.existing_tracks(playlist, token)  # Fail closed if we cannot check duplicates.
    planned = set()
    queued = set()
    seen = set()
    queue = []
    fatal = None
    if state.get('matcher') != MATCHER_VERSION:
        # The matching rules changed (better patterns / a new release): give the
        # remembered skips one more try instead of hiding them forever. Stamped in
        # memory only; it is written with the next database save, so a run that
        # changes nothing still touches no file.
        previous = state.get('matcher')
        retried = 0
        for other in state['playlists'].values():
            if isinstance(other, dict) and other.pop('skipped', None):
                retried += 1
        state['matcher'] = MATCHER_VERSION
        if retried:
            save_skip_changes(state, dry_run)
            LOG.info('Matching rules v%s -> v%s: previously skipped songs will be tried once more',
                     previous or '?', MATCHER_VERSION)
    saved_skips = db.get('skipped')
    saved_skips = saved_skips if isinstance(saved_skips, dict) else {}
    # Explain mode (--save-explain): keep what each song's search actually returned.
    evidence = {}
    if getattr(client, 'keep_evidence', False) and isinstance(state, dict):
        evidence = state.get('evidence')
        if not isinstance(evidence, dict):
            evidence = state['evidence'] = {}
    for item in pending_items(db):
        if item['track'] not in existing:
            raise FatalError('Previous add outcome is uncertain and the track was not found. Check Spotify manually, then clear pending in data/sync-state.json before retrying.')
    if db.get('pending'):
        LOG.warning('Previous uncertain add is present in Spotify; recording it')
        if not dry_run:
            for item in pending_items(db):
                if isinstance(item.get('video'), str):
                    db['videos'][item['video']] = item['track']
            db['pending'] = None
            save_state(STATE_PATH, state)
    for video in videos:
        vid = video['id']
        if vid in db['videos']:
            # Already synced: it lives in the database, so nothing to report and
            # nothing to count - it is not a skip with a reason.
            LOG.info('SYNCED %s: already in the database (not counted, not reported)', vid)
            continue
        if vid in saved_skips and vid not in overrides:
            # Already reported before with a real reason: remembered in the
            # database, so it is never searched or logged again. A manual
            # override in data/track-overrides.json always wins.
            LOG.info('SYNCED %s: already logged as skipped (not counted, not reported)', vid)
            continue
        if vid in seen:
            # The same video appears twice in the YouTube playlist: also not an
            # error, just saved once.
            LOG.info('SYNCED %s: duplicate video in the YouTube playlist (not counted, not reported)', vid)
            continue
        seen.add(vid)
        if vid not in overrides and is_retired(db, vid):
            # Failed twice already: not searched, not retried, not reported.
            # A manual match in data/track-overrides.json is still honoured.
            LOG.info('SYNCED %s: gave up after %d failure(s) (not counted, not reported)',
                     vid, failures(db).get(vid, 0))
            continue
        if video['title'].strip().casefold() in ('', 'private video', 'deleted video'):
            counts['skip'] += 1
            report_issue(issues, 'SKIP', video, 'Unavailable or missing video title')
            remember_skip(db, video)
            save_skip_changes(state, dry_run)
            LOG.info('SKIP %s: unavailable or missing video title (saved; not searched again)', vid)
            continue
        tid = None
        method = None
        try:
            tid = overrides.get(vid)
            if tid:
                method = 'MANUAL'
                # Explicit user choice bypasses automatic metadata matching; it
                # must still follow the same duplicate and pending-write logic.
                LOG.info('MANUAL MATCH %s -> %s (user-selected; version not automatically verified)', vid, tid)
            else:
                parsed = metadata(video)
                step_state = {}
                strict_candidates = client.search(*parsed, token) if parsed else []
                if getattr(client, 'keep_evidence', False):
                    step_state.setdefault('classic', {})['STRICT'] = strict_candidates
                track = choose_match(*parsed, strict_candidates) if parsed else None
                method = 'STRICT'
                if not track:
                    # Search the complete title if the strict method misses.
                    candidates = client.search('', video['title'], token)
                    if getattr(client, 'keep_evidence', False):
                        step_state.setdefault('classic', {})['LOOSE'] = candidates
                    track = choose_title_fallback(video['title'], parsed[1] if parsed else video['title'],
                                                  candidates, has_artist=bool(parsed))
                    method = 'LOOSE'
                if not track:
                    track = detail_search(client, video, parsed, token, strict_candidates + candidates)
                    method = 'DETAIL'
                if not track:
                    # A chain of separate extra search steps (syncer/search_steps.py).
                    # `step_state` already holds the classic results for --explain.
                    track, code = search_steps.search_more(
                        client, video, parsed, token, step_state,
                        keep_evidence=getattr(client, 'keep_evidence', False))
                    method = code or 'DETAIL'
                    if code:
                        LOG.info('EXTRA STEP %s matched %s', code, vid)
                if not track:
                    counts['skip'] += 1
                    report_issue(issues, 'SKIP', video, 'No confident artist/title/version match')
                    remember_skip(db, video)
                    save_skip_changes(state, dry_run)
                    LOG.info('SKIP %s: no confident artist/title/version match (video: %s) (saved; not searched again)',
                             vid, log_text(video['title']))
                    if issues is not None and getattr(client, 'keep_evidence', False):
                        evidence[vid] = {'title': log_text(video['title']), 'tries': list(step_state.get('tries') or [])}
                        LOG.info('EXPLAIN %s: %d search result(s) kept for --explain', vid, len(evidence[vid]['tries']))
                    # Which extra steps ran, so a miss can be inspected later.
                    LOG.info('SKIP %s: extra steps tried: %s', vid,
                             ', '.join(step_state.get('tried') or ['none']))
                    continue
                tid = track['id']
                evidence.pop(vid, None)   # matched now: no need to explain it later
                artist_names = ', '.join(a.get('name', '') for a in track.get('artists', []))
                LOG.info('%s MATCH %s: %s — %s', method, vid, log_text(track['name']), log_text(artist_names))
            if tid in planned or tid in queued:
                # Two videos resolved to the same track: add it only once.
                counts['skip'] += 1
                reason = 'Same track already planned in this dry run' if dry_run else 'Same track already planned in this run'
                report_issue(issues, 'SKIP', video, reason, tid, method)
                # Only the first video of a colliding pair is remembered: the
                # track is already in the playlist, so this one adds nothing.
                remember_skip(db, video)
                save_skip_changes(state, dry_run)
                LOG.info('SKIP %s: %s (saved; not searched again)', vid, reason)
                continue
            if tid in existing:
                # Already in the Spotify playlist: recorded in the database so it
                # is never searched again, but not a skip and not reported.
                LOG.info('SYNCED %s -> %s: already in the Spotify playlist (not counted, not reported)',
                         vid, tid)
                if not dry_run:
                    db['videos'][vid] = tid
                    save_state(STATE_PATH, state)
                continue
            if dry_run:
                counts['add'] += 1
                planned.add(tid)
                report_issue(issues, 'WOULD ADD', video, 'Dry run: no Spotify or database change', tid, method)
                LOG.info('WOULD ADD %s -> %s', vid, tid)
                continue
            queue.append({'video': vid, 'track': tid, 'meta': video, 'method': method})
            queued.add(tid)
            if len(queue) >= batch_size:
                flush_batch(client, playlist, token, state, db, queue, batch_size, counts, issues)
                queued.difference_update(tid for tid in list(queued) if tid in existing)
        except FatalError as exc:
            counts['fail'] += 1
            record_failure(db, vid)
            save_skip_changes(state, dry_run)
            report_issue(issues, 'FAIL', video, str(exc), tid)
            fatal = exc
            break
        except SyncError as exc:
            counts['fail'] += 1
            tried = record_failure(db, vid)
            save_skip_changes(state, dry_run)
            # Only the last failure is loud: a song that keeps failing goes
            # quiet and is retried silently on the next run.
            if tried >= MAX_REPORTED_FAILURES:
                report_issue(issues, 'FAIL', video, f'{exc} (last time logged; retried silently from now on)', tid)
            else:
                report_issue(issues, 'FAIL', video, f'{exc} (this will be logged once more, then go quiet)', tid)
            LOG.warning('FAIL %s: %s (attempt %d)', vid, exc, tried)
        except OSError:
            counts['fail'] += 1
            report_issue(issues, 'FAIL', video, 'Database file I/O error; sync stopped', tid)
            raise
    def drain():
        while queue:
            try:
                flush_batch(client, playlist, token, state, db, queue, batch_size, counts, issues)
            except OSError:
                counts['fail'] += 1
                report_issue(issues, 'FAIL', queue[0]['meta'], 'Database file I/O error; sync stopped',
                             queue[0]['track'], queue[0].get('method'))
                raise

    if fatal:
        # Tracks still queued were never sent; the next run retries them without
        # duplicating anything already added in earlier batches.
        save_deferred(dry_run)
        raise fatal
    drain()
    save_deferred(dry_run)


def db_stats(state):
    """Count saved songs, remembered skips, failed attempts and pending items per playlist."""
    rows = []
    for playlist, db in sorted((state.get('playlists') or {}).items()):
        db = db if isinstance(db, dict) else {}
        pending = db.get('pending')
        rows.append((playlist,
                     len(db.get('videos') or {}),
                     len(db.get('skipped') or {}) if isinstance(db.get('skipped'), dict) else 0,
                     sum(1 for n in failures(db).values() if isinstance(n, int) and n > 0),
                     len(pending.get('items') or []) if isinstance(pending, dict) else 0))
    return rows


def db_summary(path, title='Database'):
    """Markdown summary of the sync database, safe to print in a job summary."""
    try:
        state = load_state(path)
    except FatalError as exc:
        return f'### 🗄️ {title}\n\nCould not read `{path}`: {exc}\n'
    rows = db_stats(state)
    lines = [f'### 🗄️ {title}', '',
             '| Playlist | Saved songs | Skipped (not retried) | Failed (retried) | Pending |',
             '|---|---|---|---|---|']
    if rows:
        lines += [f'| `{playlist}` | **{saved}** | {skipped or "—"} | {failed or "—"} | {pending or "—"} |'
                  for playlist, saved, skipped, failed, pending in rows]
    else:
        lines.append('| (empty) | 0 | — | — | — |')
    total = sum(saved for _, saved, _, _, _ in rows)
    never = sum(skipped for _, _, skipped, _, _ in rows)
    lines += ['', f'**Total saved songs: {total}** · **Skipped for good: {never}**',
              '', 'Songs listed as skipped were logged once (twice for failures) and are not retried.',
              'A dry run writes only this skip/failure bookkeeping; a live run also commits added songs.']
    return '\n'.join(lines) + '\n'


def explain(state=None, limit=25):
    """Search every remembered skip again and print what Spotify returned.

    Read-only: no Spotify write, no database write. It answers one question:
    "was the song not on Spotify, or did our checks refuse it?"
    """
    state = load_state(STATE_PATH) if state is None else state
    rows = []
    for playlist, db in sorted((state.get('playlists') or {}).items()):
        skipped = db.get('skipped') if isinstance(db, dict) else None
        for video_id, info in sorted((skipped or {}).items()):
            rows.append((playlist, video_id, str(info.get('title', '')), str(info.get('channel', ''))))
    if not rows:
        print('No remembered skips: every song was added, or nothing has run yet.')
        return 0
    saved = state.get('evidence') if isinstance(state.get('evidence'), dict) else {}
    # A saved --save-explain run can answer without touching Spotify at all.
    client, token = None, None
    if any(video_id not in saved for _, video_id, _, _ in rows):
        client = Client(float(os.environ.get('REQUEST_DELAY_SECONDS', '1') or 1))
        client.keep_evidence = True
        try:
            client.spotify_backend = 'web-player'
            cookie = sp_dc_from_file(os.environ.get('SPOTIFY_COOKIE_FILE', 'cookies/spotify.txt'))
            token = client.token(cookie)
        except (FatalError, ValueError, OSError) as exc:
            print(f'Could not start a Spotify session: {exc}')
            return 1
    printed = 0
    for playlist, video_id, title, channel in rows:
        if printed >= limit:
            print(f'… {len(rows) - printed} more skipped song(s) not shown (limit {limit}).')
            break
        printed += 1
        video = {'id': video_id, 'title': title, 'channel': channel, 'description': ''}
        parsed = metadata(video)
        step_state = {'keep_evidence': True}
        if video_id in saved:
            # A run with --save-explain already recorded what Spotify returned.
            print(f'{title}   (youtu.be/{video_id})')
            print(f'  parsed as: {parsed or "(nothing usable)"}')
            for attempt in saved[video_id].get('tries', []):
                names = ' | '.join(f'{name} — {artist}' for name, artist in attempt.get('results', [])) or '(no results)'
                print(f"  {attempt.get('step', '?'):<8} q={attempt.get('query', '')!r:<45} → {names}")
            print('  verdict: still no match (from the last --save-explain run)\n')
            continue
        try:
            match, code = search_steps.search_more(client, video, parsed, token, step_state)
        except SyncError as exc:
            print(f'{title}\n  error: {exc}\n')
            continue
        print(f'{title}   (youtu.be/{video_id})')
        print(f'  parsed as: {parsed or "(nothing usable)"}')
        for method_name in ('STRICT', 'LOOSE'):
            results = step_state.get('classic', {}).get(method_name) or []
            names = ' | '.join(f"{item.get('name', '')} — {', '.join(a.get('name', '') for a in item.get('artists', []))}"
                               for item in results[:3]) or '(no results)'
            print(f'  {method_name:<8} → {names}')
        for attempt in step_state.get('tries', []):
            names = ' | '.join(f'{name} — {artist}' for name, artist in attempt['results']) or '(no results)'
            print(f"  {attempt['step']:<8} q={attempt['query']!r:<45} → {names}")
        print(f'  verdict: {"MATCH " + code if match else "still no match"}\n')
    return 0

def main():
    parser = argparse.ArgumentParser(description='Experimental one-way YouTube to Spotify sync')
    parser.add_argument('--dry-run', action='store_true',
                        help='preview only: read YouTube and Spotify, search, but write nothing '
                             '(no Spotify change, no database change). Also enabled by DRY_RUN=true.')
    parser.add_argument('--db-summary', action='store_true',
                        help='print a markdown summary of the sync database and exit')
    parser.add_argument('--playlist-title', action='store_true',
                        help='print the YouTube playlist name and its link, then exit')
    parser.add_argument('--steps', action='store_true',
                        help='list the extra search steps and exit')
    parser.add_argument('--explain', action='store_true',
                        help='search the songs that were skipped and print what Spotify returned, then exit '
                             '(no Spotify change, no database change)')
    parser.add_argument('--save-explain', action='store_true',
                        help='with a normal run: keep the rejected search results of skipped songs in the '
                             'database so --explain can show them without searching again')
    args = parser.parse_args()
    if args.db_summary:
        print(db_summary(STATE_PATH), end='')
        return 0
    logging.basicConfig(level=logging.INFO, format='%(levelname)s %(message)s')
    if args.steps:
        for number, step in enumerate(search_steps.STEPS, start=1):
            print(f'{number:2d}. {step.code:<10} {step.title}')
        return 0
    if args.explain:
        return explain()
    if args.playlist_title:
        # One read-only API call, for the run page. Never fails the job.
        try:
            client = Client(0)
            name = client.youtube_playlist(
                os.environ.get('YOUTUBE_API_KEY', ''),
                playlist_id(os.environ.get('YOUTUBE_PLAYLIST', ''), 'YouTube'))
        except (FatalError, ValueError) as exc:
            LOG.info('Playlist name unavailable: %s', exc)
            return 0
        print(f"{name['title']} — {name['url']}")
        return 0
    # The workflow sets DRY_RUN, so the same switch works locally and in Actions.
    if os.environ.get('DRY_RUN', '').strip().lower() == 'true':
        args.dry_run = True
    if args.dry_run:
        LOG.info('DRY RUN: nothing will be written to Spotify and the database will not change')
    counts = {'add': 0, 'skip': 0, 'fail': 0}
    issues = []
    result = 'SUCCESS'
    fatal_reason = None
    playlist = {'id': '', 'title': 'YouTube playlist', 'channel': '', 'url': ''}
    client = Client(0)
    client.keep_evidence = args.save_explain
    batch_size = BATCH_MAX
    try:
        delay = float(os.environ.get('REQUEST_DELAY_SECONDS', '2'))
        if delay < 0 or delay > 60 or not delay < float('inf'):
            raise ValueError('delay out of range')
        client.delay = delay
        batch_size = int(os.environ.get('SPOTIFY_BATCH_SIZE', str(BATCH_MAX)))
        if not 1 <= batch_size <= BATCH_MAX:
            raise ValueError('batch size out of range')
        yt = playlist_id(os.environ.get('YOUTUBE_PLAYLIST', ''), 'YouTube')
        spotify = playlist_id(os.environ.get('SPOTIFY_PLAYLIST', ''), 'Spotify')
        key = os.environ.get('YOUTUBE_API_KEY', '')
        if not key:
            raise FatalError('YOUTUBE_API_KEY is missing')
        state = load_state(STATE_PATH)
        overrides = load_overrides(OVERRIDES_PATH)
        cookie = sp_dc_from_file(os.environ.get('SPOTIFY_COOKIE_FILE', 'cookies/spotify.txt'))
        playlist = client.youtube_playlist(key, yt)
        # The Spotify playlist has the same name, so the YouTube one is enough.
        LOG.info('Playlist: %s — %s', playlist['title'], playlist['url'])
        videos = client.youtube(key, yt)
        token = client.token(cookie)
        sync(client, videos, spotify, token, state, args.dry_run, counts, overrides=overrides,
             issues=issues, batch_size=batch_size)
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
        # Bookkeeping gathered during a dry run is written here too: a song that
        # was reported twice stays quiet on every later run.
        try:
            save_deferred(args.dry_run)
        except OSError:
            LOG.error('Could not save the skip/failure bookkeeping')
        name_line = f"Playlist: {playlist['title']}\n{playlist['url']}\n\n" if playlist.get('url') else ''
        summary = (f"{name_line}YouTube → Spotify {'DRY RUN' if args.dry_run else 'SYNC'}: {result}\n"
                   f"{'Would add' if args.dry_run else 'Added'}: {counts['add']} | "
                   f"Skipped: {counts['skip']} | Failed: {counts['fail']}")
        # Which extra search step found what: the quickest way to judge the steps.
        extra = {}
        for event in issues:
            code = event.get('method')
            if code in search_steps.CODES:
                extra[code] = extra.get(code, 0) + 1
        if extra:
            summary += '\nMatched by extra step: ' + ', '.join(
                f'{code} ×{number}' for code, number in sorted(extra.items(), key=lambda item: -item[1]))
        if fatal_reason:
            summary += f'\nRun stopped: {issue_text(fatal_reason)}'
        LOG.info(summary.replace('\n\nPlaylist', '\nPlaylist'))
        events = [dict(event, n=number) for number, event in enumerate(issues, start=1)]
        LOG.info('Full report: %d event(s)', len(events))
        mode = 'DRY RUN' if args.dry_run else 'SYNC'
        header = f'YouTube → Spotify log ({mode}): {len(events)} song(s) to report'
        if playlist.get('url'):
            header += f"\nPlaylist: {playlist['title']} — {playlist['url']}"
        reports = [summary_message(summary, events)]
        if events:
            reports += activity_messages(header, events)
        delivered = client.telegram_many(os.environ.get('TELEGRAM_BOT_TOKEN'),
                                         os.environ.get('TELEGRAM_CHAT_ID'), reports)
        if not delivered:
            # Telegram限额, blocked bot or no secrets: the report still has to
            # reach the user, so print the same messages in the Actions log.
            LOG.warning('Telegram report was not delivered; printing it to the Actions log instead')
            for message in reports:
                LOG.info('\n%s', message)
    return 0 if result == 'SUCCESS' else 1

# The extra search steps live in their own module. It imports this one back, so
# the import happens only now, when every helper above already exists.
from . import search_steps  # noqa: E402  (deliberately last)

if __name__ == '__main__':
    raise SystemExit(main())
