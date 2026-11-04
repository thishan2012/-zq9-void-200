# ❓ 10 — FAQ

**Q. `SPOTIFY_BATCH_SIZE=100` කියන්නේ මොනවා ද?**
Spotify playlist එකට **එක HTTP request එකකින් tracks කීයක් add කරන්නද** කියන එක. Spotify එකේ උපරිමය **100**. 200 songs → requests 2 (100+100). ඒක 1–100 අතර වෙනස් කරන්න පුළුවන්; 100ට වඩා දුන්නොත් 100ට clamp වෙනවා. සාමාන්‍යයෙන් **100 තියන්නම** — වෙනස් කරන්න ඕන නම් Spotify batch එකක් reject කරන විට විතරයි (එතකොට 50).

**Q. Secrets 6ක් දාලා තියෙනවා — තව මොනවද ඕන?**
`YOUTUBE_API_KEY`, `SPOTIFY_COOKIE`, `YOUTUBE_PLAYLIST`, `SPOTIFY_PLAYLIST`, `TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID` — මේ 6 **ප්‍රමාණවත්** ✅. අමතරව optional 2ක්: `REQUEST_DELAY_SECONDS` (default 2), `SPOTIFY_BATCH_SIZE` (default 100) — මේවා **Variables** එකට දාන්න (Secrets එකට දැම්මත් දැන් වැඩ කරනවා). නැතුවත් sync එක වැඩ කරනවා.

**Q. `YOUTUBE_PLAYLIST` / `SPOTIFY_PLAYLIST` secrets වලට දැම්මද වැරදි?**
වැරදි නෑ. Workflow එක `secrets.X || vars.X || placeholder` කියලා කියවනවා — ඒ නිසා secrets එකේ තිබ්බත් හරි, variables එකේ තිබ්බත් හරි. **එකම නමින් දෙකේම තිබ්බොත් secrets එක දිනනවා.**

**Q. එකම song එක ආයේ ආයේ add වෙන්නේ නැද්ද?**
නෑ — ආරක්ෂාව 4ක්: ① state file (`videos` map) ② add කලින් playlist එකේ තියෙන track IDs ③ එකම track එකට videos දෙකක් ආවොත් එකයි ④ pending logic (අපැහැදිලි write එකක් auto-retry කරන්නේ නෑ). Job එක මැදින් කැඩුණත් batches state එකේ save වෙලා තියෙනවා.

**Q. Playlist එකේ දැනටමත් තියෙන සින්දු add වෙනවද?**
නෑ. `existing_tracks()` එකෙන් playlist එකේ track IDs ඔක්කොම කියවලා, ඒවා `SKIP: Track already in Spotify playlist` කියලා skip වෙනවා + state එකේ record වෙනවා.

**Q. Spotify එකෙන් සින්දු delete කරනවද?**
කවදාවත් නෑ. මේක one-way add-only sync එකක්. Playlist එකේ ඉඳන් අතින් මකලා තිබ්බත් ආයේ add වෙන්නේ නෑ (state එකේ record වෙලා නිසා) — ආයේ ඕන නම් state එකේ entry එක අයින් කරන්න.

**Q. Add කරන songs save වෙනවද? DB එකක් තියේද?**
ඔව් — `data/sync-state.json` (video ID → Spotify track ID). Live run එකක් ඉවර වෙද්දී bot එක ඒක commit කරනවා. ඒක තමයි "එකම සින්දුව ආයේ add නොවෙන්න" කියන එකේ ප්‍රධාන ආරක්ෂාව. බලන්න: Job summary එකේ `🗄️ Database` table, `python -m syncer.app --db-summary`, හෝ Telegram full log එකේ ADD lines.

**Q. දවසට කී පාරක් දුවනවද?**
`0 */4 * * *` = **දවසට 6** (හැම 4 පැයකට). Public repo නිසා minutes limit නෑ. Scheduled runs dry run — ඇත්තට ඕන නම් `SYNC_ENABLED=true`.

