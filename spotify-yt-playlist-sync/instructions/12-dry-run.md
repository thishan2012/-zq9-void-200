# 🧪 12 — DRY RUN (පළමුව මේකෙන් පටන් ගන්න 😌)

Dry run = **Spotify වලට කිසිම දෙයක් ලියන්නේ නෑ, ඒත් ඇත්තටම මොකද වෙන්නේ කියලා බලන එක.**
Add වෙන්නේ නෑ, add වුණු සින්දු DB එකට save වෙන්නේ නෑ. ඒත් YouTube කියවනවා, Spotify playlist එකේ තියෙන tracks කියවනවා, searches කරනවා, Telegram එකට **report** එක එවනවා.

> **එකම වෙනස:** skip/fail bookkeeping එක (`skipped` / `failures`) dry run එකේදීත් save වෙනවා. ඒකයි "එකම සින්දුව හැම run එකකම log වෙනවා" කියන එක නවත්තන්නේ — බලන්න [06-how-it-works](06-how-it-works.md#11-remembered-skips--failures-එකම-සින්දුව-දෙපාරකට-වඩා-log-නොවෙන්න).

---

## A. Actions එකෙන් (ඔයා ඉල්ලපු option එක)

**Actions → YouTube to Spotify sync → Run workflow** (right side එකේ **Run workflow** button එක)

එතන dropdown එකක් එනවා:

```
Use workflow from   [main ▾]
Dry run - preview only (no Spotify writes, no database changes)
  [✓]           ← default checked = DRY RUN
                          [Run workflow]
```

| Checkbox | මොකද වෙන්නේ |
|---|---|
| ✅ **checked** (default) | DRY RUN — `WOULD ADD` list එක විතරයි; Spotify add නෑ |
| ☐ unchecked | **LIVE** — Spotify එකට add වෙනවා + DB commit වෙනවා |

Run එක ඇතුළේ **Job summary** එකේ පේනවා:
```
### YouTube → Spotify: DRY RUN — Spotify untouched (only skip/failure bookkeeping is saved)
| Trigger | workflow_dispatch |
| Dry run | true |
```

### ⚠️ මේ option එක පේන්නේ නැත්නම්

GitHub workflow file එක **repo root එකේ `.github/workflows/`** එකේ තියෙන්න ඕන. ෆයිල් එක `spotify-yt-playlist-sync/.github/workflows/` ඇතුළේ තිබ්බොත් Actions tab එකේ **කිසිම workflow එකක් පේන්නේ නෑ** → Run workflow button එකක් නෑ.
මේ repo එකේ දැන් root එකේ copy එකක් තියෙනවා ✅ (project folder එකේ එක reference එකක් විදිහට විතරයි).

තවත් හේතු:
- Workflow එක **disabled** → Actions tab → "I understand my workflows, go ahead and enable them"
- Fork එකක ඉන්නවා නම් → fork එකේ Actions enable කරන්න, නැත්නම් upstream repo එකේ run කරන්න

---

## B. Schedule එකෙන් (auto runs)

Scheduled runs **default එකෙන්ම dry run** — එහෙම නැත්නම් මොකක් හරි වැරදිලා 200 සින්දුවක් යනවා 😅

| `vars.SYNC_ENABLED` | Scheduled run එකේ ප්‍රතිඵලය |
|---|---|
| (නෑ) / `false` | DRY RUN ✅ |
| `true` | LIVE SYNC |

**ඇත්තටම දුවන්න ඕන වෙලාවට:** Settings → Secrets and variables → Actions → **Variables** → `SYNC_ENABLED` = `true`.
Manual run එකට මේක බලපාන්නේ නෑ (manual run එකේදී checkbox එක තමයි නියමය).

---

## C. Local එකෙන්

```bash
cd spotify-yt-playlist-sync

# ක්‍රමය 1: flag
python -m syncer.app --dry-run

# ක්‍රමය 2: env var (workflow එකේ පාවිච්චි කරන්නේ මේකයි)
DRY_RUN=true python -m syncer.app
```

දෙකම එකම දේ — log එකේ මුලින්ම මේක පේනවා:
```
INFO DRY RUN: nothing will be written to Spotify and the database will not change
```

---

## D. Dry run එකේදී මොනවද සිද්ධ වෙන්නේ

| පියවර | Dry run | Live |
|---|---|---|
| YouTube playlist read | ✅ | ✅ |
| Spotify token ගන්නවා | ✅ | ✅ |
| Playlist එකේ දැනට තියෙන tracks කියවනවා | ✅ | ✅ |
| Spotify search | ✅ | ✅ |
| **Batch add** | ❌ | ✅ |
| `data/sync-state.json` — add වුණු සින්දු (`videos`) | ❌ | ✅ |
| `data/sync-state.json` — `skipped` / `failures` bookkeeping | ✅ (save වෙනවා) | ✅ |
| Bot commit | ❌ | ✅ |
| Telegram summary + full log | ✅ (`WOULD ADD` කියලා) | ✅ (`ADD` කියලා) |
| Already synced / already in playlist | ✅ (silent — DB විතරයි) | ✅ |

> Dry run එකේදී `pending` reconcile එකත් බලනවා — ඒත් එයා state එකට ලියන්නේ නෑ. Add වුණු සින්දු නම් dry run එකකින් පස්සේ කවදාවත් save වෙන්නේ නෑ; skip/fail bookkeeping විතරයි ලියවෙන්නේ.

---

## E. Dry run එකේ report එක කියවන විදිය

Telegram එකට messages 2–3ක් එනවා:

```
YouTube → Spotify DRY RUN: SUCCESS
Would add: 36 | Skipped: 5 | Failed: 0

Why songs were skipped:
  • 5 × No confident artist/title/version match

Per-song details follow.
Full log: the Actions run log.
```

```
YouTube → Spotify log (DRY RUN): 36 song(s) to report

#1 WOULD ADD: Artist - Song — youtu.be/… · STRICT · open.spotify.com/track/…

#2 SKIP: Artist - Other Song — youtu.be/… · No confident artist/title/version match
…
```

`Skipped: 5` කියන්නේ **ඇත්තටම හේතුවක් තියෙන** ඒවා විතරයි. දැනටමත් playlist එකේ/DB එකේ තියෙන ඒවා ගණනටවත් message එකටවත් එන්නේ නෑ.

බලන්න ඕන දේවල්:

| පේන දේ | තේරුම | කරන්න |
|---|---|---|
| `WOULD ADD` + `Match: STRICT` | හොඳම case — artist+title+version හරි | මොකුත් නෑ |
| `Match: LOOSE` / `DETAIL` | ටිකක් අඩු විශ්වාසය | Spotify link එක open කරලා සින්දුව හරිද බලන්න |
| `SKIP: No confident … match` | හම්බුනේ නෑ — **මේ පාර විතරයි** log වෙන්නේ | `data/track-overrides.json` එකට manual mapping |
| *(silent)* `Track already in Spotify playlist` / `Already recorded` | දැනටමත් තියෙනවා — **skip ගණනටවත්, Telegram එකටවත් එන්නේ නෑ**, DB එකේ save විතරයි | මොකුත් නෑ (හරි) |
| `FAIL: …` | search/add error | [07-troubleshooting](07-troubleshooting.md) |

හොඳ නම් විතරයි `dry_run` ☐ uncheck කරලා live run එකක් දාන්න.

---

## F. Dry run එකෙන් **verify වෙන්නේ නැති** දේ

Dry run එකේදී add request එක යන්නේ නෑ. ඒ නිසා:

- Playlist එකට **write කරන්න අවසර තියෙනවද** (Free account / collaborator) — ඒක live run එකේදී විතරයි තේරෙන්නේ
- Batch size (100) Spotify පිළිගන්නවද

ඒ නිසා පළමු live run එකේදී **playlist එක පොඩ්ඩක් බලන්න** (Telegram full log එකේ `ADD` vs `FAIL`).

---

## F2. Dry run එකේදී database එක

Dry run එකේදී **එක සින්දුවක්වත් `videos` එකට save වෙන්නේ නෑ** — `Saved songs` ගණන වෙනස් වෙන්නේ නෑ.
ඒත් `Skipped (not retried)` / `Failed (retried)` ගණන වැඩි වෙන්න පුළුවන්: ඒ bookkeeping එක dry run එකේදීත් save වෙනවා, commit message එක `Update skip/failure bookkeeping (dry run)`.
Live run එකකින් පස්සේ `Saved songs` වැඩි වෙනවා + commit message එක `Update playlist sync state`.

## G. ඉක්මන් recap

```text
පළමුව  : Run workflow + dry_run ✅   → full log බලන්න
හරි නම් : Run workflow + dry_run ☐    → tracks add වෙනවා + DB commit
ඊට පස්සේ: SYNC_ENABLED=true (variable) → දවසට 6ක් auto (හැම 4 පැයකට)
```
