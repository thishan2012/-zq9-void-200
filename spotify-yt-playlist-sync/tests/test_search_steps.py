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


def video(title, channel='Uploader', description=''):
    return {'id': 'VIDEOID0001', 'title': title, 'channel': channel, 'description': description}


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


class BrokenCreditStepTests(StepTestCase):
    """A "Song - Artist" title whose halves are written the other way round."""

    def test_the_swap_is_matched_when_the_uploader_is_that_artist(self):
        video_item = video('DESTELLO - HDN', channel='HDN🎹')
        catalog = Catalog([track('t1', 'DESTELLO', 'HDN')])
        found, _ = self.run_step(search_steps.BrokenCreditStep, video_item, catalog)
        self.assertEqual(found['id'], 't1')

    def test_a_different_artist_is_still_refused(self):
        video_item = video('DESTELLO - HDN', channel='Some Uploader')
        catalog = Catalog([track('t1', 'DESTELLO', 'HDN')])
        found, _ = self.run_step(search_steps.BrokenCreditStep, video_item, catalog)
        self.assertIsNone(found)

    def test_a_real_song_title_is_not_swapped(self):
        video_item = video('DJ X - MONTAGEM DA NOITE INTEIRA', channel='DJ X')
        catalog = Catalog([track('t1', 'MONTAGEM DA NOITE INTEIRA', 'DJ X')])
        found, _ = self.run_step(search_steps.BrokenCreditStep, video_item, catalog)
        self.assertIsNone(found)


class FeaturedNameTests(unittest.TestCase):
    """The featured credit inside a title is not part of the song's name."""

    def test_a_feat_block_does_not_stop_the_title_match(self):
        self.assertTrue(search_steps.name_matches(
            'FUNK TONTO (feat. Mc Ombrinho) [Slowed]',
            {'name': 'FUNK TONTO - Slowed', 'artists': [{'name': 'Mc Ombrinho'}]}))

    def test_version_words_survive_a_bare_feat_credit(self):
        self.assertEqual(app.version_signature(search_steps.without_feat(
            'FUNK TONTO feat. MC OMBRINHO Slowed')), {'slowed'})

    def test_the_song_on_a_slowed_album_is_found(self):
        video_item = video('FUNK TONTO (feat. Mc Ombrinho) [Slowed]', channel='Raiden - Topic',
                           description='Provided to YouTube by X\n\nFUNK TONTO · MC Ombrinho')
        catalog = Catalog([dict(track('t1', 'FUNK TONTO', 'MC Ombrinho'), album='FUNK TONTO (Slowed)')])
        found, code = search_steps.search_more(catalog, video_item, app.metadata(video_item), 'token', {})
        self.assertEqual((found['id'], code), ('t1', 'PART'))


class DescriptionCreditTests(unittest.TestCase):
    """Distributor pages state the artist in the description, not in the title."""

    TONTO = 'Provided to YouTube by DistroKid\n\nFUNK TONTO · MC Ombrinho\n\n℗ 2026'

    def test_the_song_line_of_the_description_gives_the_artist(self):
        parsed = app.metadata(video('FUNK TONTO (feat. Mc Ombrinho) [Slowed]', channel='Raiden - Topic',
                                    description=self.TONTO))
        self.assertEqual(parsed, ('MC Ombrinho', 'FUNK TONTO (feat. Mc Ombrinho) [Slowed]'))

    def test_the_version_words_stay_part_of_the_song(self):
        _, song = app.metadata(video('MONTAGEM GALACTO LOCONA (Ultra Slowed)', channel='Release - Topic',
                                     description='Provided to YouTube by X\n\nMONTAGEM GALACTO LOCONA · DJ NEO'))
        self.assertEqual(app.version_signature(song), {'ultra-slowed', 'slowed'})

    def test_a_description_about_another_song_is_ignored(self):
        parsed = app.metadata(video('MONTAGEM GALACTO LOCONA (Ultra Slowed)', channel='Release - Topic',
                                    description='Provided to YouTube by X\n\nMONTAGEM ECLIPSE · DJ NEO'))
        self.assertIsNone(parsed)

    def test_the_description_artist_decides_the_match(self):
        video_item = video('FUNK TONTO (feat. Mc Ombrinho) [Slowed]', channel='Raiden - Topic',
                           description=self.TONTO)
        catalog = Catalog([dict(track('t1', 'FUNK TONTO, Pt. 2 (feat. Mc Ombrinho)', 'Mc Ombrinho'),
                                album='FUNK TONTO (Slowed)')])
        parsed = app.metadata(video_item)
        found, code = search_steps.search_more(catalog, video_item, parsed, 'token', {})
        self.assertEqual((found['id'], code), ('t1', 'PART'))

    def test_a_wrong_artist_in_the_description_is_refused(self):
        video_item = video('FUNK TONTO (feat. Mc Ombrinho) [Slowed]', channel='Raiden - Topic',
                           description=self.TONTO)
        catalog = Catalog([dict(track('t1', 'FUNK TONTO, Pt. 2 (feat. Mc Ombrinho)', 'Somebody Else'),
                                album='FUNK TONTO (Slowed)')])
        parsed = app.metadata(video_item)
        found, _ = search_steps.search_more(catalog, video_item, parsed, 'token', {})
        self.assertIsNone(found)


