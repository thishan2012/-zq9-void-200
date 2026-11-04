# 🔎 13 — Extra search steps (29 වෙන වෙනම ක්‍රම)

මේ ගොනුව කියවන්නේ **"ඇයි මේ සින්දුව add වුණේ නැත්තේ?"** කියන ප්‍රශ්නයට උත්තර දෙන්න.
පළමු ක්‍රම 3 (`STRICT` → `LOOSE` → `DETAIL`) miss වුණාම, ඊට පස්සේ **මේ 29 ක්‍රම පිළිවෙලට** ට්‍රයි වෙනවා.
හැම එකක්ම වෙන වෙනම කුඩා experiment එකක් — කැඩුණොත් අනිත් ඒවාට බලපෑමක් නෑ, අයින් කරන්නත් පුළුවන්.

> 👉 ලොජික් එක තියෙන්නේ `syncer/search_steps.py` එකේ. ලැයිස්තුව බලන්න: `python -m syncer.app --steps`

---

## 1. මූලික රීතිය — **version එක වෙනස් වෙන්න බෑ**

> **Slowed නම් slowed එකම add වෙන්න ඕන.** Original එක, sped up එක, remix එක, nightcore එක, නැත්නම් වෙන slowed පඩියක් (Slowed ↔ Ultra Slowed) add වෙන්නේ නෑ.

හැම step එකකුත් `version_ok()` පාස් වෙන්න ඕන:

| Video title | Spotify track | ප්‍රතිඵලය |
|---|---|---|
| `FUNK ABNORMAL (SLOWED)` | `FUNK ABNORMAL - Slowed` | ✅ |
| `FUNK ABNORMAL (SLOWED)` | `FUNK ABNORMAL` (original) | ❌ |
| `FUNK ABNORMAL (SLOWED)` | `FUNK ABNORMAL - Sped Up` | ❌ |
| `VOCE NA MIRA (Super Slowed)` | `Voce Na Mira - Ultra Slowed` | ✅ (Super↔Ultra එකම පඩිය) |
| `VOICE (Slowed)` | `VOICE - Ultra Slowed` | ❌ වෙනස් slowed පඩියක් |

`version_signature()` / `version_tokens()` / `versions_agree()` / `upgraded_edit()` — මේවා `syncer/app.py` එකේ.

---

## 2. Steps 29

| # | Code | මොකද කරන්නේ | උදාහරණය |
|---|---|---|---|
| 1 | `REVERSED` | `Song - Artists` පෙරළිලා තියෙන ඒවා (artist credit දකුණේ) | `QUERO AMOR - SXYGX x FYU` |
| 2 | `SINGLE` | collab එකේ එක අයෙක්ගේ නමින් විතරක් search | `MONTAGEM RUNE - WUYS x KIT` |
| 3 | `CHANNEL` | YouTube channel නම artist විදිහට | uploader ගේ නම = artist |
| 4 | `TOPIC` | `Artist - Topic` channel එකේ ඇත්ත නම | `SHAKA - Topic` → SHAKA |
| 5 | `SUFFIX` | **4**  |  4% | extra step |
| 6 | `COUNTRY` | accent/භාෂා වෙනස්කම් fold (`ã`, `ł`, Chinese) | `CORTA NO SALÃO` ↔ `CORTA NO SALAO` |
| 7 | `FEAT` | `(feat. X)` එකේ X ව main artist විදිහට | `FUNK TONTO (feat. Mc Ombrinho)` |
| 8 | `DURATION` | එකම නමට versions කීපයක් → video duration එකෙන් තෝරනවා | Slowed vs Original |
| 9 | `ARTISTS` | හැම credited artist එකක්ම වෙන වෙනම try | collab lists |
| 10 | `SHORT` | `LUZ`, `AWE` වගේ කෙටි නම් (artist එක ගැලපෙන්න ඕන) | `LUZ` |
| 11 | `ARTISTLESS` | title එක විතරක් search (artist දෙපැත්තෙම වැරදි) | phonk uploads |
| 12 | `EXACT` | version වචන අයින් කරලා වචන සමානද බලනවා | `MONTAGEM ENDLESS` |
| 13 | `WORDSET` | වචන එකම, පිළිවෙල වෙනස් | `Funk Midu Shange` ↔ `Midu Shange Funk` |
| 14 | `SLOWED` | `"<song> slowed"` කියලා search — **slowed එකක් විතරයි** ගන්නේ | `FUNK ABNORMAL (SLOWED)` |
| 15 | `UPLOADER` | uploader නම + title එක එකට search | `Slowed by X` channels |
| 16 | `LINKED` | description එකේ `open.spotify.com/track/…` link එක තිබුණොත් — search නෑ, කෙලින්ම ඒ track එක (version check විතරයි) | `Stream: open.spotify.com/track/…` |
| 17 | `FIELD` | Spotify field search: `track:"SHAKA" artist:"Nulteex"` — නමයි artist එකයි මික් වෙන්නේ නෑ | collab uploads |
| 18 | `VARIANTS` | query shapes 3ක් එකට: artist+title+version, artist+title, title+version | `SHAKA (SLOWED)` |
| 19 | `DURVER` | title එක ටිකක් වෙනස් වුණත් duration ±3s + version ගැලපුණොත් ගන්නවා | `LOUCARA FUNK!` |
| 20 | `CLEANARTIST` | title clean කරලා ඉතුරු වෙන artist එකෙන් search | `DESTELLO - HDN \| VIRAL PHONK` |
| 21 | `TITLEONLY` | title විතරක් — duration එකයි "track නම title එකේ තියෙනවද" කියලා දෙකෙන්ම ඔප්පු වුණොත් විතරයි | `MONTAGEM RUNE - WUYS x KIT` |
| 22 | `SONGTAG` | title එකේ ඇත්ත song නම නැති uploads: description/hashtags වල `Song: …`, `Artist: …`, ♪ line, `#MontagemMiau` වලින් නම ගන්නවා | `MONTAGEM MIAU 🔥` |
| 23 | `ISRC` | description එකේ `ISRC:` එකක් තිබ්බොත්, ඒ **exact ISRC** එක තියෙන Spotify candidate එක — නම/artist check නෑ | `ISRC: BRABC2401234` |
| 24 | `DESCTEXT` | description එකේ label නැති line එකක් (නම විතරක්) song නම විදිහට — 0.92 floor | `MONTAGEM MIAU` + `Prod. by DJ NEO` |
| 25 | `BROKEN` | dash එකේ දෙපැත්ත **අනිත් පැත්තට** ලියලා තියෙනවා (`DESTELLO - HDN` = artist `HDN`, song `DESTELLO`) | `DESTELLO - HDN` + channel `HDN🎹` |
| 26 | `ALBUM` | version/naming එක **album එකේ** තියෙනවා (`X - Single`, `X (Slowed)`) | `FUNK TONTO (Slowed)` album එකේ | 
| 27 | `PART` | Spotify එකේ `Pt. 1` / `Pt. 2` විදිහට කැඩිච්ච titles එකම සින්දුව විදිහට | `FUNK TONTO, Pt. 2 (feat. Mc Ombrinho)` |
| 28 | `POPULAR` | එකම title එකේ matches කීපයක් → **වැඩිම play ගණන** ඇති එක (play ගණනක් නැත්නම්/සමාන නම් → තෝරන්නේ නෑ) | duplicate uploads |
| 29 | `TOPRESULT` | **අන්තිම උත්සාහය:** search එකේ **මුලින්ම එන result එක** ගන්නවා — ඒත් ඒක ඇත්තටම ඒ සින්දුවද කියලා 3කින් බලලා | පහළ `TOPRESULT` කොටස බලන්න |

