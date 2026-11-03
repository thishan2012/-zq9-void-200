# ZIP එක ඇතුළේ මොනවද? — YouTube → Spotify Sync (ඉගෙනීමේ සටහන්)

මේ repo එකේ තියෙන්නේ `spotify-yt-playlist-sync-project.zip` කියන එක විතරයි. ඒක දිග හැරියම එන්නේ **එක ප්‍රොජෙක්ට් එකක්**: public/unlisted YouTube playlist එකක ඉන්න සින්දු, තියෙන Spotify playlist එකකට **එක පැත්තට** (one-way) sync කරන Python ටූල් එකක්. සින්දු මකන්නේ නෑ. GitHub Actions එකෙන් දවසට දෙපාරක් ඔටෝමැටික් රන් වෙනවා, Telegram summary එකකුත් එවනවා.

Extract කරපු අනුපිටපත: `spotify-yt-playlist-sync/`
(මම ඒක repo එකට එකතු කරලා තියෙනවා — `.github/workflows/build-from-zip.yml` එකෙන් push කරද්දීම zip එකෙන් build වෙන්නත් පුළුවන්.)

---

## 1. ෆයිල් ලැයිස්තුව (සම්පූර්ණයි — 20 ෆයිල්)

```
spotify-yt-playlist-sync/
├── .github/workflows/sync.yml      # schedule + manual dry-run + state commit
├── cookies/README.md               # cookie ෆයිල් එක ගැන අවවාදය
├── data/sync-state.json            # "DB" — වීඩියෝ ID → Spotify track ID
├── data/track-overrides.json       # manual match (FGys9rRBytU → 1R96NBIdXeLeYHvstCJV1J)
├── instructions/{youtube,spotify,telegram,actions}.md
├── requirements.txt                # requests>=2.32,<3
├── syncer/app.py                   # මුළු ලොජික් එකම (880 පේළි)
└── tests/ (5 ෆයිල්, 54 test)
```

**අවධානය:** zip එකේ `cookies/spotify.txt` (9 KB, Netscape cookie export) තිබුණා. ඒක **ඇත්තම `sp_dc` session cookie** එකක් — API key එකක් නෙවෙයි, account එකට login වෙන්න පුළුවන් credential එකක්. ඒ නිසා මම ඒක extract කරපු අනුපිටපතට **දාලා නෑ**, ඒ වෙනුවට `.gitignore` එකට add කරලා තියෙනවා. ඒකේ Google/`.google.iq`/`.google.lk` cookies 39කුත් තිබුණා (YTDLnis export එකක් නිසා browser එකේ මුළු cookie jar එකම ඇවිත්). විස්තර පහළ §7 එකේ.

---

## 2. එක රන් එකක් — step by step

`python -m syncer.app [--dry-run]`

| # | තැන | මොකද වෙන්නේ |
|---|------|------------|
| 1 | `main()` 840–860 | `REQUEST_DELAY_SECONDS` (0–60, default 2) කියවනවා; playlist URL/ID දෙක validate කරනවා; state + overrides load කරනවා |
| 2 | `sp_dc_from_file()` 65 | `cookies/spotify.txt` එකේ `sp_dc` එක හොයනවා (`#HttpOnly_` prefix එකත් handle කරනවා) |
| 3 | `Client.youtube()` 163 | YouTube Data API v3: `playlistItems.list` (50/page, pageToken loop) + `videos.list` (50 බැගින්, description + ISO-8601 duration) |
| 4 | `Client.token()` 135 | cookie එකෙන් **access token** එකක් ගන්නවා — unofficial web-player TOTP flow (පහළ §4) |
| 5 | `Client.existing_tracks()` 221 | Spotify playlist එකේ දැනට තියෙන track IDs ටික (duplicate check) — REST හරි web-player GQL හරි |
| 6 | `sync()` 734 | වීඩියෝ එකින් එකට: state check → match → duplicate check → pending write → `add()` → state save |
| 7 | `main()` finally 870 | summary (`SUCCESS` / `PARTIAL FAILURE` / `FAILED`) + Telegram messages |
| 8 | workflow | `data/sync-state.json` වෙනස් වෙලා නම් bot commit + push |

Exit code: සම්පූර්ණ success නම් 0, නැත්නම් 1.

---

## 3. Matching — මේක තමයි ප්‍රොජෙක්ට් එකේ "මොළය"

Spotify එකට search කරලා හරි සින්දුව හොයාගන්න **අදියර 3ක්** තියෙනවා. පළමු එක miss වුණොත් දෙවැන්න, දෙකම miss වුණොත් තුන්වැන්න. තුනම miss → `SKIP` (සින්දුව මකන්නේ නෑ, ඊළඟ run එකේ ආයේ උත්සාහ කරනවා).