class TopicReleaseChannelTests(unittest.TestCase):
    """A "Release - Topic" page is not an artist; a named one is."""

    def test_a_compilation_page_says_nothing_about_the_artist(self):
        video_item = video('MONTAGEM GALACTO LOCONA (Ultra Slowed)', channel='Release - Topic')
        self.assertIsNone(app.metadata(video_item))
        self.assertEqual(app.channel_names(None, video_item), [])

    def test_a_named_topic_channel_is_the_artist(self):
        video_item = video('SHAKA (SLOWED)', channel='HDN - Topic')
        self.assertEqual(app.metadata(video_item), ('HDN', 'SHAKA (SLOWED)'))

    def test_a_compilation_title_is_not_read_as_a_credit(self):
        video_item = video('MONTAGEM GALACTO LOCONA (Ultra Slowed)', channel='Release - Topic')
        catalog = Catalog([track('t1', 'MONTAGEM GALACTO LOCONA - Ultra Slowed', 'DJ NEO')])
        found, _ = self.run_steps(video_item, catalog)
        self.assertEqual(found['id'], 't1')

    def test_a_wrong_song_is_still_refused(self):
        video_item = video('MONTAGEM GALACTO LOCONA (Ultra Slowed)', channel='Release - Topic')
        catalog = Catalog([track('t1', 'MONTAGEM ECLIPSE - Ultra Slowed', 'DJ NEO')])
        found, _ = self.run_steps(video_item, catalog)
        self.assertIsNone(found)

    def run_steps(self, video_item, catalog):
        parsed = app.metadata(video_item)
        self.assertIsNone(parsed, 'a release page must not become an artist credit')
        # search_more returns (track, method code).
        return search_steps.search_more(catalog, video_item, parsed, 'token', {})


class UploaderNameTests(unittest.TestCase):
    """An uploader decoration must not hide the artist name."""

    def test_a_glyph_in_the_channel_name_is_not_part_of_it(self):
        names = app.channel_names(('DESTELLO', 'HDN | VIRAL PHONK'), {'channel': 'HDN🎹'})
        self.assertEqual(names, ['DESTELLO', 'HDN'])

    def test_an_upload_suffix_and_a_topic_channel_are_stripped(self):
        self.assertEqual(app.channel_names(None, {'channel': 'HDN Music'}), ['HDN'])
        self.assertEqual(app.channel_names(None, {'channel': 'Raiden - Topic'}), ['Raiden'])

    def test_a_name_with_nothing_left_is_not_a_search_term(self):
        self.assertEqual(app.channel_names(None, {'channel': '★☆'}), [])

    def test_a_pasted_filename_dot_is_not_an_artist_name(self):
        self.assertEqual(app.artist_candidates('Signals.'), ['Signals'])
        self.assertEqual(app.artist_candidates('Mr.Kitty'), ['Mr.Kitty'])


class AlbumAwareStepTests(StepTestCase):
    def test_the_slowed_edit_living_on_a_slowed_album_wins(self):
        video_item = video('MONTAGEM ZEPHYR (Slowed)')
        catalog = Catalog([track('plain', 'Montagem Zephyr', 'X'),
                           dict(track('slowed', 'Montagem Zephyr - Slowed', 'X'), album='Slowed Hits')])
        found, _ = self.run_step(search_steps.AlbumAwareStep, video_item, catalog)
        self.assertEqual(found['id'], 'slowed')