**හැම step එකකුත් අන්තිමට artist conflict එක බලනවා** (`artist_ok()`): video එකේ title එකේ artist කෙනෙක් තියෙනවා නම්, Spotify track එකේ ඒ නම නැත්නම් → match එක අවිශ්වාසී, ඒ නිසා ගන්නේ නෑ.
ඒකයි `DESTELLO - HDN` වගේ එකක් වෙන artist කෙනෙක්ගේ `HDN` එකට match වෙන්නේ නැත්තේ (Spotify එකේ DESTELLO නෑ නම් → skip).

---

## 2b. `TOPRESULT` — අන්තිම උත්සාහය (අනිත් හැම එකක්ම miss වුණාම)

Search query එකේ **මුලින්ම එන track එක** ගන්නවා — ඒත් **පහත 3ම** සත්‍ය නම් විතරයි:

| # | චෙක් එක | ඇයි |
|---|---|---|
| 1 | **`same_song_title()`** — video title එකේ තේරුම් තියෙන හැම වචනයක්ම Spotify track එකේ තියෙන්න ඕන (+ overall 80% සමාන) | වචනයක් විතරක් ගැලපුණු වෙන සින්දුවක් එන එක නවත්තන්න |
| 2 | **`version_ok()`** — same recording (slowed = slowed, original/sped up/remix ❌) | වෙනස් version එකක් add වෙන එක නවත්තන්න |
| 3 | **`artist_ok()`** — video එකේ credit කරන artist ට Spotify එකේ conflict එකක් නැත්නම් | වෙන artist කෙනෙක්ගේ එකම නම ඇති සින්දුවක් නවත්තන්න |

උදාහරණ:

| Video | Spotify 1st result | ප්‍රතිඵලය |
|---|---|---|
| `Zephyr Nights (Slowed)` | `Zephyr Nights - Slowed` | ✅ ගන්නවා |
| `MONTAGEM ZEPHYR (Slowed)` | `Montagem Nebula - Slowed` | ❌ වචන ගැලපෙන්නේ නෑ |
| `MONTAGEM ZEPHYR (Slowed)` | `MONTAGEM ZEPHYR` (original) | ❌ version වෙනස් |
| `DESTELLO - HDN` | `HDN` (වෙන artist) | ❌ artist conflict |

⚠️ මේක **අන්තිම step එක** — අනිත් 24ම fail වුණාට පස්සේ විතරයි දුවන්නේ. `TOPRESULT` කියලා report එකේ පේනවා නම්, ඒ line එක දෙපාරක් බලන්න (Spotify link එක open කරලා) — වැරදි නම් `data/track-overrides.json` එකෙන් හදන්න.

---

## 2b2. `BROKEN` — dash එකේ දෙපැත්ත අනිත් පැත්තට

Uploader `Artist - Song` කියලා ලියනවා, ඒත් parser එක ඒක `(artist, song)` විදිහට ගන්නවා —
`DESTELLO - HDN` කියන්නේ `DESTELLO` artist, `HDN` song කියලා. ඇත්තටම ඒක අනිත් පැත්ත: `HDN` artist, `DESTELLO` song.

