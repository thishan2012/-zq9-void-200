import io
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from syncer import app


def video(n):
    return {'id': f'vid{n:08d}'[:11], 'title': f'Artist {n} - Song {n}', 'channel': 'Uploader'}


class BatchClient:
    """Spotify double that records batched adds the way the real Client does."""

    def __init__(self, existing=()):
        self.existing = set(existing)
        self.batches = []
        self.searches = 0

    def existing_tracks(self, playlist, token):
        return self.existing.copy()

    def search(self, artist, title, token):
        self.searches += 1
        number = int(title.rsplit(' ', 1)[1])
        return [{'id': f'track{number:017d}', 'name': f'Song {number}',
                 'artists': [{'name': f'Artist {number}'}]}]

    def add_batch(self, playlist, tracks, token):
        self.batches.append(list(tracks))
        self.existing.update(tracks)


class BatchingTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = Path(self.tmp.name) / 'state.json'
        self.patch = patch.object(app, 'STATE_PATH', self.path)
        self.patch.start()
        self.addCleanup(self.patch.stop)

    def run_sync(self, client, videos, *, dry=False, batch_size=app.BATCH_MAX):
        counts = {'add': 0, 'skip': 0, 'fail': 0}
        issues = []
        # Start from the database on disk, like a second workflow run does.
        state = app.load_state(self.path)
        app.sync(client, videos, 'playlist', 'token', state, dry,
                 counts, issues=issues, batch_size=batch_size)
        return counts, issues

    def test_two_hundred_tracks_are_added_in_two_batches(self):
        client = BatchClient()
        counts, issues = self.run_sync(client, [video(i) for i in range(200)])
        self.assertEqual(counts, {'add': 200, 'skip': 0, 'fail': 0})
        self.assertEqual([len(batch) for batch in client.batches], [100, 100])
        self.assertEqual(len(set(sum(client.batches, []))), 200)
        saved = app.load_state(self.path)['playlists']['playlist']
        self.assertEqual(len(saved['videos']), 200)
        self.assertIsNone(saved['pending'])
        self.assertEqual(sum(issue['status'] == 'ADD' for issue in issues), 200)

    def test_batch_size_is_configurable_and_capped(self):
        client = BatchClient()
        self.run_sync(client, [video(i) for i in range(120)], batch_size=50)
        self.assertEqual([len(batch) for batch in client.batches], [50, 50, 20])
        self.path.unlink()
        client = BatchClient()
        # A batch larger than Spotify's limit is clamped instead of failing.
        self.run_sync(client, [video(i) for i in range(150)], batch_size=5000)
        self.assertEqual([len(batch) for batch in client.batches], [100, 50])

    def test_tracks_already_in_spotify_are_skipped_without_a_batch(self):
        existing = {f'track{i:017d}' for i in range(10)}
        client = BatchClient(existing)
        counts, issues = self.run_sync(client, [video(i) for i in range(15)])
        self.assertEqual(counts, {'add': 5, 'skip': 10, 'fail': 0})
        self.assertEqual([batch for batch in client.batches], [[f'track{i:017d}' for i in range(10, 15)]])
        self.assertTrue(all(issue['reason'] == 'Track already in Spotify playlist'
                            for issue in issues if issue['status'] == 'SKIP'))

    def test_second_run_adds_nothing(self):
        videos = [video(i) for i in range(120)]
        self.run_sync(BatchClient(), videos)
        client = BatchClient()
        counts, _ = self.run_sync(client, videos)
        self.assertEqual(counts, {'add': 0, 'skip': 120, 'fail': 0})
        self.assertEqual(client.searches, 0)
        self.assertEqual(client.batches, [])

    def test_dry_run_never_writes_but_reports_every_song(self):
        client = BatchClient()
        counts, issues = self.run_sync(client, [video(i) for i in range(150)], dry=True)
        self.assertEqual(counts, {'add': 150, 'skip': 0, 'fail': 0})
        self.assertEqual(client.batches, [])
        self.assertFalse(self.path.exists())
        self.assertEqual(sum(issue['status'] == 'WOULD ADD' for issue in issues), 150)
        full = '\n'.join(app.activity_messages('log', [dict(i, n=n) for n, i in enumerate(issues, 1)]))
        self.assertIn('WOULD ADD: Artist 149 - Song 149', full)

    def test_pending_batch_is_per_item_and_reconciles(self):
        class Uncertain(BatchClient):
            def add_batch(self, playlist, tracks, token):
                super().add_batch(playlist, tracks, token)
                raise app.UncertainWrite('unknown')
        state = {'version': 1, 'playlists': {}}
        counts = {'add': 0, 'skip': 0, 'fail': 0}
        with self.assertRaises(app.UncertainWrite):
            app.sync(Uncertain(), [video(i) for i in range(3)], 'playlist', 'token', state, False, counts)
        pending = app.load_state(self.path)['playlists']['playlist']['pending']
        self.assertEqual([item['video'] for item in pending['items']], [video(i)['id'] for i in range(3)])
        self.assertEqual(counts['fail'], 3)
        # Tracks landed in Spotify: the next run records all three and adds the new one.
        client = BatchClient({f'track{i:017d}' for i in range(3)})
        counts = {'add': 0, 'skip': 0, 'fail': 0}
        app.sync(client, [video(0), video(3)], 'playlist', 'token', state, False, counts)
        self.assertEqual(counts, {'add': 1, 'skip': 1, 'fail': 0})
        saved = app.load_state(self.path)['playlists']['playlist']
        self.assertEqual(sorted(saved['videos']), [video(i)['id'] for i in range(4)])
        self.assertIsNone(saved['pending'])

    def test_full_log_lists_successful_additions(self):
        _, issues = self.run_sync(BatchClient(), [video(1)])
        text = '\n'.join(app.activity_messages('full log', [dict(i, n=1) for i in issues]))
        self.assertIn('ADD: Artist 1 - Song 1', text)
        self.assertIn('open.spotify.com/track/', text)
        self.assertIn('youtu.be/', text)
        # ...but the compact summary still omits them.
        self.assertNotIn('Artist 1 - Song 1', '\n'.join(app.telegram_messages('summary', issues)))


