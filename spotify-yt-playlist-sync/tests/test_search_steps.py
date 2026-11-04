import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from syncer import app, search_steps


def track(tid, name, *artists, duration_ms=None):
    item = {'id': tid, 'name': name, 'artists': [{'name': a} for a in artists]}
    if duration_ms:
        item['duration_ms'] = duration_ms
    return item


class Catalog:
    """A tiny fake Spotify: search returns tracks that share a word with the query."""

    def __init__(self, tracks):
        self.tracks = tracks
        self.queries = []
        self.existing = set()

    def search(self, artist, title, token):
        self.queries.append((artist, title))
        words = set(app.normalized(f'{artist} {title}').split())
        hits = []
        for item in self.tracks:
            text = app.normalized(' '.join([item['name']] + [a['name'] for a in item['artists']]))
            if words & set(text.split()):
                hits.append(item)
        return hits

    def existing_tracks(self, playlist, token):
        return set(self.existing)

    def search_calls(self):
        return len(self.queries)


def video(title, channel='Uploader'):
    return {'id': 'VIDEOID0001', 'title': title, 'channel': channel, 'description': ''}


class StepTestCase(unittest.TestCase):
    def run_step(self, step_class, video_item, catalog):
        parsed = app.metadata(video_item)
        step = step_class(video_item, parsed, {})
        self.assertTrue(step.applies(), f'{step_class.code} does not apply to {video_item["title"]!r}')
        return step.run(catalog, 'token'), parsed


class ReversedCreditStepTests(StepTestCase):
    def test_song_then_artists_is_matched(self):
        video_item = video('QUERO AMOR - SXYGX x FYU')
        catalog = Catalog([track('t1', 'QUERO AMOR', 'SXYGX', 'FYU')])
        found, parsed = self.run_step(search_steps.ReversedCreditStep, video_item, catalog)
        self.assertEqual(parsed, ('SXYGX x FYU', 'QUERO AMOR'))
        self.assertEqual(found['id'], 't1')

    def test_a_different_version_is_refused(self):
        video_item = video('QUERO AMOR - SXYGX x FYU')
        # Only the plain original is on Spotify: a slowed/edited video must not
        # be added as another recording.
        video_item['title'] = 'QUERO AMOR (Slowed) - SXYGX x FYU'
        catalog = Catalog([track('t1', 'QUERO AMOR', 'SXYGX')])
        found, _ = self.run_step(search_steps.ReversedCreditStep, video_item, catalog)
        self.assertIsNone(found)


class SingleArtistStepTests(StepTestCase):
    def test_one_member_of_a_collab_is_enough(self):
        video_item = video('MONTAGEM RUNE - WUYS x KIT')
        catalog = Catalog([track('t1', 'MONTAGEM RUNE', 'WUYS')])
        found, _ = self.run_step(search_steps.SingleArtistStep, video_item, catalog)
        self.assertEqual(found['id'], 't1')


class MarketingSuffixStepTests(StepTestCase):
    def test_marketing_suffix_is_cut(self):
        video_item = video('DESTELLO - HDN | VIRAL PHONK')
        catalog = Catalog([track('t1', 'HDN', 'DESTELLO')])
        found, parsed = self.run_step(search_steps.MarketingSuffixStep, video_item, catalog)
        self.assertEqual(parsed, ('DESTELLO', 'HDN | VIRAL PHONK'))
        self.assertEqual(found['id'], 't1')

    def test_a_real_title_with_funk_keeps_it(self):
        video_item = video('DJ X - FUNK MANDALA | PHONK')
        catalog = Catalog([track('t1', 'FUNK MANDALA', 'DJ X')])
        found, _ = self.run_step(search_steps.MarketingSuffixStep, video_item, catalog)
        self.assertEqual(found['id'], 't1')


class CountryVariantStepTests(StepTestCase):
    def test_accents_do_not_matter(self):
        video_item = video('CORTA NO SALÃO (Slowed)')
        catalog = Catalog([track('t1', 'CORTA NO SALAO - Slowed', 'Artist')])
        found, _ = self.run_step(search_steps.CountryVariantStep, video_item, catalog)
        self.assertEqual(found['id'], 't1')

    def test_ascii_titles_do_not_use_the_step(self):
        step = search_steps.CountryVariantStep(video('PLAIN SONG'), app.metadata(video('PLAIN SONG')), {})
        self.assertFalse(step.applies())


class TopicChannelStepTests(unittest.TestCase):
    def test_topic_channel_gives_the_artist(self):
        video_item = video('SHAKA (SLOWED)', channel='SHAKA - Topic')
        catalog = Catalog([track('t1', 'SHAKA - Slowed', 'SHAKA')])
        step = search_steps.TopicChannelStep(video_item, app.metadata(video_item), {})
        self.assertEqual(step.run(catalog, 'token')['id'], 't1')


class DurationCheckStepTests(StepTestCase):
    def test_the_closest_duration_wins(self):
        video_item = video('MONTAGEM MIAU (Slowed)')
        video_item['duration_ms'] = 120000
        catalog = Catalog([
            track('short', 'Montagem Miau - Slowed', 'A', duration_ms=88000),
            track('right', 'Montagem Miau - Slowed', 'B', duration_ms=121000),
        ])
        found, _ = self.run_step(search_steps.DurationCheckStep, video_item, catalog)
        self.assertEqual(found['id'], 'right')

    def test_without_a_duration_the_step_stays_out(self):
        video_item = video('MONTAGEM MIAU (Slowed)')
        catalog = Catalog([track('t1', 'Montagem Miau - Slowed', 'A', duration_ms=120000)])
        found, _ = self.run_step(search_steps.DurationCheckStep, video_item, catalog)
        self.assertIsNone(found)