1. **STRICT** — `metadata()` (422) එකෙන් `(artist, song)` එලියට ගන්නවා, ඊට පස්සේ `choose_match()` (492):
   - artist credit එක හොයන පිළිවෙළ: description එකේ `Artist: X` / `Song · Artist` / `Name - Song` → `X - Topic` channel එක → `Artist - Song` title pattern.
   - Spotify result එකේ **canonical title සමාන වෙන්න ඕන + version signature සමාන වෙන්න ඕන + primary artist match වෙන්න ඕන**.
   - Results 2ක් හරියටම සමාන නම් (ambiguity) → **අත ඇරලා දානවා**. "අහඹුවට එකක් තෝරන්නේ නෑ" කියන philosophy එක මුළු කෝඩ් එකේම තියෙනවා.
2. **LOOSE** — `choose_title_fallback()` (520): මුළු video title එකෙන් search, `SequenceMatcher` ratio ≥ **0.86**, artist match අවශ්‍ය නෑ, ඒත් version markers සහ remix/edit නම් full title සමාන වෙන්න ඕන. Top 2 අතර වෙනස < 0.05 නම් skip.
3. **DETAIL** — `detail_search()` (641) + `choose_detail_fallback()` (585): `search_core()` එකෙන් `slowed`, `reverb`, `remix` වගේ වචන අයින් කරලා core title එකෙන් ආයේ search; word-order වෙනස් වුණත් ගන්නවා (ordered vs sorted comparison, `max()`); artist match එකක් තියෙනවා නම් 0.86, නැත්නම් 0.93; දෙපැත්තේම duration තියෙනවා නම් `> max(30s, 25%)` වෙනස → reject.

Version එක වෙන් කරන එක වැදගත්: `version_signature()` (457) එකේ `slowed`, `super-slowed`, `ultra-slowed`, `sped-up`, `reverb`, `8d`, `nightcore`, `live`, `cover`, `instrumental`… 28ක් වගේ marker set එකක්. `canonical_track_title()` (383) එකෙන් `(Official Video)`, `(Lyrics)` වගේ presentation-only labels අයින් වෙනවා — **ඒත් `(Official Video - Slowed)` එකේ `Slowed` එක ඉතුරු වෙනවා** (bracket එක මුළුම අයින් කරන්නේ නෑ). මේක මගේ අතින් ටෙස්ට් කළා:

```
'Song (Official Video - Slowed)'  -> canonical: 'song slowed'
'On My Way (Ultra Slowed + Reverb)' -> version: {'ultra-slowed','reverb','slowed'} / core: 'on my way'
```

**Manual override** — `data/track-overrides.json`: YouTube video ID → Spotify track ID. මේක automatic matching එක **සම්පූර්ණයෙන් bypass** කරනවා (duration/version check නෑ), ඒත් duplicate + pending logic තියෙනවා. Format එක වැරදි නම් run එක නවතිනවා.

---

## 4. Spotify පැත්ත — මේක තමයි "experimental" කොටස

Spotify Web API app credentials පාවිච්චි කරන්නේ නෑ. ඒ වෙනුවට browser session එකේ cookie එකෙන් token එකක් ගන්නවා:

```
sp_dc cookie → TOTP code (xyloflake/spot-secrets-go secretDict.json එකෙන් cipher list)
            → GET open.spotify.com/api/token?reason=transport&productType=web-player&totp=…
            → accessToken
```

`totp()` (79) එකේ තියෙන ට්‍රික් එක: `key = ''.join(str(x ^ ((i % 33) + 9)))` — cipher එකෙන් HMAC-SHA1 secret එක හදලා, 30s time step එකෙන් 6-digit code එකක්. වැඩ කරන version එකක් හම්බ වෙනකම් අලුත්ම 3 versions උත්සාහ කරනවා (400 = පරණ version, ඊළඟ එකට යනවා).

ඊට පස්සේ **backend දෙකක්**:

- **REST** (`api.spotify.com/v1/...`) — ඒත් `https://corsly-proxy2.camdvr.org/?url=<target>` කියන third-party proxy එක හරහා. මොකද Bearer token එක proxy එකට යනවා ⇒ `instructions/spotify.md` එකේ ලොකු අවවාදයක් තියෙනවා proxy operator එකට විශ්වාස කරන්න ඕන කියලා.
- **Web-player GraphQL** (`api-partner.spotify.com/pathfinder/v2/query`) — persisted query hashes 3ක් (`fetchPlaylist`, `searchTracks`, `addToPlaylist`) hardcode කරලා. මේවා Spotify කවදා හරි rotate කරනවා ⇒ කැඩෙනවා.

