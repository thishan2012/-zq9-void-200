# මම හදපු Playlist Sync එක — Setup එක (සිංහල)

මේක ඔයා දුන්න zip එකේ code එකේ පිළිවෙළම, ඒත් ඔයාගේ අවශ්‍යතා 6ට හදලා:

| # | ඔයා ඉල්ලපු දේ | කළේ කොහොමද |
|---|---|---|
| 1 | YT pagination (50/page, 200 = 4 pages) | `nextPageToken` loop එක දැනටමත් තිබුණා — දැන් log එකේ page ගාණ print වෙනවා ("page 1…4, 200 items"). |
| 1c | Database commit එකේ නම `github-actions[bot]` වෙනුවට වෙනස් කරන්න ඕන | Repository → Settings → Variables → **`COMMIT_NAME`** = `thishcrvwqe-bot` (default එකම ඒක). Email එක බොරු කරන්න බෑ — ඒක bot ගේම වෙන්න ඕන, නැත්නම් push reject වෙනවා |
| 1b | **හදිසි අවස්ථාවක** database එක reset කරන්න ඕන | Actions → **Run workflow** → *Emergency: reset the sync database* (`history` / `playlist` / `all`). Local එකේ නම් `python -m syncer.app --reset-db all --yes`. **Spotify playlist එකට අත ගහන්නේ නෑ**, `.bak` copy එකක් ඉතුරු වෙනවා |
| 2 | Skip වුණ සින්දුවක් ආයේ try කරන්න ඕන | **ඉරිදා 03:00 UTC run එකේදී තනියෙන්ම** වෙනවා (දවස් 7ට වඩා පරණ skips). දැන්ම බලන්න `python -m syncer.app --retry-expired`, එකක් ආයේ try කරන්න `--forget-video <id>` |
| 2b | Spotify rate limit (search 200 = block) | `REQUEST_DELAY_SECONDS` (default **2s**, හැම request එකට කලින්) + `SEARCH_PAUSE_SECONDS` (default **0.5s**, search දෙකක් අතරේ; 429 ආවොත් 30s වෙනකම් දෙගුණ වෙනවා). එකම query එක දෙපාරක් යන්නේ නෑ (run cache). අලුතෙන්: 429/5xx ආවොත් **read** requests `Retry-After` එක බලලා 3 වතාවක් තෙක් ආයේ උත්සාහ කරනවා. Write එකක් කවදාවත් retry කරන්නේ නෑ. |
| 3 | Batch add (100/request) | `add_batch()` අලුතෙන්. 200 සින්දු = **requests 2** (100 + 100). `SPOTIFY_BATCH_SIZE` එකෙන් 1–100 අතර වෙනස් කරන්න පුළුවන්. |
| 4 | Code එකේ තියෙන playlist links replace | `sync.yml` එකේ `YOUTUBE_PLAYLIST` / `SPOTIFY_PLAYLIST` — `REPLACE_WITH_YOUR_…` placeholders. Repository variables වලින් override කරන්නත් පුළුවන් (secrets නැතුව links විතරක්). |
| 5 | YT = main source, read-only | YouTube API එකෙන් **කියවනවා විතරයි** (`playlistItems.list`, `videos.list`). YouTube එකට මොනවත් ලියන්නේ නෑ. Spotify එකට add විතරයි. |
| 6 | එකම song එක ආයේ add නොවෙන්න | ත්‍රිත්ව ආරක්ෂාව: ① `data/sync-state.json` (video ID → track ID) ② add කරන්න කලින් playlist එකේ දැනට තියෙන track IDs බලනවා (තිබුණොත් **SKIP**, next song) ③ එකම track එකට videos දෙකක් ආවොත් එකයි add වෙන්නේ. Video එක playlist එකේ දෙපාරක් තිබ්බත් skip. |
| 7 | Telegram එකට **full log** | එක run එකකට messages දෙකක්: **Summary** (counts + SKIP/FAIL විස්තර) + **Full log** (හැම සින්දුවක්ම: #number, ADD/WOULD ADD/SKIP/FAIL, channel, YouTube link, match method, Spotify link, reason). 4000 chars ට වැඩි නම් line boundary එකෙන් split — කිසිම entry එකක් නැති වෙන්නේ නෑ. |
| — | Bonus | Batch එකක outcome අපැහැදිලි නම් (timeout / 5xx / GraphQL error) `pending` state එකේ තියලා run එක නවතිනවා; ඊළඟ run එකේ reconcile වෙනවා. Duplicate එකක් හදන්නේ නෑ. |

**ත්‍යාග 246ක්, හැමෝම pass** (`python -m unittest discover -s tests`). අලුත් `tests/test_remembered.py` (skip/fail මතකය) + `tests/test_search_steps.py` (steps 29). `tests/test_batching.py` එකේ: 200 songs → batches [100, 100], batch size cap, duplicate skip, second run = 0 adds, dry-run, pending reconcile, 429 retry, full-log.

---

## 1️⃣ Secrets — මේවා **අනිවාර්යයි**

Repo → **Settings → Secrets and variables → Actions → Secrets → New repository secret**

| Secret name | ගන්නේ කොහෙන්ද |
|---|---|
| `YOUTUBE_API_KEY` | Google Cloud Console → project එකක් හදලා **YouTube Data API v3** enable කරන්න → Credentials → API key. Key එක "Restrict key → YouTube Data API v3" කරන්න. |
| `SPOTIFY_COOKIE` | open.spotify.com එකට login වෙලා, browser extension එකකින් cookies **Netscape cookies.txt** format එකෙන් export කරන්න. **මුළු ෆයිල් එකේ අන්තර්ගතය** (lines ගාණක්) secret එකට paste කරන්න — `sp_dc` row එක අනිවාර්යයි. |
| `TELEGRAM_BOT_TOKEN` *(optional)* | Telegram → @BotFather → `/newbot` |
| `TELEGRAM_CHAT_ID` *(optional)* | bot එකට message එකක් එවලා `https://api.telegram.org/bot<TOKEN>/getUpdates` එකෙන් `chat.id` ගන්න |

⚠️ `SPOTIFY_COOKIE` = account credential එකක්. **disposable/test account** එකක් පාවිච්චි කරන්න. Workflow එකේ ඒක `cookies/spotify.txt` (git-ignored) එකට ලියලා job එක ඉවර වෙද්දී **delete** කරනවා — repo එකේ කවදාවත් commit වෙන්නේ නෑ.

## 2️⃣ Variables — optional (links මෙතනින් දාන්න පුළුවන්)

**Settings → Secrets and variables → Actions → Variables**

| Variable | Default | මොකද |
|---|---|---|
| `YOUTUBE_PLAYLIST` | sync.yml එකේ placeholder | Source playlist: `https://www.youtube.com/playlist?list=PL…` |
| `SPOTIFY_PLAYLIST` | sync.yml එකේ placeholder | Destination: `https://open.spotify.com/playlist/…` |
| `REQUEST_DELAY_SECONDS` | `2` | හැම request එකට කලින් delay (0–60). 200 songs → 1–2 හොඳයි. |
| `SEARCH_PAUSE_SECONDS` | `0.5` | search දෙකක් අතරේ අමතර පරතරය (0–60). 429 ආවොත් මේක තනියෙන් 30s වෙනකම් දෙගුණ වෙනවා. |
| `SPOTIFY_BATCH_SIZE` | `100` | එක request එකකට tracks (1–100). Spotify reject කරනවා නම් 50 කරන්න. |

Links දාන්න ක්‍රම 2ක්:
- **හොඳම:** ඒ නමින්ම variables 2ක් හදන්න (variables > placeholders).
- **නැත්නම්:** `.github/workflows/sync.yml` එකේ `REPLACE_WITH_YOUR_YOUTUBE_PLAYLIST_ID` / `REPLACE_WITH_YOUR_SPOTIFY_PLAYLIST_ID` ටික ඔයාගේ links වලින් replace කරන්න.

## 3️⃣ Workflow එක on කරන්න

1. **Settings → Actions → General → Workflow permissions → Read and write permissions** (bot එකට state file commit කරන්න ඕන නිසා).
2. Schedule එක දුවන්නේ **default branch** එකෙන්. ඒ නිසා workflow + secrets + `data/sync-state.json` default branch එකේ තියෙන්න ඕන.
3. `0 */4 * * *` = **දවසට 6** (05:30, 09:30, 13:30, 17:30, 21:30, 01:30 — Sri Lanka). Public repo නිසා minutes limit නෑ. වෙනස් කරන්න ඕන නම් cron line එක edit කරන්න — **UTC** වලින්. Scheduled runs default එකෙන්ම dry run; ඇත්තට ඕන නම් variable `SYNC_ENABLED=true`. **60-day rule:** public repo එකක activity නැතුව දවස් 60ක් ගියොත් GitHub schedule එක **silently disable** කරනවා — ඒ නිසා හැම මාසෙම 1 වෙනිදා එන run එක `Keep the schedule alive (monthly heartbeat)` කියලා commit එකක් දානවා (DB වෙනසක් නැතත්).
4. **Actions → YouTube to Spotify sync → Run workflow** → `dry_run` ✅ තියලා එක පාරක් දුවන්න. Telegram full log එක බලලා match වැරදි නම් `data/track-overrides.json` එකට manual mapping දාන්න. හරි නම් `dry_run` ❌ කරලා ආයේ දුවන්න.

200 සින්දුවක playlist එකකට ~5–10 min (delay නිසා). Job timeout 180 min නිසා ප්‍රශ්නයක් නෑ.

## 4️⃣ Local එකේ test කරන්න

```bash
cd spotify-yt-playlist-sync
python3.11 -m venv .venv && .venv/bin/pip install -r requirements.txt
.venv/bin/python -m unittest discover -s tests -v        # 246 tests

export YOUTUBE_PLAYLIST='https://www.youtube.com/playlist?list=PL…'
export SPOTIFY_PLAYLIST='https://open.spotify.com/playlist/…'
export YOUTUBE_API_KEY='…'
# cookie: cookies/spotify.txt එකට ඔයාගේ export එක දාන්න (git-ignored)
.venv/bin/python -m syncer.app --dry-run
```

## 5️⃣ මොකද වෙන්නේ එක run එකක

```
1. YouTube: playlistItems.list → pages (50/page loop, nextPageToken) → videos.list (50/batch)
2. Cookie → Spotify token (sp_dc + TOTP)
3. Spotify playlist එකේ දැනට තියෙන track IDs කියවනවා (fail-closed)
4. හැම video එකකටම: MANUAL → STRICT → LOOSE → DETAIL → SKIP
5. දැනට තියෙන / දැනට record වෙලා තියෙන ඒවා SKIP
6. ඉතුරු ටික 100 බැගින් batch add (pending → write → save)
7. Telegram: Summary + Full log
8. data/sync-state.json → git commit (bot)
```

හැම සින්දුවකම තීරණය log එකේ සහ Telegram full log එකේ තියෙනවා — `ADD`, `WOULD ADD`, `SKIP`, `FAIL` + reason + links.

> **අලුත්:** සම්පූර්ණ A–Z guide එක `spotify-yt-playlist-sync/instructions/` එකේ.
> එතනින් පටන් ගන්න 👉 [`instructions/README.md`](spotify-yt-playlist-sync/instructions/README.md)
> Secrets හරියටම දාන විදිය + "To the one who knows the secrets" 👉 [`01-repository-secrets.md`](spotify-yt-playlist-sync/instructions/01-repository-secrets.md)

තව විස්තර: `spotify-yt-playlist-sync/README.md`
