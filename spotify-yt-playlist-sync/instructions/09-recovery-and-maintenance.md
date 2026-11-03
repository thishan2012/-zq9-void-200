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

## 2. එක සින්දුවක් ආයේ sync කරන්න

`data/sync-state.json` එකේ `videos` එකෙන් ඒ video ID entry එක delete කරලා run කරන්න.
(Spotify එකේ තියෙනවා නම් code එක `Track already in Spotify playlist` කියලා skip කරයි — duplicate නෑ.)

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
- [ ] Telegram full log එකේ වැරදි matches තියෙනවද → overrides
- [ ] `pending` null ද
