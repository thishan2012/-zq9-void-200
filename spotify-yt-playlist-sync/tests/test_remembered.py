import io
import json
import sys
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

    def test_the_weekly_retry_releases_only_expired_skips(self):
        self.run_sync([NO_MATCH, {'id': 'DDDDDDDDDDD', 'title': 'Private video'}])
        db = self.state['playlists']['playlist']
        # One skip is old, the other was recorded just now.
        db['skipped']['BBBBBBBBBBB']['at'] = '2020-01-01T00:00:00+00:00'
        released = app.release_expired_skips(self.state)
        self.assertEqual(released, 1)
        self.assertNotIn('BBBBBBBBBBB', db['skipped'])
        self.assertIn('DDDDDDDDDDD', db['skipped'])

        # The released song is searched again (and reported, because it is the
        # first time this run's answer is told to the reader again).
        counts, issues, client = self.run_sync([NO_MATCH])
        self.assertTrue(client.searches)
        self.assertEqual(counts['skip'], 1)

    def test_a_fresh_skip_survives_the_weekly_retry(self):
        self.run_sync([NO_MATCH])
        self.assertEqual(app.release_expired_skips(self.state), 0)
        self.assertIn('BBBBBBBBBBB', self.state['playlists']['playlist']['skipped'])

    def test_an_old_entry_without_a_timestamp_is_retried(self):
        # Entries written before the timestamp existed: retried once, then dated.
        self.state['playlists']['playlist'] = {'videos': {},
                                               'skipped': {'BBBBBBBBBBB': {'title': 'Artist - No Match'}}}
        self.assertEqual(app.release_expired_skips(self.state), 1)

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

    def test_the_match_tally_is_kept_per_method(self):
        self.run_sync([NO_MATCH], dry=False)
        db = self.state['playlists']['playlist']
        self.assertEqual(app.step_stats(db), {})

        counts, _, _ = self.run_sync([{'id': 'EEEEEEEEEEE', 'title': 'Artist - Good Song',
                                       'channel': 'U'}], dry=False)
        self.assertEqual(counts['add'], 1)
        self.assertEqual(app.step_stats(db), {'STRICT': 1})

    def test_the_stats_report_lists_methods_and_unused_steps(self):
        db = self.state['playlists'].setdefault('playlist', {'videos': {}, 'skipped': {}})
        db['matched'] = {'STRICT': 7, 'LOOSE': 2, 'SUFFIX': 1}
        app.save_state(self.path, self.state)
        report = app.stats_report(self.path)
        self.assertIn('`STRICT`', report)
        self.assertIn('**7**', report)
        self.assertIn('70%', report)
        self.assertIn('Never tried', report)
        self.assertIn('`TOPRESULT`', report)
        self.assertNotIn('None', report.split('Never tried')[0])

    def test_the_tally_is_labelled_as_history_not_this_run(self):
        # 316 matched vs 158 saved looked like a double count: say it plainly.
        db = self.state['playlists'].setdefault('playlist', {'videos': {}, 'skipped': {}})
        db['matched'] = {'STRICT': 292, 'LOOSE': 24}
        db['videos'] = {f'v{i}': f't{i}' for i in range(158)}
        app.save_state(self.path, self.state)
        report = app.stats_report(self.path)
        self.assertIn('matched 316 (all runs so far, dry runs included)', report)
        self.assertIn('saved 158', report)

    def test_a_cached_step_is_not_shown_as_idle(self):
        # DURATION found 4 songs with no new query (the results were cached):
        # a dash there reads as "this step did nothing".
        db = self.state['playlists'].setdefault('playlist', {'videos': {}, 'skipped': {}})
        db['matched'] = {'DURATION': 4}
        db['ran'] = {'DURATION': 4}
        app.save_state(self.path, self.state)
        report = app.stats_report(self.path)
        row = [line for line in report.splitlines() if '`DURATION`' in line][0]
        self.assertIn('cached', row)

    def test_a_step_that_ran_is_not_called_never_tried(self):
        db = self.state['playlists'].setdefault('playlist', {'videos': {}, 'skipped': {}})
        db['matched'] = {'STRICT': 1}
        db['ran'] = {'SINGLE': 5}          # ran, but every query was a cache hit
        app.save_state(self.path, self.state)
        report = app.stats_report(self.path)
        self.assertIn('Tried but never won: `SINGLE`', report)
        self.assertNotIn('`SINGLE`', report.split('Never tried')[1])

    def test_a_quiet_live_run_still_saves_its_bookkeeping(self):
        # A live run that adds nothing used to write no file at all, so its
        # counters (and the summary) vanished.
        class NoMatch:
            def existing_tracks(self, playlist, token):
                return set()

            def search(self, *args):
                return []

        before = self.path.read_text() if self.path.exists() else ''
        counts, _, _ = self.run_sync([NO_MATCH], dry=False, client=NoMatch())
        self.assertEqual(counts['skip'], 1)
        self.assertTrue(self.path.exists())
        db = app.load_state(self.path)['playlists']['playlist']
        self.assertIn(NO_MATCH['id'], db.get('skipped') or {})

    def test_a_dry_run_does_not_write_until_the_end(self):
        before = self.path.read_text() if self.path.exists() else ''
        with patch.object(app, 'save_state', wraps=app.save_state) as spy:
            self.run_sync([NO_MATCH], dry=True)
        # dry runs write once (save_deferred), never per song
        self.assertLessEqual(spy.call_count, 2)

    def test_a_step_that_tries_but_never_wins_is_named(self):
        # The tally must not call a step dead when it searches every run: that
        # was exactly how "SONGTAG" looked after the first live run.
        db = self.state['playlists'].setdefault('playlist', {'videos': {}, 'skipped': {}})
        db['matched'] = {'STRICT': 4}
        db['worked'] = {'STRICT': 9, 'SONGTAG': 5}
        db['ran'] = {'STRICT': 12, 'SONGTAG': 12, 'ISRC': 0}
        app.save_state(self.path, self.state)
        report = app.stats_report(self.path)
        tried, never = report.split('Never tried')
        self.assertIn('Tried but never won: `SONGTAG`', tried)
        self.assertIn('`ISRC`', never)
        self.assertNotIn('`SONGTAG`', never)
        self.assertIn('Queries sent', report)
        self.assertIn('| 5 |', report)     # its queries are visible, not a blank

    def test_stats_report_survives_a_missing_database(self):
        report = app.stats_report(self.path)
        self.assertIn('Match statistics', report)
        self.assertIn('Nothing counted yet', report)

    def test_skipped_entries_are_tiny(self):
        self.run_sync([NO_MATCH])
        saved = json.loads(self.path.read_text(encoding='utf-8'))
        entry = saved['playlists']['playlist']['skipped']['BBBBBBBBBBB']
        # The entry stays small: the title, the channel, the rule version that
        # gave up (so a later rule change can re-try it quietly) and the time it
        # gave up (so the weekly run knows the retry window has passed).
        self.assertEqual(set(entry), {'title', 'channel', 'since', 'at'})
        self.assertEqual(entry['title'], 'Artist - No Match')
        self.assertEqual(entry['channel'], 'U')
        self.assertEqual(entry['since'], app.MATCHER_VERSION)
        self.assertTrue(entry['at'].endswith('+00:00'))