class FeaturedCreditStepTests(StepTestCase):
    def test_the_featured_artist_is_searched(self):
        video_item = video('FUNK TONTO (feat. Mc Ombrinho) [Slowed]')
        catalog = Catalog([track('t1', 'FUNK TONTO (feat. Mc Ombrinho) - Slowed', 'Mc Ombrinho')])
        found, parsed = self.run_step(search_steps.FeaturedCreditStep, video_item, catalog)
        self.assertEqual(found['id'], 't1')
        self.assertEqual(parsed[0], 'Mc Ombrinho')


class ShortTitleStepTests(StepTestCase):
    def test_a_three_letter_title_needs_the_same_artist(self):
        video_item = video('LUZ', channel='LUZ')
        catalog = Catalog([track('t1', 'LUZ', 'LUZ')])
        found, _ = self.run_step(search_steps.ShortTitleStep, video_item, catalog)
        self.assertEqual(found['id'], 't1')

    def test_an_unknown_artist_is_refused(self):
        # The channel is "HDN", the Spotify artist is somebody else: not enough
        # evidence for a three-letter title, so the song is left out.
        video_item = video('LUZ', channel='HDN')
        catalog = Catalog([track('t1', 'LUZ', 'Somebody Else')])
        found, _ = self.run_step(search_steps.ShortTitleStep, video_item, catalog)
        self.assertIsNone(found)


class SlowStepTests(StepTestCase):
    def test_only_slowed_tracks_are_accepted(self):
        video_item = video('FUNK ABNORMAL (SLOWED)')
        catalog = Catalog([track('original', 'FUNK ABNORMAL', 'A')])
        found, _ = self.run_step(search_steps.SlowStep, video_item, catalog)
        self.assertIsNone(found, 'the original must never stand in for a slowed edit')

    def test_a_slowed_track_is_accepted(self):
        video_item = video('FUNK ABNORMAL (SLOWED)')
        catalog = Catalog([track('slowed', 'FUNK ABNORMAL - Slowed', 'A')])
        found, _ = self.run_step(search_steps.SlowStep, video_item, catalog)
        self.assertEqual(found['id'], 'slowed')

    def test_a_sped_up_track_is_refused(self):
        video_item = video('FUNK ABNORMAL (SLOWED)')
        catalog = Catalog([track('fast', 'FUNK ABNORMAL - Sped Up', 'A')])
        found, _ = self.run_step(search_steps.SlowStep, video_item, catalog)
        self.assertIsNone(found)


class WordSetStepTests(StepTestCase):
    def test_the_same_words_in_another_order(self):
        video_item = video('Funk Midu Shange')
        catalog = Catalog([track('t1', 'Midu Shange Funk', 'Artist')])
        found, _ = self.run_step(search_steps.WordSetStep, video_item, catalog)
        self.assertEqual(found['id'], 't1')


class StepChainTests(unittest.TestCase):
    def test_steps_are_skipped_when_they_do_not_apply(self):
        video_item = video('Artist - Song')
        parsed = app.metadata(video_item)
        codes = [step.code for step in search_steps.build_steps(video_item, parsed, {})]
        # No collab credit, no feat., no topic, no marketing suffix, long title.
        for absent in ('REVERSED', 'SINGLE', 'TOPIC', 'SUFFIX', 'FEAT', 'SHORT'):
            self.assertNotIn(absent, codes)
        self.assertIn('CHANNEL', codes)

    def test_a_failing_step_does_not_stop_the_chain(self):
        class Broken(Catalog):
            def search(self, artist, title, token):
                raise app.SyncError('Spotify search: network error')

        video_item = video('QUERO AMOR - SXYGX x FYU')
        parsed = app.metadata(video_item)
        state = {}
        found, code = search_steps.search_more(Broken([]), video_item, parsed, 'token', state)
        self.assertIsNone(found)
        self.assertIsNone(code)                     # nothing matched
        self.assertTrue(set(state.get('tried', [])) <= {step.code for step in search_steps.STEPS})

    def test_the_matching_step_is_named(self):
        video_item = video('DESTELLO - HDN | VIRAL PHONK')
        parsed = app.metadata(video_item)
        state = {}
        found, code = search_steps.search_more(
            Catalog([track('t1', 'HDN', 'DESTELLO')]), video_item, parsed, 'token', state)
        self.assertEqual(code, 'SUFFIX')
        self.assertEqual(found['id'], 't1')
        self.assertIn('SUFFIX', state['tried'])

    def test_every_step_has_a_unique_code_and_a_title(self):
        codes = [step.code for step in search_steps.STEPS]
        self.assertEqual(len(codes), len(set(codes)))
        self.assertGreaterEqual(len(codes), 15)
        for step in search_steps.STEPS:
            self.assertTrue(step.title, step.code)


class ExtraStepInSyncTests(unittest.TestCase):
    """A video only the new steps can match is added, and the log names the step."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = Path(self.tmp.name) / 'state.json'
        self.patch = patch.object(app, 'STATE_PATH', self.path)
        self.patch.start()
        self.addCleanup(self.patch.stop)

    def test_a_marketing_suffix_video_is_matched_by_the_new_steps(self):
        catalog = Catalog([track('t1', 'HDN', 'DESTELLO')])
        counts = {'add': 0, 'skip': 0, 'fail': 0}
        issues = []
        app.sync(catalog, [video('DESTELLO - HDN | VIRAL PHONK')], 'playlist', 'token',
                 {'version': 1, 'playlists': {}}, True, counts, issues=issues)
        self.assertEqual(counts['add'], 1)
        self.assertEqual(issues[-1]['method'], 'SUFFIX')
        self.assertEqual(issues[-1]['track_id'], 't1')


if __name__ == '__main__':
    unittest.main()
