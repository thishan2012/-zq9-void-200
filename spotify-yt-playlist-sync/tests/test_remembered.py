import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from syncer import app

TRACK = '1R96NBIdXeLeYHvstCJV1J'
NO_MATCH = {'id': 'BBBBBBBBBBB', 'title': 'Artist - No Match', 'channel': 'U'}
BROKEN = {'id': 'CCCCCCCCCCC', 'title': 'Artist - Error Song', 'channel': 'U'}
GOOD = {'id': 'AAAAAAAAAAA', 'title': 'Artist - Good Song', 'channel': 'U'}


class Client:
    """Fake Spotify client: one track, optional failing search titles."""

    def __init__(self, failing=(), existing=()):
        self.failing = set(failing)
        self.existing = set(existing)
        self.added = []
        self.searches = []

    def youtube_playlist(self, key, playlist):
        return {'id': playlist, 'title': 'Viral Phonk', 'channel': 'Thishan',
                'url': f'https://www.youtube.com/playlist?list={playlist}'}

    def existing_tracks(self, playlist, token):
        return self.existing.copy()

    def search(self, artist, title, token):
        self.searches.append(title)
        if title in self.failing:
            raise app.SyncError('Spotify search: network error')
        if 'No Match' in title:
            return []
        return [{'id': TRACK, 'name': 'Good Song', 'artists': [{'name': 'Artist'}]}]

    def add(self, playlist, track, token):
        self.added.append(track)