class ResetDatabaseTests(unittest.TestCase):
    """The emergency switch: forget the database, never touch Spotify."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = Path(self.tmp.name) / 'sync-state.json'
        self.patch = patch.object(app, 'STATE_PATH', self.path)
        self.patch.start()
        self.addCleanup(self.patch.stop)
        self.addCleanup(self.tmp.cleanup)
        app.save_state(self.path, {
            'version': 1, 'matcher': app.MATCHER_VERSION,
            'playlists': {
                'PLAAAAAAAAAAAAAAAAAAAA': {
                    'videos': {'aaaaaaaaaaa': 'T' * 22, 'bbbbbbbbbbb': 'U' * 22},
                    'skipped': {'ccccccccccc': {'title': 'Gone', 'since': 3, 'at': '2026-01-01T00:00:00+00:00'}},
                    'pending': None, 'matched': {'STRICT': 2}, 'worked': {'STRICT': 3}, 'ran': {'STRICT': 3}},
                'PLBBBBBBBBBBBBBBBBBBBB': {
                    'videos': {'ddddddddddd': 'V' * 22}, 'pending': None, 'matched': {'LOOSE': 1}},
            }})
        self.original = self.path.read_text(encoding='utf-8')

    def test_nothing_changes_without_yes(self):
        with patch('sys.stdout', new_callable=io.StringIO) as out:
            self.assertEqual(app.reset_database('all', None, dry_run=True), 0)
        self.assertIn('Dry run', out.getvalue())
        self.assertEqual(self.path.read_text(encoding='utf-8'), self.original)

    def test_all_empties_the_database_but_keeps_a_backup(self):
        with patch('sys.stdout', new_callable=io.StringIO) as out:
            app.reset_database('all', None, dry_run=False)
        self.assertEqual(json.loads(self.path.read_text(encoding='utf-8')),
                         {'version': 1, 'playlists': {}})
        backup = self.path.with_name(self.path.name + '.bak')
        self.assertTrue(backup.exists())
        self.assertEqual(backup.read_text(encoding='utf-8'), self.original)
        self.assertIn('saved songs forgotten:  3', out.getvalue())
        self.assertIn('untouched', out.getvalue())

    def test_one_playlist_leaves_the_other_alone(self):
        with patch('sys.stdout', new_callable=io.StringIO):
            app.reset_database('playlist', 'PLAAAAAAAAAAAAAAAAAAAA', dry_run=False)
        playlists = json.loads(self.path.read_text(encoding='utf-8'))['playlists']
        self.assertEqual(list(playlists), ['PLBBBBBBBBBBBBBBBBBBBB'])
        self.assertEqual(playlists['PLBBBBBBBBBBBBBBBBBBBB']['videos'], {'ddddddddddd': 'V' * 22})

    def test_history_keeps_the_duplicate_guard(self):
        with patch('sys.stdout', new_callable=io.StringIO):
            app.reset_database('history', None, dry_run=False)
        saved = json.loads(self.path.read_text(encoding='utf-8'))
        db = saved['playlists']['PLAAAAAAAAAAAAAAAAAAAA']
        self.assertEqual(len(db['videos']), 2)
        self.assertIn('ccccccccccc', db['skipped'])
        for key in ('matched', 'worked', 'ran', 'runs'):
            self.assertNotIn(key, db)
        self.assertNotIn('matcher', saved)

    def test_an_already_empty_database_says_so(self):
        with patch('sys.stdout', new_callable=io.StringIO) as out:
            app.reset_database('all', None, dry_run=False)
            self.assertEqual(app.reset_database('all', None, dry_run=False), 0)
        self.assertIn('Nothing to reset', out.getvalue())

    def test_the_backup_is_optional(self):
        with patch('sys.stdout', new_callable=io.StringIO):
            app.reset_database('all', None, dry_run=False, backup=False)
        self.assertFalse(self.path.with_name(self.path.name + '.bak').exists())

    def test_the_playlist_argument_is_validated_on_the_command_line(self):
        with patch('sys.stdout', new_callable=io.StringIO):
            with patch.object(sys, 'argv', ['app', '--reset-db', 'playlist']):
                self.assertEqual(app.main(), 2)
            with patch.object(sys, 'argv', ['app', '--reset-db', 'playlist', '--playlist', 'nope']):
                self.assertEqual(app.main(), 2)


if __name__ == '__main__':
    unittest.main()