`BROKEN` එකේදී `HDN DESTELLO` කියලා search කරනවා, ඒත් **පහත දෙකම** සත්‍ය නම් විතරයි:

1. `HDN` Spotify track එකේ artist විදිහට තියෙන්න ඕන
2. `HDN` **uploader ගේම නම** වෙන්න ඕන (`HDN🎹` / `HDN - Topic` → `HDN`)

ඒ නිසා uploader වෙන කෙනෙක් නම්, හෝ Spotify එකේ ඒ නම නැත්නම් → skip එකමයි.

## 2b1. අලුත් ක්‍රම 5 (skip වෙන සින්දු හොයන්න)

මේවා දාන කොට පරණ ක්‍රම එකක්වත් අයින් කළේ නෑ — ඒවා හැම එකක්ම තියෙනවා, මේ 5 ඒවාට **එකතු** වුණා.

* **`FIELD`** — `track:"SHAKA" artist:"Nulteex"` වගේ field search. Title එකේ වචන artist field එකට මික් වෙන්නේ නෑ.
  (එක query එකෙන් හම්බ නොවුණොත් `track:"…"` විතරක් ආයේ try කරනවා — ඒත් artist check එක එහෙමමයි.)
* **`VARIANTS`** — එකම query එකක් නෙවෙයි, shapes 3ක්: `artist + title + version`, `artist + title`,
  `title + version`. ඒවායින් එකක් හරි ගැලපුණොත් add; ඔක්කොම fail නම් විතරයි ඊළඟ step එකට යන්නේ.
* **`DURVER`** — title similarity 0.70 වගේ අඩු වුණත්, **duration ±3 seconds** ඇතුළේ + version එකම නම් ගන්නවා.
* **`CLEANARTIST`** — `| VIRAL PHONK` වගේ tags අයින් කරලා ඉතුරු වෙන artist එකෙන් search.
* **`TITLEONLY`** — artist කෙනෙක්වත් නැති වුණත්, duration ගැලපෙනවා + Spotify track එකේ නම **video title එක ඇතුළේ**
  තියෙනවා නම් ගන්නවා. වෙන සින්දුවක් එක වචනයක් බෙදාගෙන ආවොත් ඒක refuse (duration ගැලපුණත්).

## 2b0. අලුත් ක්‍රම 2: `LINKED` සහ `SONGTAG` (title එකේ song නම නැති වීඩියෝ)

### `LINKED` (16)
Uploader කෙනෙක් description එකේ Spotify link එකම දාලා තිබුණොත් අපිට search කරන්න දෙයක් නෑ:
`open.spotify.com/track/<id>` එකෙන් track එක කෙලින්ම ගන්නවා (එක API call — search එකකට වඩා ලාභයි).
බලන්නේ එකම දේ: **version එක.** වීඩියෝ එක `(Slowed)` නම් link එකේ තියෙන්නෙත් slowed edit එකම වෙන්න ඕන.
(Web API backend එක නැති වුණොත් step එක නිශ්ශබ්දව මග හරිනවා — run එක නවත්තන්නේ නෑ.)

### `SONGTAG` (22)
`MONTAGEM MIAU 🔥` වගේ title එකක ඇත්ත song නම නැති වෙන්න පුළුවන් — නම description එකේ තියෙනවා. ඒ නිසා:

1. **`Song: …` / `Track: …`** හෝ **`Artist: …`** line එක
2. YouTube music note: **`♪ MONTAGEM MIAU`**
3. Quoted නම: `the track "MONTAGEM MIAU"`
4. **Hashtags + uploader tags** (`#MontagemMiau` → `Montagem Miau`) — genre වචන (`#phonk`, `#slowed`) මග හරිනවා

ඊට පස්සේ `song + artist` search කරලා, නම **0.90** ට වඩා ගැලපුණොත් + version + artist check ගැලපුණොත් විතරයි add වෙන්නේ.
ඒ නිසා වෙන සින්දුවක් (එක වචනයක් බෙදාගෙන ආවත්) add වෙන්නේ නෑ.

## 2b1c. Skip වුණ සින්දුවක් ආයේ try කරන්න (`--forget-video`)

Skip එකක් `data/sync-state.json` එකේ **සදහටම** මතක තියෙනවා (ඒකයි 200 songs run එකක් හැම පාරම එකම දේ
report නොකරන්නේ). ඒත් මේ අවස්ථා 3කදී ආයේ බලන්න ඕන:

| අවස්ථාව | කරන්නේ |
|---|---|
| Track එක Spotify එකට **ආයේ ආවා** (copyright අයින් වුණා) | `--forget-skipped` (හෝ `--forget-video <id>`) |
| වීඩියෝ එක **private → public** වුණා | කරන්න දෙයක් නෑ — title එක වෙනස් වුණාම තනියෙන්ම ආයේ search වෙනවා |
| Matching rule එකක් හදලා `MATCHER_VERSION` bump කළා | තනියෙන්ම එක පාරක් try වෙනවා, ඒත් **report වෙන්නේ නෑ** (count විතරයි) |

```bash
.venv/bin/python -m syncer.app --forget-video aLZNbOUOyI4   # එක සින්දුවක්
.venv/bin/python -m syncer.app --forget-skipped             # okkoma
.venv/bin/python -m syncer.app --retry-expired              # weekly එකේදී retry වෙන ඒවා බලන්න (වෙනසක් නෑ)
```