class RateLimitTests(unittest.TestCase):
    class Response:
        def __init__(self, code, value=None, headers=None):
            self.status_code = code
            self.value = value if value is not None else {}
            self.headers = headers or {}

        def json(self):
            return self.value

    def client(self):
        client = app.Client(0)
        client.retries = 3
        client.http = Mock()
        return client

    def test_read_is_retried_after_429(self):
        client = self.client()
        client.http.request.side_effect = [
            self.Response(429, headers={'Retry-After': '0'}),
            self.Response(200, {'items': [], 'next': None}),
        ]
        with patch.object(app.time, 'sleep') as sleep:
            self.assertEqual(client.existing_tracks('p', 'token'), set())
        self.assertEqual(client.http.request.call_count, 2)
        self.assertEqual(sleep.call_count, 1)

    def test_write_is_never_retried_after_429(self):
        # A 429 on a write is a definite rejection: it is reported, never retried.
        client = self.client()
        client.spotify_backend = 'web-player'
        client.http.request.return_value = self.Response(429)
        with self.assertRaises(app.SyncError) as error:
            client.add_batch('p', ['track1'], 'token')
        self.assertNotIsInstance(error.exception, app.UncertainWrite)
        self.assertEqual(client.http.request.call_count, 1)

    def test_retries_are_bounded(self):
        client = self.client()
        client.retries = 2
        client.http.request.return_value = self.Response(503)
        with patch.object(app.time, 'sleep'):
            with self.assertRaises(app.HttpFatal):
                client.existing_tracks('p', 'token')
        self.assertEqual(client.http.request.call_count, 3)  # one try + two retries

    def test_backoff_uses_retry_after_then_exponential(self):
        self.assertEqual(app.backoff_seconds(self.Response(429, headers={'Retry-After': '7'}), 1), 7)
        self.assertEqual(app.backoff_seconds(self.Response(429, headers={'Retry-After': 'bad'}), 2), 10)
        self.assertEqual(app.backoff_seconds(self.Response(500), 1), 5)
        self.assertEqual(app.backoff_seconds(self.Response(500), 10), 60)


if __name__ == '__main__':
    unittest.main()


