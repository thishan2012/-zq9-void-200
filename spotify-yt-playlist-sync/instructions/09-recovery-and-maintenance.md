# 🛠️ 09 — Recovery & Maintenance (pending, expire, re-run, backup)

## 1. `pending` — ඇයි, කවදද, කරන්නේ මොකද

Batch add එකකට කලින් code එක state එකේ මෙහෙම ලියනවා:

```json
"pending": { "items": [ {"video": "FGys9rRBytU", "track": "1R96NBIdXeLeYHvstCJV1J"} ] }
```

- **Definite fail** (HTTP 4xx): `pending = null`, ඒ tracks FAIL වෙලා log වෙනවා → ඊළඟ run එකේ ආයේ උත්සාහ කරනවා
- **Ambiguous** (timeout / HTTP 5xx / GraphQL error / කියවන්න බැරි response): run එක නවතිනවා, `pending` ඉතුරු වෙනවා

ඊළඟ run එකේ ඉස්සෙල්ලාම:

| තත්වය | Code එකේ ක්‍රියාව |
|---|---|
| track එක playlist එකේ **තියෙනවා** | record කරලා ඉදිරියට යනවා ✅ |
| track එක playlist එකේ **නෑ** | run නවතිනවා: `Previous add outcome is uncertain and track was not found…` |

එහෙම නැවතුණොත්:

1. Spotify playlist එක open කරලා ඒ සින්දුව **ඇත්තටම තියෙනවද** බලන්න
2. තියෙනවා නම් → `data/sync-state.json` එකේ `pending` එක `null` කරලා, video ID → track ID `videos` එකට දාන්න (හෝ pending එක තියාගෙන run කරන්න — code එකම record කරයි)
3. නෑ නම් → `pending` එක `null` කරලා ආයේ run කරන්න (එතකොට ආයේ try කරනවා)

## 1b. Database එක බලන විදිය (add වුණු songs save වෙලාද?)

Database එක = **`data/sync-state.json`**.

| කොහෙන්ද | කොහොමද |
|---|---|
| GitHub run page | හැම run එකකම **Job summary** එකේ `🗄️ Database` table එක (playlist / saved songs / **skipped** / **failed** / pending) |
| Actions log | `INFO ADD <video> -> <track>` line එකක් හැම add එකකටම |
| Telegram full log | `#1 ADD: …` + `Spotify: https://open.spotify.com/track/…` |
| Local | `python -m syncer.app --db-summary` |
| Raw file | `data/sync-state.json` → `playlists.<id>.videos` |

⚠️ **Dry run එකේදී add වුණු සින්දු save වෙන්නේ නෑ** — `WOULD ADD` විතරයි. Save වෙන්නේ live run එකේදී විතරයි (bot commit එකෙන්).
ඒත් **skip/fail bookkeeping** (`skipped`, `failures`) dry run එකේදීත් save වෙනවා — එකම සින්දුව හැම run එකකම log නොවෙන්න.

### 1c. එකම සින්දුව ආයේ log වෙනවා නම්

| DB key | තේරුම | නැවත try කරන්න ඕන නම් |
|---|---|---|
| `skipped` | skip වුණා (හේතුවක් එක්ක), ආයේ search නෑ | entry එක delete කරන්න, නැත්නම් `data/track-overrides.json` එකට manual mapping දාන්න |
| `failures` | FAIL වුණු ගණන (`2` = retired) | entry එක delete කරන්න, නැත්නම් override එකක් දාන්න |

```bash
# එක සින්දුවක් ආයේ try කරන්න
python - <<'EOF'
import json, pathlib
p = pathlib.Path('data/sync-state.json'); d = json.loads(p.read_text())
for db in d['playlists'].values():
    db.get('skipped', {}).pop('aLZNbOUOyI4', None)
    db.get('failures', {}).pop('aLZNbOUOyI4', None)
p.write_text(json.dumps(d, indent=2, ensure_ascii=False) + '\n')
EOF

# හැම skip එකක්ම ආයේ try කරන්න (සම්පූර්ණ reset)
python - <<'EOF'
import json, pathlib
p = pathlib.Path('data/sync-state.json'); d = json.loads(p.read_text())
for db in d['playlists'].values():
    db['skipped'] = {}; db['failures'] = {}
p.write_text(json.dumps(d, indent=2, ensure_ascii=False) + '\n')
EOF
```

