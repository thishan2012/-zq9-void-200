import copy
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from syncer import app

TRACK = {'id': 't1', 'name': 'Song', 'artists': [{'name': 'Artist'}]}
VIDEO = {'id': 'v1', 'title': 'Artist - Song (Official Video)', 'channel': 'irrelevant'}

class FakeClient:
    def __init__(self, existing=()):
        self.existing = set(existing)
        self.added = []
    def existing_tracks(self, playlist, token): return self.existing.copy()
    def search(self, artist, title, token): return [TRACK]
    def add(self, playlist, track, token): self.added.append(track)

class Tests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = Path(self.tmp.name) / 'state.json'
        self.patch = patch.object(app, 'STATE_PATH', self.path)
        self.patch.start()
        self.addCleanup(self.patch.stop)
        self.addCleanup(self.tmp.cleanup)
    def run_sync(self, client, videos, state, dry=False):
        counts = {'add': 0, 'skip': 0, 'fail': 0}
        app.sync(client, videos, 'playlist', 'token', state, dry, counts)
        return counts
    def test_urls(self):
        self.assertEqual(app.playlist_id('https://www.youtube.com/playlist?list=PL_123', 'YouTube'), 'PL_123')
        self.assertEqual(app.playlist_id('https://open.spotify.com/playlist/' + 'a'*22 + '?si=x', 'Spotify'), 'a'*22)
        with self.assertRaises(app.FatalError): app.playlist_id('bad', 'Spotify')
    def test_youtube_loads_video_descriptions_in_batches(self):
        from unittest.mock import Mock
        client = app.Client(0)
        ids = [f'v{i}' for i in range(51)]
        playlist_items = [{'snippet': {'title': 'Title', 'resourceId': {'videoId': vid}}} for vid in ids]
        client.request = Mock(side_effect=[
            {'items': playlist_items},
            {'items': [{'id': 'v0', 'snippet': {'title': 'Song', 'channelTitle': 'Uploader', 'description': 'Artist: Singer'}, 'contentDetails': {'duration': 'PT3M1S'}}]},
            {'items': [{'id': 'v50', 'snippet': {'title': 'Other', 'channelTitle': 'Uploader', 'description': 'Artist: Someone'}}]},
        ])
        videos = client.youtube('api-key', 'playlist')
        self.assertEqual(len(videos), 51)
        self.assertEqual(videos[0]['description'], 'Artist: Singer')
        self.assertEqual(videos[0]['duration_ms'], 181000)
        self.assertEqual(videos[50]['description'], 'Artist: Someone')
        self.assertEqual(client.request.call_args_list[1].kwargs['params']['part'], 'snippet,contentDetails')
        self.assertEqual(len(client.request.call_args_list[1].kwargs['params']['id'].split(',')), 50)
        self.assertEqual(client.request.call_args_list[2].kwargs['params']['id'], 'v50')

    def test_cookie_httponly_and_domain(self):
        self.path.write_text('#HttpOnly_.spotify.com\tTRUE\t/\tTRUE\t0\tsp_dc\tvalue\n')
        self.assertEqual(app.sp_dc_from_file(self.path), 'value')
        self.path.write_text('.evil.com\tTRUE\t/\tTRUE\t0\tsp_dc\tvalue\n')
        with self.assertRaises(app.FatalError): app.sp_dc_from_file(self.path)
    def test_matching_requires_artist_and_title(self):
        self.assertEqual(app.metadata(VIDEO), ('Artist', 'Song (Official Video)'))
        self.assertEqual(app.choose_match(*app.metadata(VIDEO), [TRACK]), TRACK)
        self.assertIsNone(app.choose_match('Wrong artist', 'Song', [TRACK]))
        # A title with no credit falls back to the channel name as the artist.
        self.assertEqual(app.metadata({'title': 'Song', 'channel': 'Uploader'}), ('Uploader', 'Song'))
        # Generic upload channels ("Slowed Vibes", "Music", "… - Topic") are no credit.
        self.assertIsNone(app.metadata({'title': 'Song', 'channel': 'Slowed Vibes'}))
        self.assertIsNone(app.metadata({'title': 'Song', 'channel': 'Music'}))
    def test_regular_video_uses_artist_credit_in_description(self):
        video = {'id': 'v2', 'title': 'VISION SLOWED', 'channel': 'Music Video Uploader',
                 'description': 'UdieNnx - VISION SLOWED\nSubscribe for more music!'}
        self.assertEqual(app.metadata(video), ('UdieNnx', 'VISION SLOWED'))
        spotify = {'id': 'vision', 'name': 'VISION - Slowed',
                   'artists': [{'name': 'UdieNnx'}, {'name': 'HXVSAGE'}]}
        self.assertEqual(app.choose_match(*app.metadata(video), [spotify]), spotify)
        class VisionClient(FakeClient):
            def search(self, artist, title, token): return [spotify]
        counts = self.run_sync(VisionClient(), [video], {'version': 1, 'playlists': {}}, True)
        self.assertEqual(counts, {'add': 1, 'skip': 0, 'fail': 0})

    def test_regular_video_without_reliable_credit_is_skipped(self):
        video = {'title': 'Song - Slowed', 'channel': 'Uploader',
                 'description': 'https://example.com\nOther Artist - Different Song'}
        self.assertIsNone(app.metadata(video))
        video['title'] = 'Song - Slowed + Extended'
        self.assertIsNone(app.metadata(video))
        video['title'] = 'Song - Slowed'
        video['description'] = 'Artist: The Band\nA different line'
        self.assertEqual(app.metadata(video), ('The Band', 'Song - Slowed'))
        video['description'] = 'The Band - Song - Slowed\nMore music'
        self.assertEqual(app.metadata(video), ('The Band', 'Song - Slowed'))

    def test_generic_release_topic_uses_song_credits_not_channel_name(self):
        video = {'id': 'v4', 'title': 'PARAISO', 'channel': 'Release - Topic',
                 'description': 'Provided to YouTube by Distributor\n\nPARAISO · Artist One · Artist Two\n\nReleased on: 2025-01-01'}
        self.assertEqual(app.metadata(video), ('Artist One, Artist Two', 'PARAISO'))
        result = {'id': 'p1', 'name': 'PARAISO', 'artists': [{'name': 'Artist One'}, {'name': 'Artist Two'}]}
        self.assertEqual(app.choose_match(*app.metadata(video), [result]), result)
        video['description'] = ''
        self.assertIsNone(app.metadata(video))
        video['channel'] = 'release - topic'
        self.assertIsNone(app.metadata(video))

    def test_topic_description_must_match_video_title(self):
        video = {'title': 'Song', 'channel': 'Real Artist - Topic',
                 'description': 'Other Song · Different Artist'}
        self.assertEqual(app.metadata(video), ('Real Artist', 'Song'))
        video['description'] = 'Song · First Artist · Second Artist'
        self.assertEqual(app.metadata(video), ('First Artist, Second Artist', 'Song'))

    def test_topic_title_with_version_is_not_treated_as_artist(self):
        video = {'title': 'Song - Slowed', 'channel': 'Artist - Topic'}
        self.assertEqual(app.metadata(video), ('Artist', 'Song - Slowed'))
        video['title'] = 'Artist - Song'
        self.assertEqual(app.metadata(video), ('Artist', 'Song'))

    def test_versions_and_artist_are_not_interchangeable(self):
        def track(name, artist='Artist'):
            return {'id': 't', 'name': name, 'artists': [{'name': artist}]}
        self.assertIsNone(app.choose_match('Artist', 'Song (Slowed)', [track('Song')]))
        self.assertIsNone(app.choose_match('Artist', 'Song (Slowed + Extended)', [track('Song - Slowed')]))
        self.assertIsNone(app.choose_match('Artist', 'Song (Official Video - Slowed)', [track('Song')]))
        self.assertIsNone(app.choose_match('Artist', 'Song (Live)', [track('Song')]))
        self.assertIsNone(app.choose_match('Artist', 'Song', [track('Song', 'Other')]))
        self.assertIsNotNone(app.choose_match('Artist, Guest', 'Song (Slowed)', [track('Song - Slowed')]))

    def test_version_matching_keeps_speed_edits_and_remix_identity(self):
        def track(name, artist='Artist', ident='t'):
            return {'id': ident, 'name': name, 'artists': [{'name': artist}]}
        same_pairs = [
            ('Song (Ultra Slowed)', 'Song - Ultra Slowed'),
            ('Song (Super Slowed)', 'Song - Super Slowed'),
            ('Song (Slowed + Reverb)', 'Song - Slowed and Reverb'),
            ('Song (Sped Up)', 'Song - Speed Up'),
            ('Song (Official Video - Slowed)', 'Song - Slowed'),
            ('Song (Slowed Version)', 'Song - Slowed'),
            ('Song (Alex Remix)', 'Song - Alex Remix'),
        ]
        for yt, spotify in same_pairs:
            with self.subTest(youtube=yt, spotify=spotify):
                self.assertIsNotNone(app.choose_match('Artist', yt, [track(spotify)]))
        different_pairs = [
            ('Song (Ultra Slowed)', 'Song - Slowed'),
            ('Song (Ultra Slowed)', 'Song - Super Slowed'),
            ('Song (Over Slowed)', 'Song - Slowed'),
            ('Song (Slowed)', 'Song - Slowed and Reverb'),
            ('Song (Slowed + Extended)', 'Song - Slowed'),
            ('Song (Sped Up)', 'Song - Slowed'),
            ('Song (Alex Remix)', 'Song - Blake Remix'),
            ('Song (8D Audio)', 'Song'),
            ('Song 2', 'Song'),
        ]
        for yt, spotify in different_pairs:
            with self.subTest(youtube=yt, spotify=spotify):
                self.assertIsNone(app.choose_match('Artist', yt, [track(spotify)]))
        self.assertIsNone(app.choose_match('Artist', 'Song', [track('Song', artist='Artista')]))
        self.assertIsNone(app.choose_match('Artist', 'Song', [track('Song', ident='one'), track('Song', ident='two')]))
        self.assertIsNotNone(app.choose_match('Artist', 'Song', [track('Song'), track('Song')]))

    def test_title_fallback_matches_closest_but_keeps_versions(self):
        def track(name, ident='one', artist='Artist'):
            return {'id': ident, 'name': name, 'artists': [{'name': artist}]}
        choose = app.choose_title_fallback
        good = track('Shadows')
        self.assertEqual(choose('Artist - Shadowss', 'Shadowss', [good], has_artist=True), good)
        self.assertEqual(choose('VISION SLOWED', 'VISION SLOWED', [track('VISION - Slowed')], has_artist=False)['id'], 'one')
        self.assertEqual(choose('Artist Song', 'Artist Song', [track('Song')], has_artist=False)['id'], 'one')
        for expected, candidate in [
            ('Song (Ultra Slowed)', 'Song - Slowed'),
            ('Song (Ultra Slowed)', 'Song - Super Slowed'),
            ('Song (Over Slowed)', 'Song - Slowed'),
            ('Song (Slowed + Reverb)', 'Song - Slowed'),
            ('Song (Alex Remix)', 'Song - Blake Remix'),
            ('Long Song Name 2', 'Long Song Name'),
            ('Song 0.8x Slowed', 'Song 0.9x Slowed'),
            ('Song (8D Audio)', 'Song'),
        ]:
            with self.subTest(expected=expected, candidate=candidate):
                self.assertIsNone(choose(expected, expected, [track(candidate)], has_artist=True))
        self.assertIsNone(choose('Song', 'Song', [track('Song', 'one'), track('Song', 'two', 'Other')], has_artist=False))
        self.assertIsNone(choose('Private video', 'Private video', [track('Private video')], has_artist=False))

    def test_fallback_only_after_strict_miss_and_searches_video_title(self):
        class SearchClient(FakeClient):
            def __init__(self):
                super().__init__()
                self.queries = []
            def search(self, artist, title, token):
                self.queries.append((artist, title))
                if artist:
                    return []
                return [{'id': 'target', 'name': 'Shadows', 'artists': [{'name': 'Other'}]}]
        video = {'id': 'v2', 'title': 'Artist - Shadowss (Official Video)', 'channel': 'Uploader'}
        client = SearchClient()
        state = {'version': 1, 'playlists': {}}
        with self.assertLogs('sync', level='INFO') as logs:
            # The same video appears twice: the second copy is skipped without
            # searching Spotify again.
            counts = self.run_sync(client, [video, video], state)
        self.assertEqual(client.queries, [('Artist', 'Shadowss (Official Video)'), ('', video['title'])])
        self.assertEqual(client.added, ['target'])
        self.assertEqual(counts, {'add': 1, 'skip': 0, 'fail': 0})
        self.assertTrue(any('LOOSE MATCH' in line for line in logs.output))
        self.assertEqual(app.load_state(self.path)['playlists']['playlist']['videos']['v2'], 'target')

    def test_missing_artist_uses_title_fallback_dry_run(self):
        class NoArtistClient(FakeClient):
            def search(self, artist, title, token):
                self.query = (artist, title)
                return [{'id': 'vision', 'name': 'VISION - Slowed', 'artists': [{'name': 'UdieNnx'}]}]
        video = {'id': 'v3', 'title': 'VISION SLOWED', 'channel': 'Uploader'}
        client = NoArtistClient()
        with self.assertLogs('sync', level='INFO') as logs:
            counts = self.run_sync(client, [video], {'version': 1, 'playlists': {}}, dry=True)
        self.assertEqual(client.query, ('', 'VISION SLOWED'))
        self.assertEqual(counts, {'add': 1, 'skip': 0, 'fail': 0})
        self.assertEqual(client.added, [])
        self.assertFalse(self.path.exists())
        self.assertTrue(any('LOOSE MATCH' in line for line in logs.output))

    def test_strict_match_does_not_use_fallback(self):
        class StrictClient(FakeClient):
            def __init__(self):
                super().__init__()
                self.queries = []
            def search(self, artist, title, token):
                self.queries.append((artist, title))
                return [TRACK]
        client = StrictClient()
        self.run_sync(client, [VIDEO], {'version': 1, 'playlists': {}}, dry=True)
        self.assertEqual(client.queries, [('Artist', 'Song (Official Video)')])

    def test_add_once_and_persist(self):
        state = {'version': 1, 'playlists': {}}
        client = FakeClient()
        self.assertEqual(self.run_sync(client, [VIDEO, VIDEO], state), {'add': 1, 'skip': 0, 'fail': 0})
        self.assertEqual(client.added, ['t1'])
        self.assertEqual(app.load_state(self.path)['playlists']['playlist']['videos'], {'v1': 't1'})
    def test_existing_and_dry_run(self):
        state = {'version': 1, 'playlists': {}}
        client = FakeClient(['t1'])
        # Already in the playlist: saved to the database, not counted as a skip.
        self.assertEqual(self.run_sync(client, [VIDEO], state)['skip'], 0)
        self.assertEqual(app.load_state(self.path)['playlists']['playlist']['videos'], {'v1': 't1'})
        self.assertEqual(client.added, [])
        self.path.unlink()
        state = {'version': 1, 'playlists': {}}
        self.assertEqual(self.run_sync(FakeClient(), [VIDEO, VIDEO], state, True), {'add': 1, 'skip': 0, 'fail': 0})
        self.assertFalse(self.path.exists())
    def test_uncertain_write_and_reconciliation(self):
        class Uncertain(FakeClient):
            def add(self, *args): raise app.UncertainWrite('unknown')
        state = {'version': 1, 'playlists': {}}
        with self.assertRaises(app.UncertainWrite): self.run_sync(Uncertain(), [VIDEO], state)
        saved = app.load_state(self.path)
        self.assertEqual(saved['playlists']['playlist']['pending'],
                         {'items': [{'video': 'v1', 'track': 't1'}]})
        with self.assertRaises(app.FatalError): self.run_sync(FakeClient(), [VIDEO], copy.deepcopy(saved))
        self.run_sync(FakeClient(['t1']), [VIDEO], saved)
        self.assertIsNone(app.load_state(self.path)['playlists']['playlist']['pending'])
    def test_per_song_error_does_not_stop(self):
        class BadFirst(FakeClient):
            def search(self, artist, title, token):
                if title == 'Bad': raise app.SyncError('temporary error')
                return [TRACK]
        counts = self.run_sync(BadFirst(), [{'id': 'v0', 'title': 'Artist - Bad'}, VIDEO], {'version': 1, 'playlists': {}})
        self.assertEqual(counts, {'add': 1, 'skip': 0, 'fail': 1})

if __name__ == '__main__': unittest.main()