class DryRunSwitchTests(unittest.TestCase):
    """DRY_RUN=true must behave exactly like --dry-run (used by the workflow)."""

    def setUp(self):
        import os
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = Path(self.tmp.name) / 'state.json'
        self.patch = patch.object(app, 'STATE_PATH', self.path)
        self.patch.start()
        self.addCleanup(self.patch.stop)
        self.client = Mock()
        self.client.youtube.return_value = [{'id': 'AAAAAAAAAAA', 'title': 'Artist - No Match', 'channel': 'U'}]
        self.client.existing_tracks.return_value = set()
        self.client.search.return_value = []
        self.env = {'YOUTUBE_PLAYLIST': 'playlist', 'SPOTIFY_PLAYLIST': 'a' * 22, 'YOUTUBE_API_KEY': 'key'}

    def run_main(self, extra_env, argv):
        import sys
        with patch.object(app, 'Client', return_value=self.client), \
             patch.object(app, 'sp_dc_from_file', return_value='cookie'), \
             patch.object(app, 'load_state', return_value={'version': 1, 'playlists': {}}), \
             patch.object(app, 'load_overrides', return_value={}), \
             patch.dict('os.environ', dict(self.env, **extra_env), clear=True), \
             patch.object(sys, 'argv', argv):
            return app.main()

    def test_env_var_enables_dry_run_without_flag(self):
        with self.assertLogs('sync', level='INFO') as logs:
            self.assertEqual(self.run_main({'DRY_RUN': 'true'}, ['app']), 0)
        self.assertTrue(any('DRY RUN: nothing will be written' in line for line in logs.output))
        report = '\n\n'.join(self.client.telegram_many.call_args.args[2])
        self.assertIn('DRY RUN', report)
        self.assertIn('Would add: 0', report)
        self.assertFalse(self.path.exists())

    def test_without_the_switch_the_run_is_live(self):
        with self.assertLogs('sync', level='INFO') as logs:
            self.assertEqual(self.run_main({}, ['app']), 0)
        self.assertFalse(any('nothing will be written' in line for line in logs.output))
        report = '\n\n'.join(self.client.telegram_many.call_args.args[2])
        self.assertIn('SYNC: SUCCESS', report)
        self.assertIn('Added: 0', report)


class DatabaseSummaryTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = Path(self.tmp.name) / 'state.json'

    def test_summary_counts_saved_songs_and_pending(self):
        self.path.write_text(json.dumps({'version': 1, 'playlists': {
            'pl1': {'videos': {'v1': 't1', 'v2': 't2'}, 'pending': None},
            'pl2': {'videos': {'v1': 't1'}, 'pending': {'items': [{'video': 'v9', 'track': 't9'}]}},
        }}), encoding='utf-8')
        text = app.db_summary(self.path)
        self.assertIn('| `pl1` | **2** | — |', text)
        self.assertIn('| `pl2` | **1** | 1 |', text)
        self.assertIn('**Total saved songs: 3**', text)
        self.assertEqual(app.db_stats(app.load_state(self.path)), [('pl1', 2, 0), ('pl2', 1, 1)])

    def test_summary_handles_missing_and_empty_database(self):
        self.assertIn('(empty)', app.db_summary(self.path))
        self.path.write_text('{broken', encoding='utf-8')
        self.assertIn('Could not read', app.db_summary(self.path))

    def test_cli_prints_summary_and_exits(self):
        import sys
        self.path.write_text(json.dumps({'version': 1, 'playlists': {
            'pl1': {'videos': {'v1': 't1'}, 'pending': None}}}), encoding='utf-8')
        with patch.object(app, 'STATE_PATH', self.path), \
             patch('sys.stdout', new_callable=io.StringIO) as out, \
             patch.object(sys, 'argv', ['app', '--db-summary']):
            self.assertEqual(app.main(), 0)
        self.assertIn('| `pl1` | **1** | — |', out.getvalue())


class ScheduleTests(unittest.TestCase):
    def test_workflow_runs_six_times_a_day(self):
        import yaml
        root = Path(__file__).resolve().parents[2]
        for workflow in (root / '.github' / 'workflows' / 'sync.yml',
                         root / 'spotify-yt-playlist-sync' / '.github' / 'workflows' / 'sync.yml'):
            data = yaml.safe_load(workflow.read_text(encoding='utf-8'))
            cron = data[True]['schedule'][0]['cron']
            self.assertEqual(cron, '0 */4 * * *', workflow)