class RememberedTests(unittest.TestCase):
    """A song is logged at most twice, then lives quietly in the database."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = Path(self.tmp.name) / 'state.json'
        self.state_patch = patch.object(app, 'STATE_PATH', self.path)
        self.state_patch.start()
        self.addCleanup(self.state_patch.stop)
        self.state = {'version': 1, 'playlists': {}}
        app.DRY_STATE.clear()

    def run_sync(self, videos, client=None, dry=True, state=None, overrides=None):
        counts = {'add': 0, 'skip': 0, 'fail': 0}
        issues = []
        client = client or Client()
        app.sync(client, list(videos), 'playlist', 'token', state or self.state, dry, counts,
                 overrides=overrides, issues=issues)
        return counts, issues, client

    def test_a_skip_is_logged_once_then_stays_quiet(self):
        counts, issues, client = self.run_sync([NO_MATCH])
        self.assertEqual(counts['skip'], 1)
        self.assertEqual([event['reason'] for event in issues], ['No confident artist/title/version match'])

        # Second run: the song is in the database, so no search, no count, no log.
        counts, issues, client = self.run_sync([NO_MATCH])
        self.assertEqual(counts, {'add': 0, 'skip': 0, 'fail': 0})
        self.assertEqual(issues, [])
        self.assertEqual(client.searches, [])

    def test_an_unavailable_video_is_logged_once_then_stays_quiet(self):
        video = {'id': 'DDDDDDDDDDD', 'title': 'Private video'}
        counts, issues, _ = self.run_sync([video])
        self.assertEqual(counts['skip'], 1)
        self.assertEqual(len(issues), 1)
        counts, issues, _ = self.run_sync([video])
        self.assertEqual(counts['skip'], 0)
        self.assertEqual(issues, [])

    def test_a_failure_is_logged_twice_and_then_goes_quiet(self):
        self.assertEqual(app.MAX_REPORTED_FAILURES, 2)
        counts, issues, _ = self.run_sync([BROKEN], client=Client(failing=['Artist - Error Song']))
        self.assertEqual(counts['fail'], 1)
        self.assertIn('logged once more', issues[0]['reason'])

        counts, issues, _ = self.run_sync([BROKEN], client=Client(failing=['Artist - Error Song']))
        self.assertEqual(counts['fail'], 1)
        self.assertIn('last time logged', issues[0]['reason'])

        # Third run: not retried, not counted, not logged - and no search spent.
        client = Client(failing=['Artist - Error Song'])
        counts, issues, _ = self.run_sync([BROKEN], client=client)
        self.assertEqual(counts, {'add': 0, 'skip': 0, 'fail': 0})
        self.assertEqual(issues, [])
        self.assertEqual(client.searches, [])

    def test_a_manual_match_revives_a_retired_song(self):
        for _ in range(2):
            self.run_sync([BROKEN], client=Client(failing=['Artist - Error Song']))
        self.assertEqual(app.failures(self.state['playlists']['playlist']), {'CCCCCCCCCCC': 2})
        # Two failures is the end of automatic retries; a manual match is the way back.
        counts, issues, client = self.run_sync([BROKEN], dry=False, overrides={'CCCCCCCCCCC': TRACK})
        self.assertEqual(counts['add'], 1)
        self.assertEqual(client.added, [TRACK])
        db = self.state['playlists']['playlist']
        self.assertIn('CCCCCCCCCCC', db['videos'])
        self.assertNotIn('CCCCCCCCCCC', app.failures(db))

    def test_dry_run_bookkeeping_is_written_and_read_back(self):
        self.run_sync([NO_MATCH])
        self.assertTrue(self.path.exists())
        db = app.load_state(self.path)['playlists']['playlist']
        self.assertEqual(db['videos'], {})
        self.assertIn('BBBBBBBBBBB', db['skipped'])
        # A fresh run loading that file from disk is silent.
        app.DRY_STATE.clear()
        state = app.load_state(self.path)
        counts, issues, _ = self.run_sync([NO_MATCH], state=state)
        self.assertEqual(counts['skip'], 0)
        self.assertEqual(issues, [])

    def test_manual_match_wins_over_a_remembered_skip(self):
        self.run_sync([NO_MATCH])
        self.assertIn('BBBBBBBBBBB', self.state['playlists']['playlist']['skipped'])
        counts, issues, client = self.run_sync([NO_MATCH], dry=False, overrides={'BBBBBBBBBBB': TRACK})
        self.assertEqual(counts['add'], 1)
        self.assertEqual(client.added, [TRACK])

    def test_database_summary_shows_skipped_and_failed_without_titles(self):
        self.run_sync([NO_MATCH])
        self.run_sync([BROKEN], client=Client(failing=['Artist - Error Song']))
        text = app.db_summary(self.path)
        self.assertIn('Skipped (not retried)', text)
        self.assertIn('Failed (retried)', text)
        self.assertIn('| `playlist` | **0** | 1 | 1 | — |', text)
        self.assertNotIn('Artist - No Match', text)

    def test_a_new_matcher_version_retries_remembered_skips_once(self):
        self.run_sync([NO_MATCH])
        self.state['matcher'] = app.MATCHER_VERSION - 1   # an older release wrote this database
        counts, issues, client = self.run_sync([NO_MATCH])
        # The remembered skip is cleared, so the song is searched and reported once more.
        self.assertEqual(counts['skip'], 1)
        self.assertEqual(len(issues), 1)
        self.assertEqual(self.state['matcher'], app.MATCHER_VERSION)
        # ...and only once: the next run is quiet again.
        counts, issues, _ = self.run_sync([NO_MATCH])
        self.assertEqual((counts['skip'], issues), (0, []))

    def test_a_current_matcher_version_keeps_skips_quiet(self):
        self.run_sync([NO_MATCH])
        self.assertEqual(self.state['matcher'], app.MATCHER_VERSION)
        counts, issues, _ = self.run_sync([NO_MATCH])
        self.assertEqual((counts['skip'], issues), (0, []))

    def test_playlist_name_comes_from_the_api(self):
        client = app.Client(0)
        client.request = lambda *a, **k: {'items': [{'snippet': {'title': 'Viral Phonk / Slowed',
                                                                  'channelTitle': 'Thishan'}}]}
        name = client.youtube_playlist('key', 'PLabc123')
        self.assertEqual(name, {'id': 'PLabc123', 'title': 'Viral Phonk / Slowed', 'channel': 'Thishan',
                                'url': 'https://www.youtube.com/playlist?list=PLabc123'})

    def test_playlist_name_falls_back_to_a_generic_title(self):
        client = app.Client(0)
        client.request = lambda *a, **k: {'items': [{'snippet': {}}]}
        self.assertEqual(client.youtube_playlist('key', 'PLabc123')['title'], 'YouTube playlist')

    def test_a_missing_playlist_is_a_clear_error(self):
        client = app.Client(0)
        client.request = lambda *a, **k: {'items': []}
        with self.assertRaises(app.FatalError) as caught:
            client.youtube_playlist('key', 'PLabc123')
        self.assertIn('YOUTUBE_PLAYLIST', str(caught.exception))

    def test_playlist_title_flag_prints_name_and_link(self):
        import contextlib
        import io
        import sys
        client = Client()
        buf = io.StringIO()
        env = {'YOUTUBE_API_KEY': 'key', 'YOUTUBE_PLAYLIST': 'https://www.youtube.com/playlist?list=PLabc123'}
        with patch.object(app, 'Client', return_value=client), patch.dict('os.environ', env, clear=True), \
             patch.object(sys, 'argv', ['app', '--playlist-title']), contextlib.redirect_stdout(buf):
            self.assertEqual(app.main(), 0)
        self.assertEqual(buf.getvalue().strip(),
                         'Viral Phonk — https://www.youtube.com/playlist?list=PLabc123')

    def test_a_rule_change_retries_the_skip_but_reports_it_only_once(self):
        _, first, _ = self.run_sync([NO_MATCH])
        self.assertEqual(len(first), 1)
        # A new matcher version gives the remembered skip one more try.
        self.state['matcher'] = app.MATCHER_VERSION - 1
        counts, issues, client = self.run_sync([NO_MATCH])
        self.assertEqual(counts['skip'], 1)          # counted, so the total adds up
        # Counted (so the total adds up) but flagged quiet: it never reaches the
        # Telegram report, and the pick link is not offered again either.
        self.assertEqual([event['quiet'] for event in issues], [True])
        report = app.summary_message('Would add: 0 | Skipped: 1 | Failed: 0', issues)
        self.assertNotIn('No Match', report)
        self.assertNotIn('open.spotify.com/search', report)
        self.assertTrue(client.searches)             # it really was searched again
        self.assertEqual(self.state['playlists']['playlist']['skipped']['BBBBBBBBBBB']['retried'],
                         app.MATCHER_VERSION)
        # The run after that is silent again, with no search spent.
        client = Client()
        counts, issues, _ = self.run_sync([NO_MATCH], client=client)
        self.assertEqual((counts, issues, client.searches), ({'add': 0, 'skip': 0, 'fail': 0}, [], []))

    def test_a_video_that_became_readable_is_searched_again(self):
        # A private video was remembered under its placeholder title.
        self.run_sync([{'id': 'DDDDDDDDDDD', 'title': 'Private video'}])
        self.assertIn('DDDDDDDDDDD', self.state['playlists']['playlist']['skipped'])
        # Later it is public and carries a real title: the remembered skip must
        # not hide it any more.
        client = Client()
        counts, issues, _ = self.run_sync([{'id': 'DDDDDDDDDDD', 'title': 'Artist - Good Song',
                                            'channel': 'U'}], client=client)
        self.assertEqual(counts['add'], 1)
        self.assertEqual([event['status'] for event in issues], ['WOULD ADD'])

    def test_forget_video_removes_one_remembered_skip(self):
        self.run_sync([NO_MATCH])
        import contextlib, io
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            self.assertEqual(app.forget_skips(['BBBBBBBBBBB'], state=self.state), 0)
        self.assertIn('BBBBBBBBBBB', buf.getvalue())
        self.assertNotIn('skipped', self.state['playlists']['playlist'])
        # The next run searches it again (and logs it once more).
        counts, issues, client = self.run_sync([NO_MATCH])
        self.assertEqual(counts['skip'], 1)
        self.assertEqual(len(issues), 1)

    def test_forget_video_rejects_a_bad_id(self):
        self.run_sync([NO_MATCH])
        import contextlib, io
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            self.assertEqual(app.forget_skips(['not-an-id'], state=self.state), 2)
        self.assertIn('BBBBBBBBBBB', self.state['playlists']['playlist']['skipped'])

    def test_forget_skipped_clears_every_remembered_skip(self):
        self.run_sync([NO_MATCH, {'id': 'DDDDDDDDDDD', 'title': 'Private video'}])
        import contextlib, io
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            self.assertEqual(app.forget_skips([], all_skips=True, state=self.state), 0)
        self.assertNotIn('skipped', self.state['playlists']['playlist'])
        self.assertIn('2 remembered skip(s) removed', buf.getvalue())

    def test_skipped_entries_are_tiny(self):
        self.run_sync([NO_MATCH])
        saved = json.loads(self.path.read_text(encoding='utf-8'))
        entry = saved['playlists']['playlist']['skipped']['BBBBBBBBBBB']
        # The entry stays small: the title, the channel, the rule version that
        # gave up (so a later rule change can re-try it quietly).
        self.assertEqual(entry, {'title': 'Artist - No Match', 'channel': 'U', 'since': app.MATCHER_VERSION})


if __name__ == '__main__':
    unittest.main()