### 🔁 Weekly auto-retry (schedule එකේ තියෙනවා — setting එකක් ඕන නෑ)

Workflow එකේ cron දෙකක් තියෙනවා:

| Cron | වේලාව | කරන්නේ |
|---|---|---|
| `0 */4 * * *` | දිනපතා 6 පාරක් | සාමාන්‍ය sync (skip එකක් ආයේ search කරන්නේ නෑ) |
| `0 3 * * 0` | **ඉරිදා 03:00 UTC** (08:30 SL) | ඒ වගේම, **දවස් 7කට වඩා පරණ skip** ටික ආයේ එක පාරක් search කරනවා |

ඒ නිසා:

* copyright නිසා Spotify එකෙන් අයින් වුණ track එකක් **ආයේ ආවොත්** → ඉරිදා run එකේදී තනියෙන්ම add වෙනවා (`--forget-video` කරන්න ඕන නෑ)
* private වුණ වීඩියෝ එකක් public වුණොත් → ඒකට අමතරව `changed_video()` එකෙන් ඊළඟ run එකේම හම්බ වෙනවා
* ආයේ skip වුණොත් → **report වෙන්නේ නෑ** (count විතරයි), ඒ නිසා skip එකක් හැම සතියකම ඔබට කරදර කරන්නේ නෑ
* ඉරිදා run එකේදී හම්බ වුණොත් → **ADD** (dry run එකේ නම් WOULD ADD) විදිහට report වෙනවා

නැවතිලා තියෙන ටික බලන්න: `python -m syncer.app --retry-expired` (මොනවද ඊළඟ weekly එකේදී try වෙන්නේ කියලා පෙන්නනවා, වෙනසක් කරන්නේ නෑ).

ඊළඟ run එකේදී ඒ සින්දුව ආයේ search වෙනවා; හම්බුණොත් add වෙනවා, නැත්තං ආයේ එක පාරක් report වෙනවා.

**DESTELLO / LOUCARA වගේ ඒවා:** Spotify එකේ track එක **නැති** නම් (remove වුණා) හෝ වීඩියෝ එක
**private** නම්, `--forget-skipped` කරත් හැම run එකකම "Not found" එක එන්න පුළුවන්. ඒ නිසා:
track එක Spotify එකට ආයේ ආව දාට විතරක් `--forget-video` කරන්න.

## 2b3. Description parser — තව labels (`Track:`, `Prod. by`, `ISRC:`)

`SONGTAG` (22) දැන් මේ ලේබල්ස් ඔක්කොම කියවනවා:

| Line | ගන්නේ |
|---|---|
| `Song: …` / `Song name: …` / `Track: …` / `Title: …` | song නම |
| `Artist: …` / `Performed by …` | artist |
| **`Prod. by DJ NEO` / `Prod: …` / `Produced by …` / `Producer: …` / `Music by …`** | artist (producer) — **අලුත්** |
| `♪ MONTAGEM MIAU` | song නම |
| `"MONTAGEM MIAU"` (quoted) | song නම |
| `#MontagemMiau` / uploader tags | song නම |

**`ISRC: …`** කියවනවා, ඒත් **evidence විදිහට විතරයි** — track එකක් ඒකෙන් තනියෙම තෝරන්නේ නෑ.

**Producer credit එකේ රීතිය:** Spotify එකේ track එක producer ට credit වෙලා තිබ්බොත් ඒක **conflict එකක් නෙවෙයි** — ඒත් producer නම විතරක් තියෙන නිසා වෙන artist කෙනෙක්ට ඒක pass කරන්නේ නෑ.

### `DESCTEXT` (23) — label නැති line එක

`MONTAGEM MIAU` වගේ line එකක් description එකේ තනියෙම තිබ්බොත් (label එකක් නැතුව), ඒක song නම විදිහට try කරනවා.
ඒත් `Subscribe …`, `Listen …`, links, hashtags, genre වචන විතරක් තියෙන lines **මග හරිනවා**; floor එක **0.92** (SONGTAG එකේ 0.90 ට වඩා දැඩි).

## 2b4. `--stats` — step එකකට කීයක් හම්බ වුණාද (history)

හැම run එකක්ම හම්බ වුණ සින්දුවක් **method එකත් එක්ක** `data/sync-state.json` එකේ `matched` එකට එකතු කරනවා:

```json
"matched": { "STRICT": 70, "LOOSE": 9, "SUFFIX": 4, "DURATION": 3, "TOPIC": 1 }
```

```bash
python -m syncer.app --stats
```

ප්‍රතිදානය:

```
### 📊 Match statistics

**`PLUZA…`** — saved 41, skipped 3, matched 89

| # | Method | Songs | Share | Queries sent | Kind |
|---|---|---|---|---|---|
| 1 | `STRICT` | **70** | 79% | 157 | classic |
| 2 | `LOOSE`  | **9**  | 10% | 10 | classic |
| 3 | `SUFFIX` | **4**  |  4% | cached | extra step |
…
Tried but never won: `REVERSED`, `SINGLE`, `SHORT`, …
Never tried (its condition never applied to these videos): `ISRC`, `LINKED`, …
```

