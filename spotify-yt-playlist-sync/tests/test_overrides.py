import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from syncer import app

VIDEO = {'id': 'FGys9rRBytU', 'title': 'PARAISO', 'channel': 'Release - Topic'}
TRACK_ID = '1R96NBIdXeLeYHvstCJV1J'

class FakeClient:
    def __init__(self, existing=()):
        self.existing = set(existing)
        self.added = []
        self.searched = []
    def existing_tracks(self, playlist, token): return self.existing.copy()
    def search(self, artist, title, token):
        self.searched.append((artist, title))
        return []
    def add(self, playlist, tid, token): self.added.append(tid)

class OverrideTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.state_path = Path(self.tmp.name) / 'state.json'
        self.patch = patch.object(app, 'STATE_PATH', self.state_path)
        self.patch.start()
        self.addCleanup(self.patch.stop)
        self.overrides = {VIDEO['id']: TRACK_ID}
        self.state = {'version': 1, 'playlists': {}}

    def run_sync(self, client, dry=False, videos=None):
        counts = {'add': 0, 'skip': 0, 'fail': 0}
        app.sync(client, videos or [VIDEO], 'playlist', 'token', self.state, dry, counts, self.overrides)
        return counts

    def test_validates_override_file(self):
        path = Path(self.tmp.name) / 'overrides.json'
        self.assertEqual(app.load_overrides(path), {})
        path.write_text(json.dumps(self.overrides), encoding='utf-8')
        self.assertEqual(app.load_overrides(path), self.overrides)
        for bad in (['invalid'], {'bad': TRACK_ID}, {VIDEO['id']: 'https://example.com'}, {VIDEO['id']: 3}):
            path.write_text(json.dumps(bad), encoding='utf-8')
            with self.subTest(bad=bad), self.assertRaises(app.FatalError): app.load_overrides(path)
        path.write_text('{broken', encoding='utf-8')
        with self.assertRaises(app.FatalError): app.load_overrides(path)

    def test_manual_choice_in_dry_run_is_reported_without_writes(self):
        client = FakeClient()
        with self.assertLogs('sync', level='INFO') as logs:
            counts = self.run_sync(client, dry=True, videos=[VIDEO, VIDEO])
        # The second copy of the same video is silent (database only).
        self.assertEqual(counts, {'add': 1, 'skip': 0, 'fail': 0})
        self.assertEqual(client.searched, [])
        self.assertEqual(client.added, [])
        self.assertFalse(self.state_path.exists())
        self.assertTrue(any('MANUAL MATCH' in line and TRACK_ID in line for line in logs.output))

    def test_manual_choice_adds_only_once_and_records_state(self):
        client = FakeClient()
        counts = self.run_sync(client, videos=[VIDEO, VIDEO])
        self.assertEqual(counts, {'add': 1, 'skip': 0, 'fail': 0})
        self.assertEqual(client.added, [TRACK_ID])
        self.assertEqual(app.load_state(self.state_path)['playlists']['playlist']['videos'], {VIDEO['id']: TRACK_ID})
        self.assertEqual(app.load_state(self.state_path)['playlists']['playlist']['pending'], None)

    def test_manual_choice_does_not_duplicate_existing_track(self):
        client = FakeClient([TRACK_ID])
        self.assertEqual(self.run_sync(client), {'add': 0, 'skip': 0, 'fail': 0})
        self.assertEqual(client.added, [])
        self.assertEqual(app.load_state(self.state_path)['playlists']['playlist']['videos'], {VIDEO['id']: TRACK_ID})

    def test_uncertain_manual_write_is_pending_not_retried(self):
        class Uncertain(FakeClient):
            def add(self, playlist, tid, token):
                self.added.append(tid)
                raise app.UncertainWrite('uncertain')
        client = Uncertain()
        with self.assertRaises(app.UncertainWrite): self.run_sync(client)
        pending = app.load_state(self.state_path)['playlists']['playlist']['pending']
        self.assertEqual(pending, {'items': [{'video': VIDEO['id'], 'track': TRACK_ID}]})
        self.assertEqual(client.added, [TRACK_ID])

    def test_unavailable_video_is_not_overridden(self):
        client = FakeClient()
        unavailable = dict(VIDEO, title='Private video')
        self.assertEqual(self.run_sync(client, videos=[unavailable])['skip'], 1)
        self.assertEqual(client.added, [])
        # Remembered in the database so it is not searched or logged again.
        db = app.load_state(self.state_path)['playlists']['playlist']
        self.assertEqual(list(db['skipped']), [unavailable['id']])

    def test_unmapped_video_uses_automatic_matching(self):
        client = FakeClient()
        video = {'id': 'other-video', 'title': 'Other Artist - Other Song'}
        self.assertEqual(self.run_sync(client, dry=True, videos=[video])['skip'], 1)
        self.assertTrue(client.searched)

if __name__ == '__main__': unittest.main()
