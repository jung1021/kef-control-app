# Microsoft Store listing – KEF Control

Copy-paste text for Partner Center (https://partner.microsoft.com/dashboard → Apps and games → New product → **MSIX or PWA app**).

## Before you start
- **App name to reserve:** pick a name that doesn't look official. Store policy doesn't allow names that suggest you are KEF. Good options:
  - **Controller for KEF Speakers**
  - **Remote for KEF Speakers**
  - **Speaker Control for KEF**

  The app itself can keep "KEF Control" as its window title.
- After reserving the name, open **Product management → Product identity** and copy these three values to build the package:
  - `Package/Identity/Name` → `IDENTITY_NAME`
  - `Package/Identity/Publisher` → `PUBLISHER`
  - `Package/Properties/PublisherDisplayName` → `PUBLISHER_DISPLAY_NAME`

  Then build with [`../msix/build_msix.sh`](../msix/build_msix.sh), or send the values to whoever builds it.

## Properties
- **Category:** Music (subcategory: none), or Utilities & tools
- **Privacy policy URL:** https://jung1021.github.io/kef-control-app/privacy.html
- **Website:** https://jung1021.github.io/kef-control-app/
- **Support contact:** https://github.com/jung1021/kef-control-app/issues
- **System requirements:** Windows 10 version 1809 or later, x64; a KEF W2 wireless speaker on the same network.
- **Product declarations:** no in-app purchases, no ads; "This app has been tested to meet accessibility guidelines": leave unchecked.

## Age rating questionnaire
No user-generated content, no communication between users, no location sharing, no purchases → rated **3+ / Everyone**.

## Store listing (English)

**Product name:** Controller for KEF Speakers

**Short description** (shown in search, ≤ 100 characters):
> Control KEF LSX II, LSX II LT and LS50 Wireless II speakers from your PC – volume, inputs, EQ and more.

**Description:**
> Control your KEF wireless speakers from your Windows PC – no phone needed.
>
> KEF doesn't offer the KEF Connect app for Windows. This free, open-source app gives you the controls you use every day on your PC: volume, input switching and all of the speaker's sound settings, right from the Windows tray.
>
> WORKS WITH
> KEF speakers on the W2 platform: LSX II, LSX II LT, LS50 Wireless II, LS60 Wireless, XIO and LS LUXE. (The first-generation LSX and LS50 Wireless aren't supported.)
>
> FEATURES
> • Volume, mute and power – slider, mouse wheel or arrow keys
> • Switch inputs: USB, Optical, TV, Bluetooth, Wi-Fi
> • All sound settings: desk mode, wall mode, treble trim, bass extension, balance, phase correction and subwoofer settings
> • Sound profiles – save "Music", "Movies" or "Late night" and switch in one click
> • Sync with your PC – speakers turn on when the PC starts or wakes and go to standby when it sleeps or shuts down
> • Now playing – track, artist, album art and play/pause/skip when streaming
> • Multiple speakers – switch between pairs in different rooms
> • Lives in the system tray, uses almost no resources, light and dark themes
> • No account, no ads, no tracking
>
> REQUIREMENTS
> Your speakers need to be connected to your home Wi-Fi (set up once with KEF Connect on a phone). Audio can still go over USB – settings are changed over the network.
>
> This is an unofficial app and is not affiliated with or endorsed by KEF. KEF and LSX are trademarks of KEF / GP Acoustics.

**What's new in this version:**
> Now playing with playback controls, multiple speakers, light theme, and many small improvements.

**Product features** (one per line, up to 20):
- Control volume, mute and power from your PC
- Switch inputs: USB, Optical, TV, Bluetooth, Wi-Fi
- Desk mode, wall mode, treble, bass extension, balance
- Save and switch sound profiles
- Turn speakers on and off with your PC
- Now playing with play/pause/skip
- Multiple speakers
- System tray icon with quick controls
- Light and dark theme
- No account, ads or tracking

**Search terms** (up to 7): `KEF`, `KEF Connect`, `LSX II`, `LS50 Wireless II`, `speaker control`, `KEF remote`, `LSX II LT`

**Screenshots:** upload `docs/screenshots/home.png`, `sound.png`, `settings.png`, `home-light.png`. They're 920×1640, which the Store accepts for desktop. Wider shots look better, so you can also add `docs/screenshots/overview.png`.

**Store logos:** use `packaging/msix/Assets/Square310x310Logo.png` (or a 300×300 export) for the box art.

## Notes for certification (paste into "Notes for certification")
> This app controls KEF wireless speakers over the local network. Without a KEF W2 speaker on the network, the app shows a "Connect to your speakers" screen, which is the expected behaviour. The app starts a small HTTP server bound to 127.0.0.1 only, and shows its UI in a Microsoft Edge app window. It uses the runFullTrust capability because it's a desktop (Win32) app with a system-tray icon and listens for Windows power events to turn the speakers on and off with the PC.
