# 🧠 06 — Code එක වැඩ කරන විදිය (A–Z)

`syncer/app.py` එකේ තියෙන හැම කොටසක්ම, පිළිවෙළින්.

## 1. එක run එකේ flow

```
main()
 ├─ REQUEST_DELAY_SECONDS / SPOTIFY_BATCH_SIZE validate (0–60 / 1–100)
 ├─ playlist_id(YOUTUBE_PLAYLIST, 'YouTube')      → PLxxxx
 ├─ playlist_id(SPOTIFY_PLAYLIST, 'Spotify')      → 22-char id
 ├─ YOUTUBE_API_KEY තියෙනවද?
 ├─ load_state(data/sync-state.json)              → {'version':1,'playlists':{}}
 ├─ load_overrides(data/track-overrides.json)
 ├─ sp_dc_from_file(cookies/spotify.txt)          → sp_dc value
 ├─ Client.youtube(key, playlist)                 → [ {id,title,channel,description,duration_ms} ]
 ├─ Client.token(cookie)                          → accessToken
 └─ sync(...)                                     → counts + issues
      ↓
 finally: summary + Telegram summary + Telegram full log
```

Exit code: සම්පූර්ණ success = `0`, fail/partial = `1`.

## 2. YouTube (`Client.youtube`)

```python
while True:                                  # pagination loop
    playlistItems.list(maxResults=50, pageToken=…)
    page = data['nextPageToken']             # නැත්නම් loop නවතිනවා
videos.list(ids=50)                          # 50 බැගින් description + duration
```
- Playlist ID එකේ duplicates තිබ්බත් එකම video එක දෙපාරක් process වෙන්නේ නෑ
- `youtube_duration_ms('PT3M1S')` → `181000` (DETAIL matching එකේදී විතරයි පාවිච්චි වෙන්නේ)

## 3. Spotify transport (`Client.request`)

- `requests.Session` + UA header, `timeout=30`
- `delay` → හැම request එකට කලින් `time.sleep(delay)`
- **Read** requests: 429/5xx → `Retry-After` (නැත්නම් 5s/10s/20s, cap 60s) → උපරිම 3 වතාවක්
- **Write** requests: retry **නෑ**. Timeout/5xx/invalid JSON → `UncertainWrite`
- Proxy එකට යවන්නේ `api.spotify.com` / `api-partner.spotify.com` විතරයි; redirects follow කරන්නේ නෑ
- Response bodies, URLs, headers **log කරන්නේ නෑ**

## 4. Backend selection (`existing_tracks`)

```
REST (proxy) ──fail(401/403/404/405/429/501)──► web-player (proxy) ──fail──► web-player (direct)
   │                                                  │
   └──────────── සාර්ථක backend එකෙන් writes ─────────┘
```
Fail closed: playlist එක කියවන්න බැරි නම් run එක නවතිනවා (duplicate risk එකට වඩා හොඳයි).

## 5. Matching (අදියර 3ක්)

| | Method | Search | Rule |
|---|---|---|---|
| 1 | `STRICT` | `artist + title` | canonical title == , version signature == , primary artist තියෙනවා |
| 2 | `LOOSE` | full video title | similarity ≥ 0.86, versions match, close tie (<0.05) → skip |
| 3 | `DETAIL` | core title (version words අයින්) | word order වෙනස් වුණත් OK; artist තියෙනවා නම් 0.86, නැත්නම් 0.93; duration `max(30s, 25%)` |

- `version_signature()`: `slowed`, `super/ultra/over/extra slowed`, `sped up`, `reverb`, `remix`, `live`, `instrumental`, `8d`, `nightcore`, `cover`, `radio`, `demo` … 28ක්
- `canonical_track_title()`: `(Official Video)`, `(Lyrics)` අයින් වෙනවා — **ඒත් `(Official Video - Slowed)` එකේ `Slowed` ඉතුරු වෙනවා**
- Result 2ක් සමාන නම් → **skip** (අහඹුවට තෝරන්නේ නෑ)

## 6. `sync()` — සින්දුවකට

```
1. pending reconcile (කලින් run එකේ අපැහැදිලි write එකක් තියෙනවා නම්)
2. video already recorded?        → SKIP "Already recorded in the sync database"
3. duplicate video in this run?   → SKIP
4. unavailable title?             → SKIP
5. override (manual)?             → MANUAL
   නැත්නම් STRICT → LOOSE → DETAIL → හම්බුනේ නෑ නම් SKIP
6. එකම track එක මේ run එකේ plan කරලද? → SKIP
7. track එක Spotify playlist එකේ තියෙනවද? → SKIP  (+ state එකේ record)
8. dry run? → WOULD ADD
9. නැත්නම් queue එකට → batch 100 පිරුණම flush
```

## 7. Batch add + pending (ලස්සනම කොටස)

```
queue 100 පිරෙනවා
   ↓
db['pending'] = {items:[{video,track}×100]}  → save_state  (කලින්ම ලියනවා!)
   ↓
add_batch(100 uris)          ← එක HTTP request
   ↓ සාර්ථක → state එකේ 100ම record, pending = None
   ↓ definite fail (4xx) → pending = None, 100ම FAIL (ඊළඟ run එකේ ආයේ උත්සාහ)
   ↓ ambiguous (timeout/5xx) → pending තියෙනවා, run නවතිනවා
```

ඊළඟ run එකේ මුලින්ම: pending items playlist එකේ තියෙනවද?
- ඔව් → record කරලා ඉදිරියට
- නෑ → **run නවතිනවා** (`check Spotify manually, then clear pending`)

👉 මේකයි "එකම song එක ආයේ ආයේ add නොවෙන්න" කියන එකේ ඇත්තම ආරක්ෂාව.

## 8. State (`data/sync-state.json`)

```json
{
  "version": 1,
  "playlists": {
    "26ADR9K06DZ826IsgTno1S": {
      "videos": { "FGys9rRBytU": "1R96NBIdXeLeYHvstCJV1J" },
      "pending": null
    }
  }
}
```
- `videos` = video ID → track ID (add වුණු ඒවා)
- `pending` = `null` හෝ `{"items":[{video,track}…]}`
- `save_state()` = temp file + atomic replace (කැඩුණු JSON එකකින් DB එක විනාශ වෙන්නේ නෑ)

## 9. Reporting

- `report_issue()` → `issues[]` (status, title, channel, video_id, reason, track_id, method)
- `telegram_messages()` → summary (SKIP/FAIL විතරයි)
- `activity_messages()` → **full log** (හැම event එකක්ම, `#n` index එකක් එක්ක)
- `utf16_chunks()` → Telegram 4096 limit එකට line boundary එකෙන් split

## 10. Files

```
syncer/app.py                 මුළු ලොජික් එකම (~900 lines)
data/sync-state.json          database
data/track-overrides.json     manual matches
cookies/spotify.txt           local cookie (git-ignored, workflow එකෙන් delete)
tests/                        65 unit tests
```
