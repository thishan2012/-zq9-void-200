"""Separate Spotify search steps, tried one after another after the original
three methods (STRICT, LOOSE, DETAIL).

Each step is a small, independent experiment: it decides on its own whether it
applies to a video, does a couple of searches, and accepts a result only when it
is sure. A step can be measured, fixed or removed without touching the others,
and every report line names the step that matched.

Rule that all steps share: the *recording* must be the same one. A "Slowed"
video may only ever be added as that exact slowed edit - never as the original,
a sped-up version, a remix, or a different slowed step.
"""
import re

from difflib import SequenceMatcher

from . import app


# --------------------------------------------------------------------------
# shared helpers
# --------------------------------------------------------------------------

def track_title(track):
    return app.canonical_track_title(app.strip_marketing(track.get('name', '')))


def track_artists(track):
    names = set()
    for artist in track.get('artists', []):
        if isinstance(artist, dict) and artist.get('name'):
            names.add(app.normalized(artist['name']))
    return names - {''}


def version_ok(version_text, track):
    """Same edit only: an identical version, or one step up the slowed ladder."""
    return (app.versions_agree(version_text, track.get('name', ''))
            or app.upgraded_edit(version_text, track.get('name', '')))


def unique(candidates):
    seen, ordered = set(), []
    for track in candidates:
        if isinstance(track, dict) and track.get('id') and track.get('name') and track['id'] not in seen:
            seen.add(track['id'])
            ordered.append(track)
    return ordered


def best(candidates, score, floor):
    """Highest scoring candidate, but only when it clearly beats the runner-up."""
    ranked = sorted(((score(track), track) for track in unique(candidates)), key=lambda item: item[0],
                    reverse=True)
    if not ranked or ranked[0][0] < floor:
        return None
    if len(ranked) > 1 and ranked[0][0] - ranked[1][0] < .05:
        return None
    return ranked[0][1]


def known_artists(step):
    """Artists the *title* credits. A name that only the channel gave us does
    not count: it would turn "uploaded by A, made by B" into a false conflict."""
    names = app.artist_candidates(step.parsed[0]) if step.parsed else []
    channel_keys = {app.normalized(name) for name in app.channel_names(None, step.video)}
    strong = [name for name in names if app.normalized(name) not in channel_keys]
    return {app.normalized(name) for name in strong} - {''}

def artist_ok(step, track):
    """No conflict with the artists the video credits.

    When the title credits an artist and Spotify credits somebody else, that is
    a conflict - adding "DESTELLO - HDN" as a different artist's "HDN" would be
    a wrong song. When nothing is known, the step is allowed (the title may not
    carry a credit at all).
    """
    known = known_artists(step)
    return not known or bool(known & track_artists(track))

def name_matches(expected, track, floor=.93):
    """Title equality that survives accents, case and punctuation."""
    left = app.ascii_fold(app.normalized(expected))
    right = app.ascii_fold(track_title(track))
    if not left or not right:
        return False
    return left == right or SequenceMatcher(None, left, right).ratio() >= floor


def one_of(candidates):
    """The single candidate, or None when it is ambiguous."""
    items = unique(candidates)
    return items[0] if len(items) == 1 else None


class Step:
    """One named search experiment."""

    code = ''
    title = ''

    def __init__(self, video, parsed, state):
        self.video = video
        self.parsed = parsed            # (artist, title) or None
        self.state = state              # shared per-video dict, kept for debugging
        self.searches = []

    @property
    def version_text(self):
        """The title side that carries the version words ("… (Slowed)")."""
        return self.parsed[1] if self.parsed else self.video['title']

    def search(self, client, token, artist, title):
        """One Spotify query (the client caches identical queries per run)."""
        self.searches.append((artist, title))
        return client.search(artist, title, token)

    def applies(self):
        return True

    def run(self, client, token):
        """Return a matching track, or None."""
        raise NotImplementedError

    def version_checked(self, candidates):
        return [track for track in candidates if version_ok(self.version_text, track)]

    def named(self, candidates, floor=.92):
        return [track for track in self.version_checked(candidates) if name_matches(self.version_text, track, floor)]


# --------------------------------------------------------------------------
# the steps
# --------------------------------------------------------------------------

class ReversedCreditStep(Step):
    code = 'REVERSED'
    title = 'Artist credit on the right of the dash ("Song - SXYGX x FYU")'

    def applies(self):
        return bool(self.parsed and app.is_collab_credit(self.parsed[0]))

    def run(self, client, token):
        artist, song = self.parsed
        candidates = []
        for name in app.artist_candidates(artist):
            candidates += self.search(client, token, name, song)
        candidates += self.search(client, token, '', song)
        return best(self.version_checked(candidates),
                    lambda track: SequenceMatcher(None, app.normalized(song), track_title(track)).ratio(),
                    floor=.90)