## 2. එක සින්දුවක් ආයේ sync කරන්න

`data/sync-state.json` එකේ `videos` එකෙන් ඒ video ID entry එක delete කරලා run කරන්න.
(Spotify එකේ තියෙනවා නම් code එක ඒක silent එකේ record කරනවා — duplicate නෑ, log එකටත් එන්නේ නෑ.)

## 3. State file එක backup / restore

```bash
# backup
cp data/sync-state.json ~/sync-state-backup-$(date +%F).json

# restore (හොඳ version එකක්)
git log --oneline -- data/sync-state.json
git show <commit>:data/sync-state.json > data/sync-state.json
```

State file එකේ වැදගත් දේ `videos` map එක විතරයි — ඒක කැඩුණොත් අලුත් `{"version":1,"playlists":{}}` එකකින් පටන් ගන්න පුළුවන්, ඒත් එතකොට duplicate check playlist read එකෙන් විතරයි වෙන්නේ (එහෙමත් duplicate add නොවෙනවා, ඒත් searches ටිකක් වැඩිපුර යනවා).

## 4. Cookie expire වීම (සාමාන්‍ය දේ)

ලක්ෂණ: `Spotify token request failed (HTTP 400/401)` හෝ `Spotify returned an anonymous session`

කරන්න:
1. open.spotify.com → login
2. අලුත් Netscape cookies.txt export
3. Settings → Secrets → `SPOTIFY_COOKIE` → **Update**
4. ඊළඟ run එකේදී වැඩ කරනවා

## 5. Manual override එකක් (වැරදි match එකක් හදන්න)

`data/track-overrides.json`:

```json
{
  "FGys9rRBytU": "1R96NBIdXeLeYHvstCJV1J"
}
```

- key = YouTube **video ID** (11 chars, `watch?v=` එකෙන් පස්සේ එන එක)
- value = Spotify **track ID** (22 chars, `/track/` එකෙන් පස්සේ එන එක)
- Format වැරදි නම් run එක නවතිනවා (`Invalid data/track-overrides.json`)
- Override එකක් දාපු video එකක් දැනටමත් `videos` එකේ තියෙනවා නම් override එක apply වෙන්නේ නෑ — ඒ entry එක අයින් කරන්න

## 6. Playlist එකක් මාරු කරන්න

1. `SPOTIFY_PLAYLIST` secret/variable එක update කරන්න
2. State file එකේ අලුත් playlist ID එකට key එකක් **හදන්න ඕන නෑ** — code එකම හදනවා (`playlists.setdefault`)
3. පළමු run එකේදී playlist එකේ තියෙන tracks ඔක්කොම skip වෙනවා, ඉතුරු ඒවා add වෙනවා

## 7. නඩත්තු checklist (මාසිකව)

- [ ] Actions tab එකේ last runs ✅ ද බලන්න
- [ ] cookie එක වැඩ කරනවද (run එකක් දාලා බලන්න)
- [ ] `data/sync-state.json` commit වෙනවද
- [ ] YouTube playlist එකේ අලුත් සින්දු add වෙලාද
- [ ] Telegram full log එකේ වැරදි matches තියෙනවාද → overrides
- [ ] `pending` null ද
- [ ] Job summary එකේ `Skipped (not retried)` ගණන වැඩි වෙනවාද → ඒ ලිස්ට් එකේ ඉන්නේ ඇත්තටම හම්බුනේ නැති සින්දු (patterns වැඩ කරන්නේ නැති ඒවා)