* මේකෙන් පේනවා **කුමන steps වැඩ කරනවද** කියලා → පස්සේ step කපනවද නැද්ද කියලා data එකෙන් තීරණය කරන්න.
* **`Queries sent`**: `cached` කියන්නේ step එක වැඩ කළා, ඒත් ඒ queries run cache එකේ තිබ්බා (අලුත් request එකක් ගියේ නෑ) කියලා. `—` කියන්නේ ඇත්තටම දුවලා නෑ.
* **`matched … (all runs so far, dry runs included)`** — මේක **history** එකක්, මේ run එකේ ගණන නෙවෙයි. ඒ නිසා `matched` > `saved` වෙන්න පුළුවන් (dry run + live run දෙකම එකතු වෙනවා).
* **`Queries sent`** (හා `ran` tally) — step එක **කීප වතාවක් search කළාද** කියන එක. ඒක නැතුව "Songs found = 0" කියන්නේ "මේක මළ step එකක්" කියලා **වැරදියට** තේරෙනවා; ඇත්තටම `SONGTAG` වගේ steps හැම run එකකම search කරනවා, ඒත් ඉන්න කලින් step එකක් ජය ගන්නවා.
  - **Tried but never won** → කපන්න සුදුසුකම් ලබන steps
  - **Never tried (its condition never applied)** → මේ videos වලට අදාළම නැති steps (කපන්න එපා)
* Dry run එකකින් count වෙන්නේ නෑ (dry run එකේ bookkeeping විතරයි) — live run එකකින් + dry run එකේ skip වුණ ඒවා වෙනස්.
* ඒකම table එක Actions **job summary** එකටත් append වෙනවා.

## 2b5. `ISRC` (23) — recording එකේ අංකය

Description එකේ **`ISRC: BRABC2401234`** වගේ එකක් තිබ්බොත්, ඒක **recording එකේම අංකය**:

1. description එකේ නම / artist / producer / channel වලින් candidate queries හදනවා
2. ඒ results වල **track IDs** ගන්නවා (metadata ඕන නෑ — ලාභයි)
3. හැම ID එකක්ම එක පාරක් කියවලා **`external_ids.isrc`** description ISRC එකට සමානද බලනවා
4. සමාන නම් → ඒ track එක. නම / version / artist check **ඕන නෑ** (ISRC එකම ඔප්පුව)

* Spotify search API එකේ ISRC field එකක් නෑ → ID-by-ID බැලීම අවශ්‍ය. ඒ නිසා එක query එකකට **උපරිම candidates 8**, හා query එකකින් හම්බුණොත් එතනින් නවත්තනවා (burst නෑ).
* Candidates වල ISRC **හිස්** නම් ඊළඟ query එකට යනවා — එකම query එකේ request වියදම් නොකර.
* `ISRC:` **නැති** descriptions වලට මේක දුවන්නේ නෑ; අනිත් steps එහෙමම.

## 2b6. 🚨 `--reset-db` — හදිසි අවස්ථාවේ database එක

Database එකේ bookkeeping එකේම ප්‍රශ්නයක් තිබ්බොත් (run එකක් අතරමගදී නැවතුණා, playlist එක මුල ඉඳන් rebuild කරන්න ඕන, numbers වැරදි) — මේක තමයි switch එක:

```bash
python -m syncer.app --reset-db all                          # මොනවද යන්නේ කියලා පෙන්නනවා (වෙනසක් නෑ)
python -m syncer.app --reset-db all --yes                    # ඇත්තටම කරනවා
python -m syncer.app --reset-db playlist --playlist <ID> --yes
python -m syncer.app --reset-db history --yes                # statistics විතරයි, duplicate guard එක තියෙනවා
```

| Scope | යන දේ | ඉතුරු වෙන දේ |
|---|---|---|
| `history` | `matched` / `worked` / `ran` / `runs` + matcher stamp | මතක තියෙන videos / skips — කිසිවක් ආයේ search වෙන්නේ නෑ |
| `playlist` | එක playlist එකක record එක (`--playlist` ඕන) | අනිත් playlists |
| `all` | ඔක්කොම (videos, skips, statistics) | **Spotify playlist එක** |

* **Spotify එකට කිසිම වෙනසක් නෑ** — reset එකෙන් වෙන්නේ sync එක කරපු දේ **අමතක වෙන එක** විතරයි. ඒ නිසා ඊළඟ run එකේදී මුළු playlist එකම ආයේ search වෙලා, නැති ඒවා add වෙනවා (Spotify එක duplicate ඒවා අයින් කරනවා).
* `--yes` නැතුව = **dry run**. මොනවද යන්නේ කියලා කලින් print වෙනවා.
* `data/sync-state.json.bak` එකක් ඉතුරු වෙනවා (ඕන නැත්නම් `--no-backup`).
* **Actions වලින්:** Run workflow → *Emergency: reset the sync database* → scope එක තෝරන්න. ඒක sync එකට **කලින්** දුවනවා, ඒ නිසා එකම run එකේදී database එක rebuild වෙනවා. Dry-run box එක tick කරලා තිබ්බොත් reset එක **preview** එකක් විතරයි.

## 2b7. Credit splitting fix (2026-11-04)

`REVERSED` 17 real queries ගිහින් 0ක් හම්බුණේ **bug දෙකක්** නිසා:

| bug | උදාහරණය | දැන් |
|---|---|---|
| ` x ` splitter එක නමක තියෙන **X** එකත් කැපුවා | `MC X & DJ Y` → `["MC", "DJ Y"]` (Spotify එකේ "MC" කියලා artist කෙනෙක් නෑ) | `["MC X", "DJ Y"]` |
| Spotify එකේ එකම artist නමක් විදිහට තියෙන collab එක conflict එකක් විදිහට පෙනුණා | artist `MC X & DJ Y` vs credit `MC X` / `DJ Y` → conflict | **match** (වචන ඇතුළෙත් compare කරනවා) |