class PartSuffixStepTests(StepTestCase):
    def test_pt_2_is_the_same_song(self):
        video_item = video('FUNK TONTO (feat. Mc Ombrinho) [Slowed]')
        # Spotify splits feat. tracks into "Pt. 2" releases.
        catalog = Catalog([dict(track('pt2', 'FUNK TONTO, Pt. 2 (feat. Mc Ombrinho)', 'Mc Ombrinho'),
                                album='FUNK TONTO (Slowed)')])
        found, _ = self.run_step(search_steps.PartSuffixStep, video_item, catalog)
        self.assertEqual(found['id'], 'pt2')

    def test_a_different_number_is_still_a_different_song(self):
        video_item = video('MONTAGEM ZEPHYR')
        catalog = Catalog([track('other', 'MONTAGEM NEBULA, Pt. 2', 'X')])
        found, _ = self.run_step(search_steps.PartSuffixStep, video_item, catalog)
        self.assertIsNone(found)


class SlowStepRungTests(StepTestCase):
    """The SLOWED step may change the rung of the ladder, never the song."""

    def test_a_plain_slowed_edit_is_taken_for_an_ultra_slowed_video(self):
        video_item = video('MONTAGEM GALACTO LOCONA (Ultra Slowed)')
        catalog = Catalog([track('t1', 'MONTAGEM GALACTO LOCONA - Slowed', 'DJ NEO')])
        found, _ = self.run_step(search_steps.SlowStep, video_item, catalog)
        self.assertEqual(found['id'], 't1')

    def test_the_original_is_never_taken(self):
        video_item = video('MONTAGEM GALACTO LOCONA (Ultra Slowed)')
        catalog = Catalog([track('t1', 'MONTAGEM GALACTO LOCONA', 'DJ NEO')])
        found, _ = self.run_step(search_steps.SlowStep, video_item, catalog)
        self.assertIsNone(found)

    def test_two_different_rungs_stay_ambiguous(self):
        video_item = video('MONTAGEM GALACTO LOCONA (Ultra Slowed)')
        catalog = Catalog([dict(track('a', 'MONTAGEM GALACTO LOCONA - Slowed', 'DJ NEO'), popularity=5),
                           dict(track('b', 'MONTAGEM GALACTO LOCONA - Super Slowed', 'DJ NEO'), popularity=7)])
        found, _ = self.run_step(search_steps.SlowStep, video_item, catalog)
        self.assertIsNone(found)


class PopularRankStepTests(StepTestCase):
    def test_the_most_played_of_two_equal_titles_wins(self):
        video_item = video('MONTAGEM ZEPHYR')
        catalog = Catalog([dict(track('a', 'MONTAGEM ZEPHYR', 'X'), popularity=900),
                           dict(track('b', 'MONTAGEM ZEPHYR', 'X'), popularity=940000)])
        found, _ = self.run_step(search_steps.PopularRankStep, video_item, catalog)
        self.assertEqual(found['id'], 'b')

    def test_a_tie_stays_a_skip(self):
        video_item = video('MONTAGEM ZEPHYR')
        catalog = Catalog([dict(track('a', 'MONTAGEM ZEPHYR', 'X'), popularity=500),
                           dict(track('b', 'MONTAGEM ZEPHYR', 'X'), popularity=500)])
        found, _ = self.run_step(search_steps.PopularRankStep, video_item, catalog)
        self.assertIsNone(found)


