# ⚙️ 05 — GitHub Actions (schedule, dry run, state commit)

## 1. Permissions (අනිවාර්යයි)

**Settings → Actions → General → Workflow permissions → Read and write permissions** → **Save**

ඇයි: run එක ඉවර වෙද්දී bot එක `data/sync-state.json` එක commit කරනවා. `Read` විතරයි නම් add වුණාට state save වෙන්නේ නෑ → ඊළඟ run එකේ duplicate check එක playlist එකෙන් විතරයි වෙන්නේ (එහෙමත් duplicate වෙන්නේ නෑ, ඒත් අතිරේක search නිකම්ම යනවා).

Branch protection තියෙනවා නම් bot එකට push කරන්න allow කරන්න, නැත්නම් state commit fail වෙනවා.

## 2. Enable / Disable

- Actions tab එකේ workflow එක **disabled** නම් → "I understand my workflows, go ahead and enable them"
- Run එකක් manually: **Actions → YouTube to Spotify sync → Run workflow**
  - Branch: default branch
  - `dry_run`: ✅ (preview) / ❌ (ඇත්තටම add)

## 3. Schedule

```yaml
on:
  schedule:
    - cron: '0 0,12 * * *'      # 00:00 සහ 12:00 UTC
```

| UTC | Sri Lanka (UTC+5:30) |
|---|---|
| 00:00 | **05:30** |
| 12:00 | **17:30** |

- GitHub cron **UTC විතරයි** — ඔයාට ඕන වෙලාව UTC එකට convert කරලා ලියන්න
- Scheduled runs **default branch එකෙන් විතරයි** → workflow + secrets + state එක default branch එකේ තියෙන්න ඕන
- GitHub පැය ගාණක් delay කරන්න පුළුවන් (busy times). හරියටම වෙලාවට ඕන නම් manual run එකක් දාන්න
- Repo එක දිගට inactive නම් GitHub schedules auto-disable කරනවා — Actions tab එකේ බලන්න

## 4. Workflow එකේ steps

```
1. checkout
2. setup-python 3.11 + pip install -r requirements.txt
3. Restore Spotify cookie    ← secrets.SPOTIFY_COOKIE → cookies/spotify.txt (umask 077)
4. Sync playlists            ← dry_run නම් --dry-run
5. Remove cookie file        ← always()
6. Save sync database        ← diff එකක් තියෙනවා නම් bot commit + push
```

Dry run එකකදී (manual) step 6 **skip** වෙනවා — database එකට කිසිම වෙනසක් නෑ.

## 5. Timeout / minutes

- Job timeout: **180 minutes** (`timeout-minutes: 180`)
- 200 songs ≈ **5–10 min** (delay 2s + searches + 2 batch adds) → minutes ගැන බය වෙන්න ඕන නෑ
- Free plan private repo: 2,000 min/month → දවසට 2 runs × ~8 min = ~480 min/month
- Public repo: Actions minutes **unlimited** (free)

කාලය අඩු කරන්න ඕන නම් `REQUEST_DELAY_SECONDS=1` (නමුත් rate limit අවදානම වැඩි) — හොඳම දේ default 2 තියාගන්න.

## 6. Logs

Run එකක් ඇතුළේ:
- **Sync playlists** step එකේ log එකේ හැම සින්දුවකටම `ADD / SKIP / FAIL / WOULD ADD` line එකක් තියෙනවා (+ `STRICT MATCH` etc.)
- **Summary at the end**: `Added: 187 | Skipped: 12 | Failed: 1`
- Telegram එකටත් යනවා ([04](04-telegram.md))

Log එකේ **secrets, tokens, cookie, HTTP response bodies print වෙන්නේ නෑ** (code එකෙන් හිතාමතාම වළක්වලා තියෙනවා).

## 7. Manual run එකක් නැවැත්වීම

Actions → run එක → **Cancel workflow**. ඒත් ඒ වෙනකොට add වෙච්ච batch එකේ tracks state එකේ record වෙලා තියෙන්න පුළුවන්, එහෙම නැත්නම් `pending` එකේ තියෙන්න පුළුවන් ([09](09-recovery-and-maintenance.md)).
