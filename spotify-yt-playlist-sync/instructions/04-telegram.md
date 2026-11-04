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
[1] Summary
    YouTube → Spotify DRY RUN: SUCCESS
    Would add: 36 | Skipped: 130 | Failed: 0

    Already synced / already in the playlist (125), saved to the database:
      • 125 × Track already in Spotify playlist

    Songs that did not go in:
      • 5 × No confident artist/title/version match

[2..6] Per-song log (compact, 1 line per song)
    YouTube → Spotify log (DRY RUN): 41 song(s) to report
    Already present, not listed (125): 125 × Track already in Spotify playlist

    #1 SKIP: Artist - Song — youtu.be/xxxxxxxxxxx · No confident artist/title/version match
    #131 WOULD ADD: Artist - Song — youtu.be/xxxxxxxxxxx · STRICT · open.spotify.com/track/…
```

| රීතිය | අගය |
|---|---|
| එක run එකකට messages | **උපරිම 6** (`TELEGRAM_MAX_MESSAGES`) |
| Message එකක size | 4000 UTF-16 units (හැම message එකක්ම message boundary එකෙන් pack — සින්දුවක් මැදින් කැපෙන්නේ නෑ) |
| 6ට වඩා ඕන නම් | අන්තිම message එකේ `… N more message(s) omitted…` — විස්තර Actions log එකේ |
| Already synced / already in playlist | විස්තර නෑ — ගණන විතරයි |
| No confident match / unavailable / FAIL | හැම එකක්ම, link + හේතුව සමඟ |

උදා: 200-song playlist එකක dry run එකකදී **3 messages** (කලින් 14). සම්පූර්ණයෙන්ම අලුත් සින්දු 200ක් නම් **6**.
Telegram send fail වුණොත් (no secrets / blocked / rate limit) **ඒ report එකම Actions log එකට print වෙනවා** — කිසි දෙයක් නැති වෙන්නේ නෑ.

(Actions log එකේ තවම හැම සින්දුවකටම `ADD/WOULD ADD/SKIP/FAIL` line එකක් තියෙනවා — debug කරන්න ඕන නම් ඒක බලන්න.)

## 4. Secrets නැති නම්

Telegram configure නොකළොත් summary + full log **Actions log** එකේ විතරයි (`telegram not configured; summary only in Actions log`).
Sync එකට කිසිම බලපෑමක් නෑ.

## 5. Privacy

- Action log එකේ **secrets, tokens, HTTP bodies print වෙන්නේ නෑ**.
- Telegram එකට යන්නේ **public metadata** විතරයි: video title, channel, links, reply reason. Cookie/token කවදාවත් යන්නේ නෑ.
- Bot token එක තියෙන කෙනාට ඔයාගේ chat එකට message එවන්න පුළුවන් → token එක password එකක් වගේ තියාගන්න.
