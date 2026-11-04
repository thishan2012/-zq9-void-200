# 📨 04 — Telegram (summary + full log)

## 1. Bot එකක් හදන්න

1. Telegram එකේ **@BotFather** → `/newbot` → නමක් + username (`…bot` අන්ත වෙන්න ඕන)
2. Token එක එනවා: `123456789:AAH…` → **`TELEGRAM_BOT_TOKEN`** secret එකට දාන්න
3. ඔයාගේ bot එකට **`/start`** එවන්න (bot එකට ඔයාට message එවන්න බෑ, ඔයා chat එකක් පටන් ගත්තොත් විතරයි)

## 2. Chat ID එක ගන්න

Browser එකේ මේ URL එක open කරන්න (token එක ඔයාගේ එක දාන්න):

```
https://api.telegram.org/bot<TOKEN>/getUpdates
```

Response එකේ `"chat":{"id":123456789, …}` → ඒ අංකය **`TELEGRAM_CHAT_ID`**.

- Group/Channel එකකට යවන්න ඕන නම් id එක **negative** අංකයක් (`-100…`) වෙනවා, ඒ නිසා bot එක ඒ group එකට **admin/member** කරන්න.
- `getUpdates` එකේ `[]` පෙන්නනවා නම්: bot එකට අලුතෙන් message එකක් එවලා ආයේ try කරන්න.

## 3. ඔයාට එන messages — **උපරිම 6ක්** (spam guard)

```text
[1] Summary  ← "Skipped" ගණන මෙතනින් explain වෙනවා
    YouTube → Spotify DRY RUN: SUCCESS
    Would add: 36 | Skipped: 5 | Failed: 0

    Why songs were skipped:
      • 5 × No confident artist/title/version match

    Per-song details follow.
    Full log: the Actions run log.

[2..6] Per-song log (compact, 1 line per song)
    YouTube → Spotify log (DRY RUN): 36 song(s) to report

    #1 SKIP: Artist - Song — youtu.be/xxxxxxxxxxx · No confident artist/title/version match
    #6 WOULD ADD: Artist - Song — youtu.be/xxxxxxxxxxx · STRICT · open.spotify.com/track/…
```

| රීතිය | අගය |
|---|---|
| එක run එකකට messages | **උපරිම 6** (`TELEGRAM_MAX_MESSAGES`) |
| Message එකක size | 4000 UTF-16 units (හැම message එකක්ම message boundary එකෙන් pack — සින්දුවක් මැදින් කැපෙන්නේ නෑ) |
| 6ට වඩා ඕන නම් | අන්තිම message එකේ `… N more message(s) omitted…` — විස්තර Actions log එකේ |
| Already synced / already in playlist / duplicate video | **skip ගොඩටවත්, log එකටවත් නෑ** — DB එකේ save විතරයි (ගණනෙත් නෑ) |
| No confident match / unavailable / same-track-in-run | **එක පාරයි** (link + හේතුව), ඊට පස්සේ DB එකේ `skipped` නිසා silent |
| FAIL | **දෙපාරක්** (`… logged once more, then go quiet` → `… last time logged`), ඊට පස්සේ silent |
| මේ පාර skip/fail වුණු එකක් ආයේ log වෙනවද? | **නෑ** — `data/sync-state.json` එකේ `skipped` / `failures` එකෙන් මතක තියාගන්නවා ([09](09-recovery-and-maintenance.md#1c-එකම-සින්දුව-ආයේ-log-වෙනවා-නම්)) |

උදා: 200-song playlist එකක dry run එකකදී **2–3 messages** (කලින් 14). සම්පූර්ණයෙන්ම අලුත් සින්දු 200ක් නම් **6**.

`Skipped: N` කියන්නේ **ඇත්තටම හේතුවක් නිසා** skip වුණු ගණන විතරයි (already added ඒවා ගණනට එන්නේ නෑ).
Telegram send fail වුණොත් (no secrets / blocked / rate limit) **ඒ report එකම Actions log එකට print වෙනවා** — කිසි දෙයක් නැති වෙන්නේ නෑ.

(Actions log එකේ තවම හැම සින්දුවකටම `ADD/WOULD ADD/SKIP/FAIL` line එකක් තියෙනවා — debug කරන්න ඕන නම් ඒක බලන්න.)

## 4. Secrets නැති නම්

Telegram configure නොකළොත් summary + full log **Actions log** එකේ විතරයි (`telegram not configured; summary only in Actions log`).
Sync එකට කිසිම බලපෑමක් නෑ.

## 5. Privacy

- Action log එකේ **secrets, tokens, HTTP bodies print වෙන්නේ නෑ**.
- Telegram එකට යන්නේ **public metadata** විතරයි: video title, channel, links, reply reason. Cookie/token කවදාවත් යන්නේ නෑ.
- Bot token එක තියෙන කෙනාට ඔයාගේ chat එකට message එවන්න පුළුවන් → token එක password එකක් වගේ තියාගන්න.