Backend තේරීමේ රීතිය (221–247): **read එකේදී** විතරයි fallback. REST read 401/403/404/405/429/501 → web-player; proxy web-player fail → direct web-player. සාර්ථක වුණු backend එකෙන් **writes** කරනවා. **Write එකක් fail වුණොත් කවදාවත් retry කරන්නේ නෑ** — මොකද add එක ඇත්තටම වෙලා තියෙන්න පුළුවන්.

---

## 5. වඩාත්ම ලස්සන කොටස: uncertainty handling

මේක තමයි මේ කෝඩ් එකෙන් ඉගෙන ගන්න ඕන pattern එක. "sidhu දෙපාරක් add වුණොත් මොකද" කියන ප්‍රශ්නයට උත්තරය:

1. `add()` එකට කලින් state එකේ `db['pending'] = {video, track}` save කරනවා (806).
2. Network timeout / HTTP 5xx / HTTP 200 + GraphQL error / invalid JSON → `UncertainWrite` exception (FatalError subclass) → **run එක නවතිනවා**, pending එක state එකේ ඉතුරු වෙනවා.
3. ඊළඟ run එකේ මුලින්ම pending එක reconcile කරනවා (739): track එක playlist එකේ තියෙනවා නම් → record කරලා ඉවර; නැත්නම් → "check manually, then clear pending" කියලා නවතිනවා. Auto-retry නෑ (duplicate risk).
4. `SyncError` (definite failure) එකේදී විතරයි pending එක clear කරලා ඊළඟ සින්දුවට යන්නේ.

තවත් safety touches:
- `existing_tracks()` fail වුණොත් (playlist එක කියවන්න බැරි නම්) → **fail closed** — duplicates වෙන්න දෙනවට වඩා run එක නවතින එක හොඳයි කියන තීරණය.
- Invalid/පොඩි response එකක් ආවොත් page එකක් "අඩුවෙන්" කියවලා duplicate add වෙන්න පුළුවන් නිසා `FatalError`.
- Proxy URL එකට `api.spotify.com` / `api-partner.spotify.com` විතරයි යවන්නේ (98) — bearer token වෙන host එකකට යන්නෙ නෑ. Proxy request එකේ redirects follow කරන්නේ නෑ (token leak එකක් වෙන්න පුළුවන් නිසා).
- Telegram 4096 UTF-16 limit එකට messages split කරනවා (709) — ඒත් **issue boundary** එකකින් split කරනවා, මැදින් කපන්නේ නෑ.
- Logs වලට secrets, URLs, responses **print කරන්නේ නෑ** — `log_text()` / `issue_text()` (693–700) වලින් user metadata එකත් control chars අයින් කරලා short කරනවා (prompt-injection-ish / log-forging නවත්තන්න).

**එකම නොකැඩෙන අඩුපාඩුව:** state commit එක Spotify write එකට පස්සේ, separate step එකක්. Action එකේ push fail වුණොත් playlist එකේ add වෙලා, state එකේ record නෑ. ඒත් duplicate check එක playlist එකේ ඇත්ත track එක බලන නිසා දෙවෙනි පාර add වෙන්නේ නෑ — skip වෙනවා විතරයි.

---

## 6. සීමා (මේක "toy" එකක් නෙවෙයි, ඒත් guarantee නෑ)

- Audio fingerprinting නෑ — metadata heuristics විතරයි. LOOSE/DETAIL matches වැරදි සින්දුවකට යන්න පුළුවන්. ඒ නිසා `--dry-run` + log එකේ `MANUAL/STRICT/LOOSE/DETAIL MATCH` / `SKIP` lines බලන්න.
- Spotify Free account එකකට playlist edit අවසර නොලැබෙන්න පුළුවන්; 401/403 ආවොත් run එක නවතිනවා (බොරු "success" කියන්නේ නෑ).
- GraphQL hashes + TOTP secret list + proxy = තුනම third-party/unofficial ⇒ කවදා හරි නවතිනවා.
- state එකේ ඉන්න වීඩියෝ ආයේ evaluate කරන්නේ නෑ — Spotify එකෙන් අතින් මකලා තිබ්බත් skip වෙනවා (entry එක අතින් අයින් කරන්න ඕන).
- Schedule දුවන්නේ default branch එකෙන් විතරයි; GitHub පැය ගාණක් delay කරන්න පුළුවන්.

---

## 7. ⚠️ ආරක්ෂාව — මේක අනිවාර්යයෙන් කියවන්න