class SingleArtistStep(Step):
    code = 'SINGLE'
    title = 'Collab credit searched one artist at a time'

    def applies(self):
        return bool(self.parsed and len(app.artist_candidates(self.parsed[0])) > 1)

    def run(self, client, token):
        song = self.parsed[1]
        candidates = []
        for name in app.artist_candidates(self.parsed[0]):
            for track in self.search(client, token, name, song):
                if app.normalized(name) in track_artists(track):
                    candidates.append(track)
        return best(self.version_checked(candidates),
                    lambda track: SequenceMatcher(None, app.normalized(song), track_title(track)).ratio(),
                    floor=.90)


class ChannelSearchStep(Step):
    code = 'CHANNEL'
    title = 'Uploader/channel name used as the artist'

    def applies(self):
        return bool(app.channel_names(self.parsed, self.video))

    def run(self, client, token):
        candidates = []
        for name in app.channel_names(self.parsed, self.video)[:3]:
            candidates += self.search(client, token, name, self.version_text)
        return one_of(self.named(candidates, floor=.90))


class TopicChannelStep(Step):
    code = 'TOPIC'
    title = '"Artist - Topic" channels carry the real artist name'

    def applies(self):
        return bool(re.fullmatch(r'(.+?)\s*-\s*Topic', self.video.get('channel', ''), flags=re.I))

    def run(self, client, token):
        artist = re.fullmatch(r'(.+?)\s*-\s*Topic', self.video['channel'], flags=re.I).group(1).strip()
        # A Topic upload is usually named "Song" or "Artist - Song".
        title = self.parsed[0] if self.parsed and app.title_similarity(
            self.parsed[0], self.video['title']) > .8 else self.version_text
        candidates = self.search(client, token, artist, title)
        keep = [track for track in self.version_checked(candidates)
                if name_matches(title, track, floor=.90)
                and app.normalized(artist) in track_artists(track)]
        return one_of(keep)


class MarketingSuffixStep(Step):
    code = 'SUFFIX'
    title = 'Cut uploader marketing off the title ("HDN | VIRAL PHONK")'

    def applies(self):
        return app.normalized(app.strip_marketing(self.version_text)) != app.normalized(self.version_text)

    def run(self, client, token):
        song = app.strip_marketing(self.version_text)
        candidates = []
        for artist in app.channel_names(self.parsed, self.video)[:2] + ['']:
            candidates += self.search(client, token, artist, song)
        keep = [track for track in self.version_checked(candidates)
                if name_matches(song, track, floor=.90) and artist_ok(self, track)]
        return one_of(keep)


class CountryVariantStep(Step):
    code = 'COUNTRY'
    title = 'Accent/country variants of the same words ("Salão" ↔ "Salao", "Ł" ↔ "L")'

    def applies(self):
        text = ' '.join([self.version_text] + app.channel_names(self.parsed, self.video)[:2])
        return not text.isascii()

    def run(self, client, token):
        song = app.ascii_fold(app.strip_marketing(self.version_text))
        candidates = []
        for artist in app.channel_names(self.parsed, self.video)[:2] + ['']:
            candidates += self.search(client, token, artist, song)
        keep = [track for track in self.version_checked(candidates)
                if app.ascii_fold(track_title(track)) == app.ascii_fold(app.canonical_track_title(song))
                and artist_ok(self, track)]
        return one_of(keep)


class FeaturedCreditStep(Step):
    code = 'FEAT'
    title = 'Featured artist used as the main artist ("(feat. X)")'

    FEAT = re.compile(r'[\[(]\s*(?:feat(?:uring)?|ft)\.?\s+([^\])}]*)[\])}]', re.I)

    def applies(self):
        return bool(self.FEAT.search(self.version_text))

    def run(self, client, token):
        found = self.FEAT.search(self.version_text)
        candidates = []
        for artist in app.artist_candidates(found.group(1))[:2]:
            candidates += self.search(client, token, artist, self.version_text)
            candidates += self.search(client, token, artist, app.strip_marketing(self.version_text))
        keep = [track for track in self.version_checked(candidates)
                if name_matches(self.version_text, track, floor=.88)]
        return one_of(keep)


class DurationCheckStep(Step):
    code = 'DURATION'
    title = 'Same title, several versions: choose by video duration'

    def run(self, client, token):
        video_ms = self.video.get('duration_ms')
        if not isinstance(video_ms, (int, float)) or isinstance(video_ms, bool) or video_ms <= 0:
            return None
        candidates = self.search(client, token, '', self.version_text)
        scored = []
        for track in self.named(candidates, floor=.90):
            track_ms = track.get('duration_ms')
            if not isinstance(track_ms, (int, float)) or isinstance(track_ms, bool) or track_ms <= 0:
                continue
            difference = abs(video_ms - track_ms)
            if difference <= max(5000, video_ms * .02):
                scored.append((difference, track))
        scored.sort(key=lambda item: item[0])
        if not scored:
            return None
        if len(scored) > 1 and scored[0][0] > 1000 and scored[1][0] - scored[0][0] < 2000:
            return None
        return scored[0][1]


