# Getting KEF Control found – launch checklist

## 1. One-time GitHub setup (5 minutes)
- [ ] **Turn on the website:** repo **Settings → Pages → Build and deployment → Source: Deploy from a branch → Branch: `main` / folder `/docs` → Save**. After a minute it's live at https://jung1021.github.io/kef-control-app/
- [ ] **About box** (⚙️ next to "About" on the repo page):
  - Description: `Free Windows app to control KEF LSX II, LSX II LT & LS50 Wireless II speakers – a KEF Connect alternative for PC`
  - Website: `https://jung1021.github.io/kef-control-app/`
  - Topics: `kef`, `kef-connect`, `lsx-ii`, `lsx-ii-lt`, `ls50-wireless-ii`, `windows`, `tray-app`, `speaker-control`, `python`
- [ ] **Social preview:** Settings → General → Social preview → upload `docs/social-preview.png`. This is the image people see when the link is shared.
- [ ] **Release v1.3.1** with `KEFControl-Setup-1.3.1.exe` attached. Paste the notes from `CHANGELOG.md`.

## 2. Google (10 minutes, then wait)
- [ ] Go to https://search.google.com/search-console → **Add property → URL prefix** → `https://jung1021.github.io/kef-control-app/`
- [ ] Choose **HTML tag** verification and copy the `<meta name="google-site-verification" ...>` tag. Paste it into `docs/index.html` where it says "Google Search Console", commit, then click **Verify**. Or ask Claude to add it.
- [ ] **Sitemaps** → submit `sitemap.xml`.
- [ ] **URL inspection** → enter the site URL → **Request indexing**.
- [ ] Optional: do the same in Bing Webmaster Tools (it can import from Google). Bing also powers DuckDuckGo and Copilot answers.

Google usually indexes a new site in a few days. Ranking for "KEF Connect for Windows" comes from links, which is what steps 3–4 are for.

## 3. Directories and package managers
- [ ] **winget:** see `packaging/winget/README.md`.
- [ ] **Microsoft Store:** see `packaging/store/LISTING.md`. Free for individuals, and no SmartScreen warning.
- [ ] **AlternativeTo:** https://alternativeto.net/software/kef-connect/ → "Suggest alternative" → add KEF Control (Windows, free, open source). Paste the short description from the Store listing.
- [ ] **Home Assistant / Roon forum threads** where people ask for PC control: reply with a short, helpful note and the link (drafts below).

## 4. Post drafts
Post as yourself, be upfront that it's your project, and answer questions. Communities respond well to that.

### Reddit: r/KEF, r/audiophile (check each sub's self-promotion rules first)
**Title:** I made a free Windows app to control KEF LSX II / LSX II LT / LS50W II from your PC (tray icon, profiles, power sync)

> I use an LSX II LT as PC speakers, and reaching for my phone to change settings in KEF Connect got old, so I made a desktop app.
>
> **KEF Control for Windows** (free, open source):
> - Volume, inputs and all the sound settings (desk/wall mode, treble, bass extension, balance, sub)
> - Sound profiles you can switch from the tray
> - Speakers turn on when the PC wakes and go to standby when it sleeps (it won't cut off Bluetooth from your phone)
> - Now playing with play/pause/skip, and multiple speakers
> - Tray icon, ~40 MB RAM, no account
>
> Speakers need to be on Wi-Fi (USB is audio-only on these). Works with the W2 models: LSX II, LSX II LT, LS50 Wireless II, LS60, XIO.
>
> Site: https://jung1021.github.io/kef-control-app/ · Code: https://github.com/jung1021/kef-control-app
>
> It's not affiliated with KEF. I'd love to hear if it works on your model and firmware, and what you'd want added.

### Audio Science Review / Head-Fi / AVS Forum (KEF LSX II threads)
> For anyone using LSX II / LSX II LT / LS50W II as desktop speakers: I've released a free Windows app that does the PC-relevant parts of KEF Connect (volume, inputs, desk/wall mode, treble, bass extension, profiles) from the system tray. It can also turn the speakers on and off with the PC. Open source, no account: https://jung1021.github.io/kef-control-app/. Feedback welcome, especially from LS60/XIO owners.

### Hacker News: Show HN
**Title:** Show HN: KEF Control – Windows tray app for KEF wireless speakers

> KEF's W2 speakers (LSX II, LS50 Wireless II, LS60) expose a local HTTP API that their phone app uses, but there's no Windows client, which is awkward for people who use them as desk speakers. This is a small Python app (pykefcontrol + a local web UI in an Edge app window) that lives in the tray. It mirrors the speaker's DSP settings, adds saved profiles, and listens for Windows power/session events to turn the speakers on and off with the PC. The installer is built entirely on Linux (embeddable Python + a tiny MinGW launcher + NSIS). Code: https://github.com/jung1021/kef-control-app

## 5. Keep it alive
- Answer issues quickly and thank people who report models or firmware that work.
- Ship small releases with a changelog. Active repos rank better on GitHub and Google.
- Add a "Works with" table to the README as people report models and firmware.
