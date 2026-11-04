# 🔎 13 — Extra search steps (16 වෙන වෙනම ක්‍රම)

මේ ගොනුව කියවන්නේ **"ඇයි මේ සින්දුව add වුණේ නැත්තේ?"** කියන ප්‍රශ්නයට උත්තර දෙන්න.
පළමු ක්‍රම 3 (`STRICT` → `LOOSE` → `DETAIL`) miss වුණාම, ඊට පස්සේ **මේ 15 ක්‍රම පිළිවෙලට** ට්‍රයි වෙනවා.
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

## 2. Steps 15

| # | Code | මොකද කරන්නේ | උදාහරණය |
|---|---|---|---|
| 1 | `REVERSED` | `Song - Artists` පෙරළිලා තියෙන ඒවා (artist credit දකුණේ) | `QUERO AMOR - SXYGX x FYU` |
| 2 | `SINGLE` | collab එකේ එක අයෙක්ගේ නමින් විතරක් search | `MONTAGEM RUNE - WUYS x KIT` |
| 3 | `CHANNEL` | YouTube channel නම artist විදිහට | uploader ගේ නම = artist |
| 4 | `TOPIC` | `Artist - Topic` channel එකේ ඇත්ත නම | `SHAKA - Topic` → SHAKA |
| 5 | `SUFFIX` | title එකේ marketing කපනවා (`\| GENRE` වගේ කොටස්) | `DESTELLO - HDN` + `VIRAL PHONK` → HDN |
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
| 16 | `TOPRESULT` | **අන්තිම උත්සාහය:** search එකේ **මුලින්ම එන result එක** ගන්නවා — ඒත් ඒක ඇත්තටම ඒ සින්දුවද කියලා 3කින් බලලා | පහළ `TOPRESULT` කොටස බලන්න |

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

⚠️ මේක **අන්තිම step එක** — අනිත් 15ම fail වුණාට පස්සේ විතරයි දුවන්නේ. `TOPRESULT` කියලා report එකේ පේනවා නම්, ඒ line එක දෙපාරක් බලන්න (Spotify link එක open කරලා) — වැරදි නම් `data/track-overrides.json` එකෙන් හදන්න.

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

**Q. Steps 15ම හැම සින්දුවකටම දුවනවද?**
නෑ. `applies()` එකෙන් අදාළ නැති ඒවා මුලින්ම අයින් වෙනවා (උදා: `REVERSED` දුවන්නේ artist credit එකේ `x`/`,` තියෙන සින්දුවලට විතරයි).
Match නොවුණු සින්දුවකට steps 8–11ක් විතරයි දුවන්නේ, එකකට search 1–3ක්.

**Q. Run එක slow වෙනවද?**
පළමු run එකේදී match නොවන සින්දු වලට search කීපයක් යනවා (delay 2s නිසා ~20s වැඩි). ඒත් ඒ සින්දු දැන් DB එකේ `skipped` යටතේ save වෙනවා → ඊළඟ runs වලට search එකක්වත් නෑ.

**Q. වැරදි සින්දුවක් add වුණොත්?**
`data/track-overrides.json` එකෙන් ඒ video ID එකට හරි track එක දාන්න (manual override හැම වෙලාවෙම දිනනවා). වැරදි step එක මොකක්ද කියලා log line එකේ `method` එකෙන් තේරෙනවා → ඒ step එකේ `applies()`/threshold එක හදන්න.