class TopResultStepTests(StepTestCase):
    """The last resort: the first result, but only when it really is the song."""

    def test_the_first_result_is_taken_when_title_and_version_match(self):
        video_item = video('MONTAGEM ZEPHYR (Slowed)')
        catalog = Catalog([track('first', 'Montagem Zephyr - Slowed', 'Someone'),
                           track('second', 'Other Song', 'X')])
        found, _ = self.run_step(search_steps.TopResultStep, video_item, catalog)
        self.assertEqual(found['id'], 'first')

    def test_a_different_song_with_one_shared_word_is_refused(self):
        video_item = video('MONTAGEM ZEPHYR (Slowed)')
        catalog = Catalog([track('wrong', 'Montagem Nebula - Slowed', 'X')])
        found, _ = self.run_step(search_steps.TopResultStep, video_item, catalog)
        self.assertIsNone(found)

    def test_the_original_is_never_taken_for_a_slowed_video(self):
        video_item = video('MONTAGEM ZEPHYR (Slowed)')
        catalog = Catalog([track('original', 'MONTAGEM ZEPHYR', 'X')])
        found, _ = self.run_step(search_steps.TopResultStep, video_item, catalog)
        self.assertIsNone(found)

    def test_an_artist_conflict_is_refused(self):
        video_item = video('DESTELLO - HDN | VIRAL PHONK')
        catalog = Catalog([track('wrong', 'HDN', 'Somebody Else')])
        found, _ = self.run_step(search_steps.TopResultStep, video_item, catalog)
        self.assertIsNone(found)

    def test_word_order_and_accents_do_not_matter(self):
        video_item = video('CORTA NO SALÃO (Slowed)')
        catalog = Catalog([track('first', 'Salao Corta No - Slowed', 'X')])
        found, _ = self.run_step(search_steps.TopResultStep, video_item, catalog)
        self.assertEqual(found['id'], 'first')

    def test_it_is_the_last_step_in_the_chain(self):
        self.assertIs(search_steps.STEPS[-1], search_steps.TopResultStep)


class ExplainTests(unittest.TestCase):
    """--explain must say what Spotify returned for a skipped song."""

    def test_explain_prints_the_songs_and_its_results(self):
        import contextlib, io, json, os
        state = {'version': 1, 'playlists': {'pl': {'videos': {}, 'pending': None, 'skipped': {
            'VIDEOID0001': {'title': 'MONTAGEM RUNE - WUYS x KIT', 'channel': 'U'}}}}}
        catalog = Catalog([track('t1', 'MONTAGEM RUNE', 'WUYS')])

        class FakeClient(Catalog):
            def token(self, cookie):
                return 'token'

        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        path = Path(tmp.name) / 'state.json'
        path.write_text(json.dumps(state), encoding='utf-8')
        buf = io.StringIO()
        with patch.object(app, 'STATE_PATH', path), patch.object(app, 'Client', lambda delay: FakeClient(catalog.tracks)), \
             patch.object(app, 'sp_dc_from_file', return_value='cookie'), \
             patch.dict(os.environ, {'REQUEST_DELAY_SECONDS': '0'}), contextlib.redirect_stdout(buf):
            self.assertEqual(app.explain(), 0)
        text = buf.getvalue()
        self.assertIn('MONTAGEM RUNE - WUYS x KIT', text)
        self.assertIn('parsed as:', text)
        self.assertIn('verdict:', text)

    def test_explain_without_skips_says_so(self):
        import contextlib, io
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            self.assertEqual(app.explain(state={'version': 1, 'playlists': {}}), 0)
        self.assertIn('No remembered skips', buf.getvalue())


class SavedEvidenceTests(unittest.TestCase):
    """--save-explain: a dry run keeps what Spotify said, and --explain reuses it."""

    def test_a_skipped_song_is_remembered_and_explained_without_searching(self):
        import contextlib, io
        video_item = {'id': 'VIDEOID0001', 'title': 'MONTAGEM ZEPHYR - X x Y',
                      'channel': 'Uploader', 'description': ''}
        catalog = Catalog([track('other', 'SOMETHING ELSE', 'Z')])
        catalog.keep_evidence = True
        state = {'version': 1, 'playlists': {}}
        counts = {'add': 0, 'skip': 0, 'fail': 0}
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        with patch.object(app, 'STATE_PATH', Path(tmp.name) / 'state.json'):
            app.sync(catalog, [video_item], 'pl', 'token', state, True, counts, issues=[])
        self.assertEqual(counts['skip'], 1)
        self.assertIn('VIDEOID0001', state['evidence'])

        # --explain now prints the saved attempts and never searches Spotify.
        catalog.queries.clear()
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            self.assertEqual(app.explain(state=state), 0)
        self.assertEqual(catalog.search_calls(), 0)
        self.assertIn('MONTAGEM ZEPHYR - X x Y', buf.getvalue())
        self.assertIn('still no match', buf.getvalue())


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
        self.assertGreaterEqual(len(codes), 20)
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
