import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from syncer import app

TRACK = '1R96NBIdXeLeYHvstCJV1J'

class Client:
    def __init__(self, existing=()):
        self.existing = set(existing)
        self.added = []
    def existing_tracks(self, playlist, token): return self.existing.copy()
    def search(self, artist, title, token):
        if 'Error Song' in title:
            raise app.SyncError('Spotify search: network error')
        if 'Fatal Song' in title:
            raise app.FatalError('Spotify search: HTTP 401')
        if 'No Match' in title: return []
        return [{'id': TRACK, 'name': 'Good Song', 'artists': [{'name': 'Artist'}]}]
    def add(self, playlist, track, token): self.added.append(track)

class TelegramReportingTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = Path(self.tmp.name) / 'state.json'
        self.state_patch = patch.object(app, 'STATE_PATH', self.path)
        self.state_patch.start()
        self.addCleanup(self.state_patch.stop)

    def test_summary_message_has_only_skips_and_failures(self):
        videos = [
            {'id': 'AAAAAAAAAAA', 'title': 'Artist - Good Song', 'channel': 'Uploader'},
            {'id': 'BBBBBBBBBBB', 'title': 'Artist - No Match (Slowed)', 'channel': 'Release - Topic'},
            {'id': 'CCCCCCCCCCC', 'title': 'Artist - Error Song', 'channel': 'Channel'},
            {'id': 'DDDDDDDDDDD', 'title': 'Private video'},
        ]
        counts = {'add': 0, 'skip': 0, 'fail': 0}
        issues = []
        app.sync(Client(), videos, 'playlist', 'token', {'version': 1, 'playlists': {}}, True, counts, issues=issues)
        self.assertEqual(counts, {'add': 1, 'skip': 2, 'fail': 1})
        # The compact summary lists only skips and failures; the full log in
        # test_full_log_lists_every_event covers successful songs.
        text = '\n'.join(app.telegram_messages('summary', issues))
        self.assertNotIn('Good Song', text)
        for snippet in ('SKIP: Artist - No Match (Slowed)', 'Release - Topic',
                        'https://www.youtube.com/watch?v=BBBBBBBBBBB', 'No confident artist/title/version match',
                        'FAIL: Artist - Error Song', 'Spotify search: network error',
                        'SKIP: Private video', 'Unavailable or missing video title'):
            self.assertIn(snippet, text)
        self.assertFalse(self.path.exists())

    def test_already_recorded_existing_and_dry_run_duplicate(self):
        base = {'title': 'Artist - Good Song', 'channel': 'X'}
        state = {'version': 1, 'playlists': {'playlist': {'videos': {'AAAAAAAAAAA': TRACK}, 'pending': None}}}
        issues = []; counts = {'add': 0, 'skip': 0, 'fail': 0}
        app.sync(Client([TRACK]), [dict(base, id='AAAAAAAAAAA'), dict(base, id='BBBBBBBBBBB')],
                 'playlist', 'token', state, True, counts, issues=issues)
        self.assertIn('Already recorded', issues[0]['reason'])
        self.assertIn('already in Spotify', issues[1]['reason'])
        self.assertEqual(issues[1]['track_id'], TRACK)
        issues = []; counts = {'add': 0, 'skip': 0, 'fail': 0}
        app.sync(Client(), [dict(base, id='AAAAAAAAAAA'), dict(base, id='BBBBBBBBBBB')],
                 'playlist', 'token', {'version': 1, 'playlists': {}}, True, counts, issues=issues)
        self.assertEqual(counts, {'add': 1, 'skip': 1, 'fail': 0})
        self.assertEqual(issues[0]['reason'], 'Dry run: no Spotify or database change')
        self.assertEqual(issues[1]['reason'], 'Same track already planned in this dry run')

    def test_fatal_song_is_reported_and_stops(self):
        issues = []; counts = {'add': 0, 'skip': 0, 'fail': 0}
        video = {'id': 'AAAAAAAAAAA', 'title': 'Artist - Fatal Song', 'channel': 'U'}
        with self.assertRaises(app.FatalError):
            app.sync(Client(), [video], 'playlist', 'token', {'version': 1, 'playlists': {}}, True, counts, issues=issues)
        self.assertEqual(counts['fail'], 1)
        self.assertEqual(issues[0]['reason'], 'Spotify search: HTTP 401')
        self.assertEqual(issues[0]['status'], 'FAIL')

    def test_unknown_write_includes_track_and_safety_reason(self):
        class Uncertain(Client):
            def add(self, playlist, track, token):
                raise app.UncertainWrite('Outcome unknown. Check playlist before clearing pending')
        issues = []; counts = {'add': 0, 'skip': 0, 'fail': 0}
        with self.assertRaises(app.UncertainWrite):
            app.sync(Uncertain(), [{'id': 'AAAAAAAAAAA', 'title': 'Artist - Good Song'}], 'playlist', 'token',
                     {'version': 1, 'playlists': {}}, False, counts, issues=issues)
        self.assertEqual(issues[0]['track_id'], TRACK)
        self.assertIn('Outcome unknown', issues[0]['reason'])
        self.assertEqual(app.load_state(self.path)['playlists']['playlist']['pending'],
                         {'items': [{'video': 'AAAAAAAAAAA', 'track': TRACK}]})

    def test_splits_unicode_without_losing_any_issue(self):
        issues = []
        for i in range(40):
            app.report_issue(issues, 'SKIP', {'id': f'{i:011d}', 'title': f'Item {i} ' + '😀' * 100,
                                              'channel': 'Channel'}, 'No match')
        messages = app.telegram_messages('summary', issues)
        self.assertGreater(len(messages), 1)
        for message in messages:
            self.assertLessEqual(len(message.encode('utf-16-le')) // 2, 4000)
        for i in range(40):
            self.assertEqual(sum(f'Item {i} ' in m for m in messages), 1)
        self.assertEqual(app.telegram_messages('summary', []), ['summary'])

    def test_extremely_long_untrusted_fields_are_bounded_and_controls_removed(self):
        issues = []
        app.report_issue(issues, 'FAIL', {'id': 'bad\nhttps://example.com', 'title': '😀' * 5000,
                                         'channel': '\u202eevil\nchannel'}, '😀' * 5000)
        messages = app.telegram_messages('summary', issues)
        self.assertTrue(all(len(m.encode('utf-16-le')) // 2 <= 4000 for m in messages))
        self.assertNotIn('\u202e', ''.join(messages))
        self.assertNotIn('https://www.youtube.com/watch?v=bad', ''.join(messages))

    def test_main_delivers_issues_and_summary(self):
        client = Mock()
        client.youtube.return_value = [{'id': 'BBBBBBBBBBB', 'title': 'Artist - No Match', 'channel': 'Uploader'}]
        client.existing_tracks.return_value = set()
        client.search.return_value = []
        env = {'YOUTUBE_PLAYLIST': 'playlist', 'SPOTIFY_PLAYLIST': 'a' * 22, 'YOUTUBE_API_KEY': 'key',
               'TELEGRAM_BOT_TOKEN': 'telegram-token', 'TELEGRAM_CHAT_ID': 'chat'}
        with patch.object(app, 'Client', return_value=client), patch.object(app, 'sp_dc_from_file', return_value='cookie'), \
             patch.object(app, 'load_state', return_value={'version': 1, 'playlists': {}}), \
             patch.object(app, 'load_overrides', return_value={}), patch.dict('os.environ', env, clear=True), \
             patch.object(sys, 'argv', ['app', '--dry-run']):
            self.assertEqual(app.main(), 0)
        # One call carries the whole report; the fake returns a Mock (truthy).
        report = '\n\n'.join(client.telegram_many.call_args.args[2])
        self.assertIn('Would add: 0 | Skipped: 1 | Failed: 0', report)
        self.assertIn('SKIP: Artist - No Match', report)
        self.assertIn('Spotify log (DRY RUN)', report)

    def test_main_reports_global_fatal_before_any_song(self):
        client = Mock()
        env = {'YOUTUBE_PLAYLIST': 'playlist', 'SPOTIFY_PLAYLIST': 'a' * 22,
               'TELEGRAM_BOT_TOKEN': 'telegram-token', 'TELEGRAM_CHAT_ID': 'chat'}
        with patch.object(app, 'Client', return_value=client), patch.dict('os.environ', env, clear=True), \
             patch.object(sys, 'argv', ['app', '--dry-run']):
            self.assertEqual(app.main(), 1)
        report = '\n\n'.join(client.telegram_many.call_args.args[2])
        self.assertIn('Failed: 1', report)
        self.assertIn('YOUTUBE_API_KEY is missing', report)
        self.assertNotIn('SKIP:', report)
        self.assertNotIn('FAIL:', report)

    def test_state_io_failure_identifies_the_song(self):
        issues = []; counts = {'add': 0, 'skip': 0, 'fail': 0}
        video = {'id': 'AAAAAAAAAAA', 'title': 'Artist - Good Song'}
        with patch.object(app, 'save_state', side_effect=OSError('sensitive path')), self.assertRaises(OSError):
            app.sync(Client(), [video], 'playlist', 'token', {'version': 1, 'playlists': {}}, False, counts, issues=issues)
        self.assertEqual(counts['fail'], 1)
        self.assertEqual(issues[0]['status'], 'FAIL')
        self.assertNotIn('sensitive path', issues[0]['reason'])

    def test_telegram_transport_sends_plain_text_without_previews(self):
        client = app.Client(0)
        client.http.post = Mock(return_value=Mock(ok=True))
        client.telegram('token', 'chat', 'SKIP: <title>')
        payload = client.http.post.call_args.kwargs['json']
        self.assertEqual(payload['text'], 'SKIP: <title>')
        self.assertTrue(payload['disable_web_page_preview'])
        self.assertNotIn('parse_mode', payload)

if __name__ == '__main__': unittest.main()


class QuietSkipTests(unittest.TestCase):
    """Songs already synced or already in the playlist are saved, not reported."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = Path(self.tmp.name) / 'state.json'
        self.patch = patch.object(app, 'STATE_PATH', self.path)
        self.patch.start()
        self.addCleanup(self.patch.stop)

    def issues_for(self, videos, existing=(), state=None, dry=False):
        issues = []
        counts = {'add': 0, 'skip': 0, 'fail': 0}
        app.sync(Client(existing), videos, 'playlist', 'token',
                 state or {'version': 1, 'playlists': {}}, dry, counts, issues=issues)
        return issues, counts

    def test_already_in_playlist_is_saved_but_not_reported(self):
        videos = [{'id': 'AAAAAAAAAAA', 'title': 'Artist - Good Song', 'channel': 'U'}]
        issues, _ = self.issues_for(videos, existing={TRACK})
        # The database records the mapping so it is never searched again...
        self.assertEqual(app.load_state(self.path)['playlists']['playlist']['videos'],
                         {'AAAAAAAAAAA': TRACK})
        # ...but Telegram says nothing about it.
        self.assertEqual(app.telegram_messages('summary', []), ['summary'])
        self.assertNotIn('Good Song', '\n'.join(app.telegram_messages('summary', issues)))
        self.assertEqual(list(app.activity_messages('log', [dict(i, n=1) for i in issues])), ['log'])
        self.assertEqual(app.skip_breakdown(issues), {'Track already in Spotify playlist': 1})

    def test_no_confident_match_is_still_reported(self):
        videos = [{'id': 'BBBBBBBBBBB', 'title': 'Artist - No Match', 'channel': 'U'}]
        issues, _ = self.issues_for(videos)
        self.assertFalse(issues[0].get('quiet'))
        text = '\n'.join(app.telegram_messages('summary', issues))
        self.assertIn('No confident artist/title/version match', text)
        self.assertIn('BBBBBBBBBBB', text)

    def test_header_counts_quiet_skips(self):
        videos = [
            {'id': 'AAAAAAAAAAA', 'title': 'Artist - Good Song', 'channel': 'U'},
            {'id': 'BBBBBBBBBBB', 'title': 'Artist - No Match', 'channel': 'U'},
        ]
        issues, _ = self.issues_for(videos, existing={TRACK})
        quiet = app.skip_breakdown(issues)
        header = f'log: {len(issues) - sum(quiet.values())} song(s) to report'
        header += f"\nAlready present, not listed ({sum(quiet.values())}): 1 × Track already in Spotify playlist"
        messages = app.activity_messages(header, [dict(i, n=n) for n, i in enumerate(issues, 1)])
        self.assertIn('1 song(s) to report', messages[0])
        self.assertIn('Already present, not listed (1)', messages[0])
        body = '\n'.join(messages)
        self.assertNotIn('Artist - Good Song', body)
        self.assertIn('Artist - No Match', body)

    def test_already_recorded_video_is_quiet(self):
        state = {'version': 1, 'playlists': {'playlist': {'videos': {'AAAAAAAAAAA': TRACK}, 'pending': None}}}
        issues, counts = self.issues_for([{'id': 'AAAAAAAAAAA', 'title': 'Artist - Good Song'}], state=state)
        self.assertEqual(counts['skip'], 1)
        self.assertTrue(issues[0]['quiet'])
        self.assertEqual(app.skip_breakdown(issues), {'Already recorded in the sync database': 1})


class SpamGuardTests(unittest.TestCase):
    """A run must never fire a burst of messages: one report, few chunks."""

    def client(self):
        client = app.Client(0)
        client.http.post = Mock(return_value=Mock(ok=True))
        return client

    def test_many_events_become_few_messages(self):
        issues = []
        for i in range(150):
            app.report_issue(issues, 'SKIP', {'id': f'{i:011d}', 'title': f'Item {i} ' + 'x' * 40,
                                              'channel': 'Channel'}, 'No confident artist/title/version match')
        numbered = [dict(issue, n=n) for n, issue in enumerate(issues, 1)]
        messages = [app.summary_message('summary', numbered)] + app.activity_messages('header', numbered)
        chunks = app.utf16_chunks('\n\n'.join(messages))
        # Everything is present exactly once...
        joined = '\n'.join(chunks)
        for i in range(150):
            self.assertEqual(joined.count(f'Item {i} '), 1)
        # ...and 150 songs still fit in the per-run message cap.
        self.assertLessEqual(len(chunks), app.TELEGRAM_MAX_MESSAGES)
        for chunk in chunks:
            self.assertLessEqual(len(chunk.encode('utf-16-le')) // 2, 4000)
        client = self.client()
        self.assertTrue(client.telegram_many('token', 'chat', messages))
        self.assertLessEqual(len(client.http.post.call_args_list), app.TELEGRAM_MAX_MESSAGES)

    def test_hard_cap_adds_an_omission_notice(self):
        client = self.client()
        big = ['x' * 3900 for _ in range(20)]
        self.assertTrue(client.telegram_many('token', 'chat', big, max_messages=3))
        texts = [call.kwargs['json']['text'] for call in client.http.post.call_args_list]
        self.assertLessEqual(len(texts), 3)
        self.assertIn('omitted', texts[-1])

    def test_no_secrets_means_no_requests(self):
        client = self.client()
        self.assertFalse(client.telegram_many(None, None, ['a', 'b']))
        self.assertEqual(client.http.post.call_count, 0)

    def test_delivery_failure_is_reported_to_the_caller(self):
        client = app.Client(0)
        client.http.post = Mock(return_value=Mock(ok=False, status_code=429))
        self.assertFalse(client.telegram_many('token', 'chat', ['hello']))

    def test_quiet_telegram_does_not_raise(self):
        client = app.Client(0)
        client.http.post = Mock(side_effect=app.requests.RequestException('boom'))
        self.assertFalse(client.telegram('t', 'c', 'hi', quiet=True))
