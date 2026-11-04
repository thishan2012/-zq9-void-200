# 🧾 11 — Cheatsheet (එක පිටුව)

## Secrets (Settings → Secrets and variables → Actions → Secrets)

```text
YOUTUBE_API_KEY       = AIza…                       (required)
SPOTIFY_COOKIE        = <netscape cookies.txt, whole file>  (required)
YOUTUBE_PLAYLIST      = https://www.youtube.com/playlist?list=PL…   (required)
SPOTIFY_PLAYLIST      = https://open.spotify.com/playlist/…         (required)
TELEGRAM_BOT_TOKEN    = 123456:AAH…                 (optional)
TELEGRAM_CHAT_ID      = 123456789 / -100…           (optional)
```

## Variables (optional)

```text
REQUEST_DELAY_SECONDS = 2      (0–60; rate limit guard)
SPOTIFY_BATCH_SIZE    = 100    (1–100; tracks per add request)
```

## Defaults (දෙකම නැතුවත් වැඩ කරනවා)

| Setting | Default |
|---|---|
| `REQUEST_DELAY_SECONDS` | `2` |
| `SPOTIFY_BATCH_SIZE` | `100` |
| `SYNC_ENABLED` | unset (scheduled runs stay dry) |
| Schedule | `0 */4 * * *` UTC = දවසට 6 (05:30, 09:30, 13:30, 17:30, 21:30, 01:30 SL) |
| Job timeout | 180 min |
| Retries (reads) | 3, `Retry-After` respected |
| Retries (writes) | 0 — never |

## Numbers

| අගය | අර්ථය |
|---|---|
| 50 | YouTube page size (max) |
| 100 | Spotify URIs per add request (max) |
| 22 | Spotify playlist/track ID length |
| 11 | YouTube video ID length |

## Commands

```bash
# tests
python -m unittest discover -s tests -v

# dry run (either form)
python -m syncer.app --dry-run
DRY_RUN=true python -m syncer.app

# real run
python -m syncer.app

# check cookie (value print වෙන්නේ නෑ)
awk -F'\t' '$6=="sp_dc"{print "sp_dc found, length", length($7)}' cookies/spotify.txt

# database summary (saved songs per playlist)
python -m syncer.app --db-summary

# playlist name + link (YouTube API එකෙන්, read-only)
python -m syncer.app --playlist-title

# state backup
cp data/sync-state.json ~/sync-state-$(date +%F).json

# skipped/failed ලැයිස්තුව බලන්න
python - <<'EOF'
import json, pathlib
d = json.loads(pathlib.Path('data/sync-state.json').read_text())
for pid, db in d['playlists'].items():
    print(pid, 'saved', len(db.get('videos', {})), 'skipped', len(db.get('skipped', {})), 'failed', db.get('failures', {}))
    for vid, info in db.get('skipped', {}).items(): print('  SKIP', vid, info.get('title'))
EOF

# එක සින්දුවක් ආයේ try කරන්න (skip + failure එක අයින් කරලා)
python - <<'EOF'
import json, pathlib
p = pathlib.Path('data/sync-state.json'); d = json.loads(p.read_text())
for db in d['playlists'].values():
    db.get('skipped', {}).pop('aLZNbOUOyI4', None)
    db.get('failures', {}).pop('aLZNbOUOyI4', None)
p.write_text(json.dumps(d, indent=2, ensure_ascii=False) + '\n')
EOF

# clear pending (playlist එක බැලුවට පස්සේ!)
python - <<'EOF'
import json, pathlib
p = pathlib.Path('data/sync-state.json'); d = json.loads(p.read_text())
for db in d['playlists'].values(): db['pending'] = None
p.write_text(json.dumps(d, indent=2) + '\n')
EOF
```

## Telegram message එකේ statuses

| Status | අර්ථය |
|---|---|
| `ADD` | Spotify එකට add වුණා ✅ |
| `WOULD ADD` | dry run — add වෙන්නේ ඊළඟ ඇත්ත run එකේ |
| `SKIP` | no match / unavailable / same track in run — **මේ පාර විතරයි** ගණනට + Telegram එකට එනවා; ඊට පස්සේ DB එකේ `skipped` නිසා silent |
| `FAIL` | network/HTTP error — **දෙපාරක්** log වෙනවා, ඊට පස්සේ `failures` නිසා silent (retry නෑ) |
| *(silent)* | already recorded / already in Spotify / duplicate video / කලින් log වුණු skip හෝ fail → DB එකේ විතරයි (ගණනටවත් නෑ) |
| `FAIL` | search error / add error / ambiguous write |

## Match methods

| Method | අර්ථය |
|---|---|
| `MANUAL` | `data/track-overrides.json` |
| `STRICT` | artist + exact canonical title + version |
| `LOOSE` | full title similarity ≥ 0.86 |
| `DETAIL` | core title + word order + duration check |

## Dry run

| කොහෙන්ද | කොහොමද |
|---|---|
| Actions | Run workflow → `dry_run` ✅ (default) |
| Schedule | `SYNC_ENABLED` unset = dry run; `true` = live |
| Local | `--dry-run` හෝ `DRY_RUN=true` |

## ඉක්මන් ලින්ක්

Setup → [00](00-QUICKSTART.md) · Secrets → [01](01-repository-secrets.md) · Errors → [07](07-troubleshooting.md) · Security → [08](08-security-and-cookie-hygiene.md)