* සැබෑ collab markers තාම split වෙනවා: `A x B`, `DJ NEO x MC X`, `Nulteex, ewyx`, `MC KIT & DJ X`.
* වෙන artist කෙනෙක් තාම **conflict** — ලිහිල් වුණේ නෑ.
* `MATCHER_VERSION` **14** → මතක තියෙන skips වලට තව එක try එකක්.
* `--stats` table එකේ දැන් **tried** වුණ හැම step එකකටම row එකක් (`cached` = queries ටික cache එකෙන්).

## 2b1a. Rate limit — search ගණන පාලනය

Steps 29ක් තියෙන නිසා එක සින්දුවකට search 30ක් යන එක නවත්තලා තියෙනවා:

1. **Extra steps යන්නේ skip වුණ සින්දුවලට විතරයි.** `STRICT`/`LOOSE`/`DETAIL` වලින් හම්බ වුණොත්, නැත්නම් සින්දුව දැනටමත් playlist එකේ තියෙනවා නම් → අමතර query **0**.
2. **එකම query එක දෙපාරක් යන්නේ නෑ.** Run එක ඇතුළේ cache එකක් තියෙනවා (`SEARCH_CACHE_MAX` = 5000). `Nulteex shaka` යැව්වට පස්සේ `shaka` එකට ආයේ request එකක් යන්නේ නෑ. Run එක ඉවර වෙද්දී log එකේ: `Spotify searches: 41 real query(s), 17 reused from the run cache`.
3. **Search දෙකක් අතරේ පරතරයක්.** `SEARCH_PAUSE_SECONDS` (default `0.5s`) — `REQUEST_DELAY_SECONDS` (default 2s) උඩින්.
4. **429 ආවොත්** `Retry-After` එක බලලා ආයේ උත්සාහ කරනවා (read requests 3 වතෙක්), ඒ වගේම ඒ run එකේ ඉතුරු searches අතරේ පරතරය **දෙගුණ** වෙනවා — උපරිම `30s`.
5. **Session එක මැරිලා නම් (403 / blocked cookie) ඉතුරු steps දුවන්නේ නෑ** — එකම error එකට steps 29ක් වියදම් කරන එක නවත්තලා, run එක එහෙමම fail වෙනවා.

## 2b1b. Skip වෙන සින්දුවක් අතින් add කරන්න (manual pick)

Report එකේ skip වෙන හැම සින්දුවකටම (මුල් 5ට) Spotify search link එකකුයි, override key එකකුයි දෙනවා:

```
#1 SKIP: DESTELLO - HDN | VIRAL PHONK — youtu.be/aLZNbOUOyI4 · No confident artist/title/version match
   pick: https://open.spotify.com/search/DESTELLO%20-%20HDN  →  track-overrides.json: "aLZNbOUOyI4": "<track id>"
```

1. Link එක open කරලා හරි track එක තෝරන්න → **⋯ → Share → Copy link** (`open.spotify.com/track/XXXX…`)
2. `data/track-overrides.json` එකට `"aLZNbOUOyI4": "XXXX…"` (22 අකුරු track id) දාන්න
3. ඊළඟ run එකේදී ඒක **search නොකර** කෙලින්ම add වෙනවා (`MANUAL` method)

## 2b2a. Label Engine වගේ double line එක

```
SHAKA (SLOWED) · Nulteex · ewyx     ← song(version එකත් එක්ක) · artist · artist
SHAKA                                ← ඊට පස්සේ එන plain song line එක
℗ INTERTONE
Producer: Ion Purice                 ← real names, search කරන්නේ නෑ
```

* `credit line` එකේ විතරක් artists ගන්නවා; ඊට පස්සේ එන plain song line එක artist කියලා ගන්නේ නෑ.
* **credit කරලා තියෙන එක artist කෙනෙක් ගැලපුණා නම් ඇති** — Spotify එකේ `ewyx` නැතුව `Nulteex` විතරක්
  තිබ්බත් match වෙනවා. ඒත් track එකේ artist `Somebody` විතරක් නම් → refuse (credit එකට විරුද්ධයි).
* `Nulteex` ↔ `Nulteex Music` වගේ කෙටි/දිගු නම් එකම කෙනා විදිහට ගන්නවා.

## 2b2b. `STRICT` ඇයි අඩු? — description එකේ තියෙන artist credit

Distributor ලාගේ uploads වල artist නම **title එකේ නෑ**, description එකේ විතරයි:

```
Provided to YouTube by DistroKid

FUNK TONTO · MC Ombrinho          ← song · artist

℗ 2026 Raiden
```

කලින් script එක `Raiden` (channel එකේ නම) artist කියලා ගත්තා → හරි track එක ආවත් `artist_ok()` එකෙන්
refuse වුණා → `STRICT` fail, ඒ නිසා extra steps වලට වැටුණා. දැන්:

* description එකේ `Song · Artist` line එකේ **song කොටස video title එකේ මුල** නම් (`FUNK TONTO` +
  `(feat. Mc Ombrinho) [Slowed]`) ඒකෙන් artist ගන්නවා, song එක විදිහට තියෙන්නේ video title එකම
  (version වචන එහෙමම තියෙනවා).