1. **මේ repo එක public** (`thishan2012/-zq9-void-200`, `isPrivate: false`). ඒ නිසා zip එක ඇතුළේ තිබුණු `cookies/spotify.txt` එක මෙතන commit කළේ නෑ. ඒක commit කරනවා නම් ඕනෑම කෙනෙකුට ඒ Spotify account එකට login වෙන්න පුළුවන්. ⇒ ඒ cookie එක **ක්ෂණිකව revoke** කරන්න: Spotify → Account → "Sign out everywhere", password change; `.google.*` cookies තිබුණු නිසා ඒ Google account එකේ sessions ටිකත් sign out කරන්න.
2. Zip එකේ **Git history නෑ** — ඒ නිසා `git log` එකෙන් "මොනවා හරි වෙනස් වුණාද" කියලා බලන්න බෑ. Commit එකක් තියෙන්නේ: `Add files via upload` විතරයි. ඒ නිසා "හදලා තියෙන විදිය" කියලා බලාගන්න පුළුවන් එකම දේ = දැනට තියෙන state එක. (STATE එකේ `playlists: {}` — ඒ කියන්නේ sync එකක් තවම සාර්ථකව record වෙලා නෑ. Overrides එකේ PARAISO mapping එක විතරයි.)
3. `cookies/spotify.txt` `.gitignore` එකට add කළා — ඒ නිසා cookie එකක් තිබ්බත් `git add .` එකෙන් public වෙන්නේ නෑ.
4. හොඳ deployment එකක් ඕන නම්: repo එක private කරන්න, cookie එක **GitHub Secrets** එකකට දාන්න (file එකට වඩා), disposable account එකක් පාවිච්චි කරන්න, `REQUEST_DELAY_SECONDS` වැඩි කරන්න.
5. Proxy එකට Bearer token එක යන නිසා proxy operator එකට විශ්වාස කරන්න ඕන. Token එක expire වෙනවා (1h වගේ), cookie එක නෙවෙයි — ඒත් token එකෙන් playlist edit කරන්න පුළුවන්.

---

## 8. අතින් ට්‍රයි කරන්න (local, මගේ sandbox එකේ)

```bash
cd spotify-yt-playlist-sync
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
.venv/bin/python -m unittest discover -s tests -v     # ✅ 54 tests OK (මම run කළා)
```

Live run එකකට ඕන දේවල්: `YOUTUBE_API_KEY`, cookie ෆයිල් එක, `YOUTUBE_PLAYLIST`, `SPOTIFY_PLAYLIST`.

```bash
YOUTUBE_PLAYLIST='…' SPOTIFY_PLAYLIST='…' YOUTUBE_API_KEY='…' \
SPOTIFY_COOKIE_FILE=cookies/spotify.txt \
.venv/bin/python -m syncer.app --dry-run
```

`--dry-run` කියන්නේ: Spotify වලට මොනවත් write නෑ, state file එකත් වෙනස් වෙන්නේ නෑ ⇒ network/API keys නැතුවත් `python -m syncer.app --dry-run` එක fail වෙන්නේ config check එකේදී විතරයි.

---

## 9. ඉගෙන ගන්න පුළුවන් design patterns (මේ repo එකෙන්)

| Pattern | කොහෙද | ඇයි වැදගත් |
|---|---|---|
| Fail closed | `existing_tracks()`, `gql_existing_tracks()` | duplicate > no-op වලට වඩා නරක |
| Pending record + no auto-retry | `sync()` 806–819 | ambiguous write එකක් දෙපාරක් නොවෙන්න |
| Backend දෙකක්, read-only fallback | 221–247, `spotify_backend` | write එකක් වුණාට පස්සේ route මාරු කරන්න බෑ |
| Uncertain vs. definite errors | `UncertainWrite` vs `SyncError` | retry කරන්න පුළුවන් දේ වෙන් කරලා හඳුනාගන්න |
| Heuristic scoring + tie rejection | `choose_*_fallback()` | confidence gate එකේ අගය තමයි නිවැරදිකම |
| Per-item failure ≠ run failure | `sync()` except blocks | එක සින්දුවක් fail වුණාට ඉතුරු ඒවා process වෙනවා |
| Sanitized logging | `log_text`, `issue_text`, 121 comment | secrets + log forging |
| Atomic state write | `save_state()` (`tmp` + replace) | කැඩුණු JSON එකකින් DB එක විනාශ නොවෙන්න |

---

## 10. ඊළඟට කරන්න පුළුවන් දේවල් (මම කැමති නම්)

- `python -m syncer.app --dry-run` එකට **fixture mode** එකක් (mock YouTube/Spotify JSON) — network නැතුව මුළු flow එකම ටෙස්ට් කරන්න.
- State schema එකට `schema_version` migration helper එකක් (`version: 1` hardcode වෙලා තියෙනවා).
- GraphQL hashes ෆයිල් එකකට ගෙනියන්න — rotate වුණාම code edit නැතුව update කරන්න.
- `add()` එකට කලින් playlist track count එකක් ගන්නවා නම්, uncertain add එක reconcile කරන්න තව විදිහක් තියෙනවා (track ID එකෙන් නොවේ, position එකෙන්).

මොකක් හරි එකක් කරන්න ඕන නම් කියන්න — මම ඒක branch එකේම හදලා දෙන්නම්. 🙂