class SearchByEachArtistStep(Step):
    code = 'ARTISTS'
    title = 'The title searched with every credited artist until one fits'

    def applies(self):
        return bool(self.parsed)

    def run(self, client, token):
        for artist in app.artist_candidates(self.parsed[0])[:4]:
            keep = [track for track in self.named(
                        self.search(client, token, artist, self.version_text), floor=.92)
                    if app.normalized(artist) in track_artists(track)]
            if len(keep) == 1:
                return keep[0]
        return None


class ShortTitleStep(Step):
    code = 'SHORT'
    title = 'Very short titles ("LUZ", "AWE") accepted only with a known artist'

    def applies(self):
        return len(app.normalized(app.strip_marketing(self.version_text))) <= 3

    def run(self, client, token):
        song = app.strip_marketing(self.version_text)
        known = {app.normalized(name) for name in
                 (app.artist_candidates(self.parsed[0]) if self.parsed else [])
                 + app.channel_names(self.parsed, self.video)}
        candidates = []
        for artist in app.channel_names(self.parsed, self.video)[:3] + ['']:
            candidates += self.search(client, token, artist, song)
        keep = [track for track in self.version_checked(candidates)
                if app.normalized(track_title(track)) == app.normalized(song)
                and track_artists(track) & known]
        return one_of(keep)


class EmptySearchStep(Step):
    code = 'ARTISTLESS'
    title = 'Title-only search (the artists are unknown or wrong on both sides)'

    def run(self, client, token):
        song = app.strip_marketing(self.version_text)
        candidates = self.search(client, token, '', song)
        keep = [track for track in self.version_checked(candidates)
                if app.ascii_fold(track_title(track)) == app.ascii_fold(app.canonical_track_title(song))
                and artist_ok(self, track)]
        return one_of(keep)


class ExactTitleStep(Step):
    code = 'EXACT'
    title = 'Words compared without version labels (versions must still agree)'

    def run(self, client, token):
        song = app.search_core(self.version_text)
        if len(song) < 3:
            return None
        candidates = self.search(client, token, '', song)
        keep = [track for track in self.version_checked(candidates)
                if app.search_core(track.get('name', '')) == song and artist_ok(self, track)]
        return one_of(keep)


class WordSetStep(Step):
    code = 'WORDSET'
    title = 'Same words in another order ("Midu Shange Funk" ↔ "Funk Midu Shange")'

    def run(self, client, token):
        song = app.search_core(self.version_text)
        words = set(song.split())
        if len(words) < 2:
            return None
        candidates = self.search(client, token, '', song)
        keep = [track for track in self.version_checked(candidates)
                if len(words & set(app.search_core(track.get('name', '')).split())) >= max(2, len(words) - 1)
                and artist_ok(self, track)]
        return one_of(keep)


class SlowStep(Step):
    code = 'SLOWED'
    title = 'A slowed edit of the same song searched explicitly (Slowed only, never the original)'

    def applies(self):
        return 'slowed' in app.version_tokens(self.version_text)

    def run(self, client, token):
        song = app.search_core(self.version_text)
        if len(song) < 3:
            return None
        candidates = self.search(client, token, '', f'{song} slowed')
        keep = [track for track in candidates
                if 'slowed' in app.version_tokens(track.get('name', ''))
                and app.search_core(track.get('name', '')) == song
                and artist_ok(self, track)]
        return one_of(keep)


class UploaderSearchStep(Step):
    code = 'UPLOADER'
    title = 'Uploader name and title in one query'

    def applies(self):
        return bool(app.channel_names(self.parsed, self.video))

    def run(self, client, token):
        channel = app.channel_names(self.parsed, self.video)[0]
        candidates = self.search(client, token, '', f'{channel} {app.strip_marketing(self.version_text)}')
        keep = [track for track in self.version_checked(candidates) if name_matches(self.version_text, track, floor=.90)]
        return one_of(keep)


STEPS = (
    ReversedCreditStep,      # 1
    SingleArtistStep,        # 2
    ChannelSearchStep,       # 3
    TopicChannelStep,        # 4
    MarketingSuffixStep,     # 5
    CountryVariantStep,      # 6
    FeaturedCreditStep,      # 7
    DurationCheckStep,       # 8
    SearchByEachArtistStep,  # 9
    ShortTitleStep,          # 10
    EmptySearchStep,         # 11
    ExactTitleStep,          # 12
    WordSetStep,             # 13
    SlowStep,                # 14
    UploaderSearchStep,      # 15
)


# Codes of the extra steps (used by the report).
CODES = frozenset(step.code for step in STEPS)

def build_steps(video, parsed, state):
    """Instantiate the steps that apply to this video, in order."""
    built = []
    for step_class in STEPS:
        step = step_class(video, parsed, state)
        if step.applies():
            built.append(step)
    return built


def search_more(client, video, parsed, token, state):
    """Run the extra steps in order. Returns (track, step code) or (None, None).

    A step that hits a network error is skipped instead of stopping the run, and
    the codes that were tried are kept in `state['tried']` for the report.
    """
    tried = state.setdefault('tried', [])
    for step in build_steps(video, parsed, state):
        try:
            track = step.run(client, token)
        except app.SyncError:
            continue
        tried.append(step.code)
        if track:
            return track, step.code
    return None, None