* title එකේ artist credit එකක් නැත්නම්, `artist_ok()` description එකේ artist එකෙන් බලනවා →
  ඒ නිසා **`STRICT` එකෙන්ම** match වෙනවා.
* description එකේ තියෙන ඒක **වෙන සින්දුවක්** නම් → ගන්නේ නෑ. Artist වැරදි නම් → ගන්නේ නෑ.
* `(feat. X)` block එක දැන් song name එකේ කොටසක් නෙවෙයි — Spotify එකේ `FUNK TONTO` (feat. artist
  වෙනම credit කරලා) එකම සින්දුව විදිහට match වෙනවා. Version වචන තියෙන්නේ එහෙමම (slowed ≠ original).

## 2b3. `Release - Topic` වගේ channel වල ඒවා

YouTube එකේ `… - Topic` channels දෙකක් තියෙනවා:

| Channel | මොකක්ද | script එකේ |
|---|---|---|
| `HDN - Topic` | artist කෙනෙක්ගේ ඒකම නමින් තියෙන page එක | artist = `HDN` ✅ |
| `Release - Topic`, `Releases - Topic`, `Record Release` | label එකේ compilation page එක | artist කියලා ගන්නේ **නෑ** ❌ |

`Release - Topic` එකේ `MONTAGEM GALACTO LOCONA (Ultra Slowed)` වගේ title එකකට කලින් artist = `Release` කියලා
ගත්තා → හැම query එකකුත් `Release MONTAGEM …` වුණා → `artist_ok()` එකෙන් හරි track එකත් **refuse** වුණා.
දැන් artist credit එකක් නෑ කියලා ගන්නවා, title එක විතරක් search වෙනවා (version + title චෙක් එකම තියෙනවා).

## 2b4. Slowed ඉණිමඟ (`SLOWED` step)

Video එක `Ultra Slowed` නම්, Spotify එකේ ඒ සින්දුවේ `Ultra Slowed` version එක නැති වෙලා **Slowed** එක විතරක්
තියෙන්න පුළුවන්. `SLOWED` step එක දැන් ඒක ගන්නවා — ඒත් **original, sped up, remix** කවදාවත් ගන්නේ නෑ,
සහ **වෙනස් rung දෙකක්** එකට ආවොත් (Slowed + Super Slowed) තෝරන්නේ නෑ.

## 2c. `ALBUM` / `PART` / `POPULAR` — Spotify naming එකේ අවුල්

Spotify එකේ track name එකයි YouTube title එකයි හැම වෙලාවෙම එකට ලියන්නේ නෑ:

| YouTube title | Spotify | කලින් | දැන් |
|---|---|---|---|
| `FUNK TONTO (feat. Mc Ombrinho) [Slowed]` | track `FUNK TONTO, Pt. 2 (feat. Mc Ombrinho)`, album `FUNK TONTO (Slowed)` | skip | ✅ `ALBUM`+`PART` |
| `X` (album `X - Single`) | `X` / `X (Slowed)` | skip | ✅ `ALBUM` |
| `LUZ` | same title track 3ක් (duplicate uploads) | skip (ambiguous) | ✅ `POPULAR` (වැඩිම play) |

* `ALBUM` — version වචන album එකේ තියෙනවා නම් ඒකත් සමඟ බලනවා (`version_signature` name + album මත).
* `PART` — `, Pt. 2`, `(Pt. 1)` කපලා ඉතුරු නම සමානද බලනවා; **part number එක ගණන් ගන්නේ නෑ** (එකම සින්දුවේ කොටස්), ඒත් slowed/sped වෙනස එහෙමම බලනවා.
* `POPULAR` — **අන්තිම tie-break එක**: එකම (title, artists) ඇති results කීපයක් ආවොත් වැඩිම playcount එක ගන්නවා. Play ගණනක් නැත්නම් හෝ ගණන සමාන නම් → **තෝරන්නේ නෑ** (අහඹුවට ගන්නේ නෑ). Title එක නොගැලපෙන එකක් popularity එකෙන් ගන්නේ නෑ.

---

## 2d. `--explain` — skip වුණ සින්දුවක් ඇයි skip වුණේ

Actions log එකේ බැලුවට වඩා පහසුවෙන්: **ඔබේ computer එකේ** (Actions එකේ නෙවෙයි) මේක දුවන්න —

```bash
cd spotify-yt-playlist-sync
export SPOTIFY_COOKIE_FILE=~/cookies/sp_dc.txt
.venv/bin/python -m syncer.app --explain
```

එකින් එක skip වුණ සින්දුවකට මේක print වෙනවා:

```
MONTAGEM RUNE - WUYS x KIT   (youtu.be/aLZNbOUOyI4)
  parsed as: ('WUYS', 'MONTAGEM RUNE x KIT')
  STRICT   → (no results)
  LOOSE    → MONTAGEM RUNE — WUYS, KIT
  CHANNEL  q='WUYS MONTAGEM RUNE'   → MONTAGEM RUNE — WUYS | MONTAGEM RUNE (Slowed) — WUYS
  verdict: MATCH LOOSE
```