**Q. 200 songs කී වෙලාවක් ගන්නවද?**
Delay 2s + search ≈ 5–10 min. Job timeout 180 min. GitHub Actions minutes (private repo) ~8 min/run.

**Q. "Track already in Spotify playlist" කියන ඒවා Telegram එකට එන්නේ නෑ — හරිද?**
ඔව්, ඒක හිතාමතාම. ඒ සින්දු database එකේ save වෙනවා (ආයේ search කරන්නේ නෑ), ඒත් message එකක් එවන්නේ නෑ. Header එකේ ගණන විතරයි: `Already present, not listed (125): 118 × Track already in Spotify playlist`.
**Add නොවුණු නියම හේතු** තියෙන ඒවා (`No confident artist/title/version match`, `Unavailable…`, `FAIL`) තවම විස්තර සහිතව එනවා 👍

**Q. Telegram එකට message ගොඩක් එනවා 😅 (bot ban වෙයිද?)**
දැන් නෑ. එක run එකකට **උපරිම messages 6ක්** — හැම message එකකුත් 4000 characters දක්වා pack කරලා. 200-song playlist එකකට **3** විතරයි. `bot ban` වෙන එක නවත්තන්න තමයි මේක. ඊට වඩා ඕන නම් අන්තිම message එකේ `omitted` notice එකක් එනවා + Actions log එකේ සම්පූර්ණ විස්තර.

**Q. Dry run එකේදී "WOULD ADD" පෙන්නනවා, ඒත් playlist එකේ මොකුත් නෑ**
හරි — dry run එකේදී Spotify එකට කිසිම write එකක් නෑ, state එකත් save වෙන්නේ නෑ. `dry_run` uncheck කරලා ආයේ දුවන්න.

**Q. "No confident artist/title/version match" — ඇයි?**
YouTube title/description එකේ artist එක විශ්වාස කරන්න බැරි නම්, හෝ Spotify එකේ version එක වෙනස් නම් (උදා: `Slowed` vs original) code එක skip කරනවා — වැරදි සින්දුවක් add කරනවාට වඩා skip එක හොඳයි. විසඳුම: `data/track-overrides.json` එකට manual mapping.

**Q. Spotify Free account එකකින් වැඩ කරනවද?**
සමහර වෙලාවට නෑ (playlist edit block/401/403). Test account එකකින් try කරන්න; නැත්නම් Premium.

**Q. Cookie එක කී දවසකට expire වෙනවා?**
Spotify කියන්නේ නෑ. සාමාන්‍යයෙන් සති කීපයක් – මාස කීපයක්. Log එකේ 400/401 ආවම අලුත් export එකක් දාන්න.

**Q. Repo එක public කරන්න පුළුවන්ද?**
පුළුවන් — secrets කිසිවක් repo එකේ නෑ, cookie එක secret එකෙන් එනවා. **ඒත්** පරණ commit එකක cookie blob එකක් තියෙනවා නම් ඒක revoke කරලා history එක clean කරන්න ([08](08-security-and-cookie-hygiene.md)).

**Q. Workflow එකේ playlist links කොහෙද?**
`.github/workflows/sync.yml` එකේ `REPLACE_WITH_YOUR_…` placeholders — ඒවා secrets/variables වලින් override වෙනවා. කවදාවත් workflow file එකේ secret එකක් අගයක් ලියන්න එපා.

**Q. Local එකේ run කරන්නේ කොහොමද?**
```bash
cd spotify-yt-playlist-sync
python3.11 -m venv .venv && .venv/bin/pip install -r requirements.txt
export YOUTUBE_PLAYLIST=… SPOTIFY_PLAYLIST=… YOUTUBE_API_KEY=…
# cookie: cookies/spotify.txt (git-ignored)
.venv/bin/python -m syncer.app --dry-run
```

**Q. Tests කරන්නේ කොහොමද?**
`.venv/bin/python -m unittest discover -s tests -v` → **65 tests** pass වෙන්න ඕන (requests package එක ඕන).
