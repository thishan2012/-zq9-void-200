import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from syncer import app


def track(name, artist='Artist', ident='track1', duration=180000):
    return {'id': ident, 'name': name, 'artists': [{'name': artist}], 'duration_ms': duration}


class DetailMatchingTests(unittest.TestCase):
    def test_youtube_duration_parser(self):
        self.assertEqual(app.youtube_duration_ms('PT3M1S'), 181000)
        self.assertEqual(app.youtube_duration_ms('PT1H2M3.5S'), 3723500)
        self.assertEqual(app.youtube_duration_ms('P1DT2H'), 93600000)
        for bad in ('', 'PT', 'PT0S', '3:01', None, 'P1M'):
            self.assertIsNone(app.youtube_duration_ms(bad))

    def test_query_core_does_not_strip_actual_song_words(self):
        self.assertEqual(app.search_core('On My Way (Ultra Slowed + Reverb)'), 'on my way')
        self.assertEqual(app.search_core('Super Down (Slowed)'), 'super down')
        self.assertEqual(app.search_core('Up and Down'), 'up and down')
        self.assertEqual(app.search_core('Song - Sped Up'), 'song')

    def test_detail_matches_reordered_title_and_checks_duration(self):
        video = {'title': 'Artist - On My Way (Slowed)', 'duration_ms': 186000}
        parsed = ('Artist', 'On My Way (Slowed)')
        good = track('My Way On - Slowed')
        self.assertEqual(app.choose_detail_fallback(video, parsed, [good]), good)
        self.assertIsNone(app.choose_detail_fallback(video, parsed, [track('My Way On - Slowed', duration=300000)]))
        # A different artist is allowed when the title/version match strongly.
        self.assertEqual(app.choose_detail_fallback(video, parsed, [track('My Way On - Slowed', artist='Different')])['id'], 'track1')
        self.assertIsNone(app.choose_detail_fallback(video, parsed, [track('My Way On - Ultra Slowed')]))
        self.assertIsNone(app.choose_detail_fallback(video, parsed, [track('My Way On - Ultra Slowed', artist='Different')]))
        self.assertIsNone(app.choose_detail_fallback(video, parsed, [track('My Way On - Slowed', ident='a'), track('My Way On - Slowed', ident='b')]))
        self.assertIsNone(app.choose_detail_fallback(video, parsed, [track('My Way On - Slowed', artist='Different', ident='a'), track('My Way On - Slowed', artist='Another', ident='b')]))
        self.assertEqual(app.choose_detail_fallback(video, parsed, [track('My Way On - Slowed', duration=None)] )['id'], 'track1')

    def test_details_preserve_specific_versions_and_title_numbers(self):
        def choose(source, candidate):
            video = {'title': source, 'duration_ms': 180000}
            return app.choose_detail_fallback(video, ('Artist', source), [track(candidate)])
        for source, candidate in [
            ('On My Way (Ultra Slowed)', 'My Way On - Slowed'),
            ('On My Way (Slowed + Reverb)', 'My Way On - Slowed'),
            ('On My Way (Slowed + Extended)', 'My Way On - Slowed'),
            ('On My Way (Alex Remix)', 'My Way On - Blake Remix'),
            ('On My Way 2', 'My Way On'),
            ('On My Way 0.8x Slowed', 'My Way On 0.9x Slowed'),
            ('Super Down', 'Down'),
        ]:
            with self.subTest(source=source, candidate=candidate):
                self.assertIsNone(choose(source, candidate))

    def test_details_can_handle_no_artist_if_title_is_strong(self):
        video = {'title': 'Shine Bright Slowed', 'duration_ms': 180000}
        self.assertEqual(app.choose_detail_fallback(video, None, [track('Bright Shine - Slowed')])['id'], 'track1')
        self.assertIsNone(app.choose_detail_fallback(video, None, [track('Bright Shine - Ultra Slowed')]))

    def test_third_method_runs_only_after_two_misses_and_is_dry(self):
        class Client:
            def __init__(self): self.queries, self.added = [], []
            def existing_tracks(self, playlist, token): return set()
            def search(self, artist, title, token):
                self.queries.append((artist, title))
                if (artist, title) == ('Artist', 'on my way'):
                    return [track('My Way On - Slowed')]
                return []
            def add(self, playlist, track_id, token): self.added.append(track_id)
        client = Client()
        video = {'id': 'video1', 'title': 'Artist - On My Way (Slowed)', 'duration_ms': 186000}
        state = {'version': 1, 'playlists': {}}
        counts = {'add': 0, 'skip': 0, 'fail': 0}
        with tempfile.TemporaryDirectory() as temp, patch.object(app, 'STATE_PATH', Path(temp) / 'state.json'), self.assertLogs('sync', level='INFO') as logs:
            app.sync(client, [video], 'playlist', 'token', state, True, counts)
            self.assertFalse(app.STATE_PATH.exists())
        self.assertEqual(client.queries[:2], [('Artist', 'On My Way (Slowed)'), ('', video['title'])])
        self.assertIn(('Artist', 'on my way'), client.queries)
        self.assertEqual(counts, {'add': 1, 'skip': 0, 'fail': 0})
        self.assertFalse(client.added)
        self.assertTrue(any('DETAIL MATCH' in line for line in logs.output))

    def test_third_method_real_add_is_recorded_and_not_added_twice(self):
        class Client:
            def __init__(self): self.added = []
            def existing_tracks(self, playlist, token): return set()
            def search(self, artist, title, token):
                return [track('My Way On - Slowed')] if (artist, title) == ('Artist', 'on my way') else []
            def add(self, playlist, track_id, token): self.added.append(track_id)
        client = Client()
        video = {'id': 'video1', 'title': 'Artist - On My Way (Slowed)', 'duration_ms': 186000}
        counts = {'add': 0, 'skip': 0, 'fail': 0}
        state = {'version': 1, 'playlists': {}}
        with tempfile.TemporaryDirectory() as temp, patch.object(app, 'STATE_PATH', Path(temp) / 'state.json'):
            app.sync(client, [video, video], 'playlist', 'token', state, False, counts)
            saved = app.load_state(app.STATE_PATH)
        self.assertEqual(client.added, ['track1'])
        self.assertEqual(counts, {'add': 1, 'skip': 1, 'fail': 0})
        self.assertEqual(saved['playlists']['playlist']['videos'], {'video1': 'track1'})

    def test_existing_methods_do_not_run_third_method(self):
        class Client:
            def __init__(self): self.queries = []
            def existing_tracks(self, playlist, token): return set()
            def search(self, artist, title, token):
                self.queries.append((artist, title))
                return [track('Song')]
        client = Client()
        counts = {'add': 0, 'skip': 0, 'fail': 0}
        app.sync(client, [{'id': 'v', 'title': 'Artist - Song'}], 'playlist', 'token', {'version': 1, 'playlists': {}}, True, counts)
        self.assertEqual(client.queries, [('Artist', 'Song')])
        self.assertEqual(counts['add'], 1)

if __name__ == '__main__':
    unittest.main()