* ලියන්නේ **මුල් 25** skip වුණ සින්දු විතරයි.
* මේකෙන් **Spotify එකට මොකුත් add වෙන්නේ නෑ, database එකත් වෙනස් වෙන්නේ නෑ** (read-only).
* Search කරන නිසා `SPOTIFY_COOKIE_FILE` ඕන. Cookie නැත්නම් `Could not start a Spotify session: …` කියලා නවතිනවා — steps දුවන්න cookie ඕන.
* `BROKEN` වගේ steps වලට **channel එකේ නම** වැදගත්: `HDN🎹`, `HDN Music`, `Raiden - Topic` වගේ නම් වලින්
  glyph / `- Topic` / `Music` අයින් වෙලා search වෙන්නේ `HDN`, `Raiden` විදිහට (නම සම්පූර්ණයෙන් symbols නම්
  ඒක search term එකක් විදිහට ගන්නේ නෑ).
* `verdict: MATCH <STEP>` කියලා එනවා නම් ඒ සින්දුව Spotify එකේ **ඇති**, ඒත් run එකේදී **ඒ step එක දුවලා නෑ** (හෝ ඒ වෙලාවේ search result වෙනස්) — එහෙම එකක් එවන්න, ඒ step එක හදන්න.
* `verdict: still no match` නම් Spotify results වලට ගැලපෙන එකක් නෑ — ඒ පේළියේ පේන `q=` query එකෙන් ඒ නම Spotify එකේ search කරලා බලන්න.
* ඊට කලින් run එකක් `--save-explain` එකෙන් run කරලා නම්, database එකේ ඒ results තියෙනවා → `--explain` ආයේ search නොකර ඒවා පෙන්නනවා.

---

## 3. Report එකේ බලන විදිය

හැම step එකක් වැඩ කළොත් log line එකේ **ඒ step එකේ නම** එනවා:

```
YouTube → Spotify DRY RUN: SUCCESS
Would add: 37 | Skipped: 5 | Failed: 0
Matched by extra step: SUFFIX ×2, TOPIC ×1

Why songs were skipped:
  • 5 × No confident artist/title/version match
```

```
#2 WOULD ADD: DESTELLO - HDN · VIRAL PHONK — youtu.be/aLZNbOUOyI4 · SUFFIX · open.spotify.com/track/…
```

`Matched by extra step:` line එක **කොයි step එක වැඩ කරනවද** කියලා කියනවා (STRICT/LOOSE/DETAIL ඒකේ එන්නේ නෑ — ඒවා මුල් ක්‍රම 3).

Match නොවුණු සින්දුවකට Actions log එකේ මේකත් තියෙනවා — **කොයි steps ට්‍රයි කළාද** කියලා:

```
INFO SKIP aLZNbOUOyI4: no confident artist/title/version match (video: …) (saved; not searched again)
INFO SKIP aLZNbOUOyI4: extra steps tried: CHANNEL, SUFFIX, DURATION, ARTISTS, …
```

---

## 4. අලුත් step එකක් දාන විදිය (2 විනාඩියේ)

`syncer/search_steps.py` එකේ අගට:

```python
class MyStep(Step):
    code = 'MYSTEP'
    title = 'මොකද කරන්නේ කියලා එක පේළියක්'

    def applies(self):                 # මේ step එක මේ සින්දුවට අදාළද?
        return bool(self.parsed)

    def run(self, client, token):
        candidates = self.search(client, token, self.parsed[0], self.version_text)
        keep = [t for t in self.version_checked(candidates)      # version සමානද
                if name_matches(self.version_text, t)             # නම සමානද
                and artist_ok(self, t)]                          # artist conflict නැද්ද
        return one_of(keep)           # 2ක් තියෙනවා නම් → None (අහඹුවට තෝරන්නේ නෑ)
```

ඊට පස්සේ `STEPS` tuple එකට `MyStep` එකතු කරන්න. Test එකකුත් `tests/test_search_steps.py` එකට දාන්න.

---

## 5. Step එකක් අයින් කරන්න / නවත්තන්න

- `STEPS` tuple එකෙන් අයින් කරන්න (code එක ඉතුරු කරන්න පුළුවන්)
- නැත්නම් `applies()` එකේ `return False`
- අයින් කළොත් `MATCHER_VERSION` එක **bump කරන්න එපා** — ඒකෙන් DB එකේ තියෙන skips ආයේ try වෙනවා (ඒක ඕන වෙන්නේ rules වැඩි දියුණු කළොත් විතරයි)

## 6. පොදු ප්‍රශ්න

**Q. Steps 29ම හැම සින්දුවකටම දුවනවද?**
නෑ. `applies()` එකෙන් අදාළ නැති ඒවා මුලින්ම අයින් වෙනවා (උදා: `REVERSED` දුවන්නේ artist credit එකේ `x`/`,` තියෙන සින්දුවලට විතරයි).
Match නොවුණු සින්දුවකට steps 8–11ක් විතරයි දුවන්නේ, එකකට search 1–3ක්.

**Q. Run එක slow වෙනවද?**
පළමු run එකේදී match නොවන සින්දු වලට search කීපයක් යනවා (delay 2s නිසා ~20s වැඩි). ඒත් ඒ සින්දු දැන් DB එකේ `skipped` යටතේ save වෙනවා → ඊළඟ runs වලට search එකක්වත් නෑ.

**Q. වැරදි සින්දුවක් add වුණොත්?**
`data/track-overrides.json` එකෙන් ඒ video ID එකට හරි track එක දාන්න (manual override හැම වෙලාවෙම දිනනවා). වැරදි step එක මොකක්ද කියලා log line එකේ `method` එකෙන් තේරෙනවා → ඒ step එකේ `applies()`/threshold එක හදන්න.
