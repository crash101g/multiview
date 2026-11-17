# multiview

**Watch up to four live feeds in one window, with the ads stripped out.**

Web streams, IP cameras, RTSP feeds and HLS links all play side by side in a single clean grid. One feed has the sound at a time, and a press of a key switches it. The ad blocking uses the same filter lists as uBlock Origin, run on the same engine Brave uses.

One Python file. No Electron, no Docker, nothing to configure before you press play.

![multiview showing four live feeds in a 2×2 grid](docs/screenshots/hero-grid.png)

---

## Why multiview?

Following several streams at once usually means four browser tabs, four sets of autoplaying ads, pop-unders opening behind your back, and hunting for whichever tab is making noise. multiview puts all of them in one window and makes it easy to manage.

- **🖥️ 2–4 feeds, one window.** Two feeds sit side by side and three or four fill a 2×2 grid. Fullscreen any single feed with one key and press it again to go back to the grid.
- **🔊 One feed has the sound.** Press `1`–`4` to choose which feed you hear; the rest stay muted. `M` mutes everything.
- **🛡️ Real ad blocking, not a hosts file.** Built on Brave's adblock-rust engine, with the uBlock Origin lists (filters, badware, privacy, quick-fixes, unbreak), EasyList, EasyPrivacy and Peter Lowe's list. It blocks ad and tracker requests in every frame and hides the empty ad boxes they leave behind.
- **🚫 No pop-ups, pop-unders or hijacked redirects.** New-window ads are dropped, `window.open()` is stubbed so ad scripts give up quietly, and an ad can't redirect a feed to some other site.
- **📼 Plays anything.** Web pages and embed players open in a built-in Chromium view. IP cameras (`rtsp://`, `rtsps://`) play through mpv and reconnect by themselves. Other direct streams (`.m3u8`, `.ts`, `.mp4` and more) play through VLC. You can mix both kinds in the same grid.
- **📋 Paste an `<iframe>` and go.** Hand it the embed code straight off a page and multiview pulls out the link itself.
- **🪶 Tiny and readable.** One file of plain Python and Qt that you can read in one sitting.

## Ads in, ads out

The same page, the same window. On the left multiview runs with `--no-adblock`; on the right it runs with its defaults.

![Before and after: the same stream page with ad blocking off and on](docs/screenshots/adblock-before-after.png)

The banners, sidebars and the fake "update your player" box are removed by the stock uBlock Origin and EasyList rules. The ad-network scripts behind them are blocked before they load, and the window title keeps a running count.

## Two up

![Two feeds side by side](docs/screenshots/side-by-side.png)

> The screenshots are real captures of multiview playing sample pages made for this README. The ads are fakes, built to show what the blocker does.

---

## Install

**Ubuntu / Pop!_OS / Debian**

```bash
sudo apt install python3-pyqt6 python3-pyqt6.qtwebengine bubblewrap
pip install --user --break-system-packages adblock      # Brave's engine (recommended)
sudo apt install mpv                                     # only for rtsp/rtsps cameras
# recommended: cameras through libmpv, so the sandbox can run without X11 (see Sandbox)
sudo apt install libmpv2 && pip install --user --break-system-packages python-mpv
sudo apt install vlc python3-vlc                         # only for m3u8/ts/etc. feeds

git clone https://github.com/crash101g/multiview.git
cd multiview
chmod +x multiview.py
```

To give multiview its own name and icon in the taskbar and app launcher, install the desktop entry (run this from the `multiview` folder):

```bash
sed "s|@DIR@|$PWD|g" multiview.desktop > ~/.local/share/applications/multiview.desktop
# optional: a second entry that runs without the sandbox, as a fallback
sed "s|@DIR@|$PWD|g" multiview-non-sandboxed.desktop > ~/.local/share/applications/multiview-non-sandboxed.desktop
```

Started from the launcher, multiview plays the feeds listed under `[feeds]` in `multiview.ini`. If you move the folder, run the command again.

**macOS** (with [Homebrew](https://brew.sh))

```bash
brew install python
brew install mpv                                         # only for rtsp/rtsps cameras (provides libmpv)
brew install --cask vlc                                  # only for m3u8/ts/etc. feeds

git clone https://github.com/crash101g/multiview.git
cd multiview
python3 -m venv .venv
source .venv/bin/activate
pip install PyQt6 PyQt6-WebEngine adblock python-vlc python-mpv
chmod +x multiview.py multiview-sandbox.sh
```

Run `source .venv/bin/activate` in each new terminal before starting multiview. python-vlc finds VLC in `/Applications/VLC.app`. Use `Ctrl`+`Cmd`+`F` for fullscreen, because macOS keeps `F11` for Show Desktop.

On macOS, cameras play through libmpv *inside* multiview (a separate mpv process can't draw into another app's window there), with the same settings and reconnect rules as on Linux. If libmpv isn't found, point python-mpv at Homebrew's copy: `export DYLD_FALLBACK_LIBRARY_PATH=/opt/homebrew/lib`.

**macOS hasn't been tested yet.** Things to check on a first run:
- **Codecs:** the pip `PyQt6-WebEngine` build usually leaves out H.264/AAC, so web players that use them may stay blank. Cameras (mpv) and VLC feeds aren't affected.
- **Widevine:** multiview looks for the copy inside Chrome/Edge/Brave in `/Applications` and in `~/Library/Application Support`. Many DRM services also check the browser itself, so protected streams may still refuse to play.

**Windows:** `pip install PyQt6 PyQt6-WebEngine adblock python-vlc` (plus VLC itself for direct streams). This should work but hasn't been tested.

Linux is the only platform multiview has been tested on so far.

## Sandbox (on by default)

multiview restarts itself inside an OS sandbox every time it starts (via `multiview-sandbox.sh`). The feeds play exactly the same; the sandbox only limits what the app can see. If a malicious page on an embed site ever broke out of the browser engine, it would land in a box with no access to the rest of your home folder (`~/.ssh`, browser logins, documents), no way to rewrite multiview's own files, and no access to your desktop session bus.

```bash
./multiview.py                 # sandboxed (default)
./multiview.py --no-sandbox    # fallback: run without the sandbox
```

To turn it off permanently, set `sandbox = no` under `[options]` in `multiview.ini`. If the sandbox can't start (for example bubblewrap isn't installed), multiview prints a warning and runs without it, so your feeds still come up.

The window title tells you which mode you're in: `multiview - 4 feeds` is sandboxed, `(not sandboxed)` means you turned it off, and `⚠ NOT SANDBOXED` (plus a warning popup) means the sandbox should have started but couldn't. Unsandboxed runs keep their ad-block cache separately (`~/.cache/multiview-unsandboxed`), so nothing a sandboxed run writes is ever loaded outside the sandbox.

- **Linux** uses [bubblewrap](https://github.com/containers/bubblewrap) (`sudo apt install bubblewrap`). The app sees a throw-away home folder, its own folder read-only, the ad-block list cache, and read-only copies of Widevine and pip `--user` packages. Display (X11/Wayland), audio (PipeWire/Pulse), GPU and network work as normal. Chromium's own sandbox still runs inside it, so web pages are boxed twice.
- **macOS** uses the built-in `sandbox-exec` with `multiview.sb` (blocks your home folder except the files multiview needs, and blocks AppleScript control of other apps). Apple labels `sandbox-exec` deprecated, but it is the same sandbox engine macOS and Chrome rely on. Untested so far: if web tiles stay blank inside it, Chromium's own sandbox may not start inside another one. Try `QTWEBENGINE_DISABLE_SANDBOX=1 ./multiview.py`, which keeps the outer sandbox only.
- What it can't stop: the app still needs the network, so a compromised page could still reach other devices on your LAN. Camera passwords in `multiview.ini` are inside the box, because the app needs them.

### No X11 access: cameras through libmpv

A camera tile can run a separate `mpv` that draws into the tile through X11, which means the sandbox has to let the app reach your X server. Anything that can talk to X11 can read the clipboard, see keys typed into other X11 apps, and send keystrokes to other windows. That's the biggest remaining hole in the sandbox.

So when `python-mpv` is installed, cameras play through mpv *inside* multiview instead (`camera_player = auto`, the default). On a Wayland desktop, when no feed needs VLC, multiview then:

- runs natively on Wayland, with no `DISPLAY`;
- gives the sandbox no X11 socket files;
- uses Landlock (Linux 6.12+) to block X11's *abstract* socket. bwrap can't hide that socket while the network is shared, and many X servers accept it without a cookie.

The terminal then says `multiview: no X11 access (cameras through libmpv, Wayland only)`. This applies to web-only sessions too.

- Without `python-mpv` installed, cameras use the separate `mpv` and X11 stays available, as before.
- `camera_player = mpv` (or `--mpv-process` for one run) chooses the old way on purpose; `camera_player = libmpv` insists on libmpv.
- If a VLC feed is open, X11 stays on for that run.

## Use

```bash
# two web feeds side by side
./multiview.py https://example.com/stream-a https://example.com/stream-b

# mix a camera and a web page; an <iframe> tag works as-is
./multiview.py rtsp://192.168.1.50/live '<iframe src="https://example.com/embed/1"></iframe>'

# cameras that need a login: put user:password in the URL.
# The title bar shows it as rtsps://USER:***@... so the password stays hidden.
# URL-encode special characters in the password (@ -> %40, # -> %23, : -> %3A).
# Wyze RTSP is TLS-only on port 322 (rtsps://). If you paste the rtsp://...:322 link
# the Wyze app shows, multiview switches it to rtsps:// for you.
./multiview.py 'rtsps://USER:PASS@192.168.1.50:322/stream0' 'rtsps://USER:PASS@192.168.1.51:322/stream1'

# no arguments: uses the [feeds] list in multiview.ini
./multiview.py
```

| Key | Action |
| --- | --- |
| `1`–`4` | Give that feed the audio |
| `M` | Mute / unmute everything |
| `S` | Solo the feed with the audio full-window (press again to return) |
| `R` | Reload the feed you're listening to (all feeds if none has audio) |
| `Shift+R` | Reload all feeds, a few seconds apart |
| `H` | Hide / show the title bars |
| `F11` (`Ctrl`+`Cmd`+`F` on macOS) | Fullscreen · `Esc` leaves fullscreen or solo |
| `Q` | Quit |

Each tile also has 🔊 / ⛶ / ⟳ buttons in its title bar.

## Settings

The first run creates `multiview.ini` next to the script:

```ini
[feeds]
1 = https://example.com/stream-a
2 = rtsp://192.168.1.50/live
; camera with a login - the title bar shows the password as ***
3 = rtsp://USER:PASS@192.168.1.51/live

[options]
audio = 1              ; which feed starts with the sound (0 = all muted)
block_popups = yes     ; drop pop-up / new-window ads
adblock = yes          ; uBlock Origin / EasyList filtering
lock_navigation = yes  ; stop ads redirecting a feed to another site
extra_lists =          ; more filter-list URLs, comma separated
log_level = important  ; terminal noise: all, important, fatal (or critical), none
webrtc = off           ; on = allow web feeds to open peer-to-peer connections
auto_reload = no       ; yes = reload web feeds that never start playing
```

### Terminal logs

The browser engine (Chromium) prints a lot of `ERROR` lines that are harmless: D-Bus being blocked by the sandbox, WebRTC `.local` names, STUN timeouts, data channels closing. `log_level` (or `--logs=LEVEL` for one run) controls how much of it you see. multiview's own `multiview: ...` messages always show.

| `log_level` | Shows |
| --- | --- |
| `all` | everything, including Qt's startup banner |
| `important` (default) | real errors only. Known-harmless lines and the startup banner are hidden; dropped WebRTC upload packets (`error 11`) are summed up once a minute |
| `fatal` / `critical` | only crashes (Chromium `FATAL`) |
| `none` | nothing from the browser engine |

`-v` always shows everything.

### WebRTC

WebRTC is **off by default**. Some streaming sites use it to share video between viewers peer-to-peer, which uses your upload bandwidth and can reveal your IP address to other viewers. With it off, multiview removes the WebRTC API from every page and frame and stops the engine sending UDP, so those sites fall back to normal downloads. Cameras (mpv) aren't affected.

If a web feed won't play, it may genuinely need WebRTC. Turn it back on with `webrtc = on` in `multiview.ini`, or for one run with `--webrtc`. (`--no-webrtc` forces it off for one run when the ini says `on`.)

### One feed at a time (`stagger = auto`, optional)

Many stream sites fail when several players start at the same moment, but work when they start one after another. `stagger` sets the gap between starting each web feed (default 3 seconds). With `stagger = auto`, multiview starts the next web feed as soon as the previous one is actually playing. If a feed hasn't started after `auto_reload_after` seconds (default 20), it moves on to the next one. Shift+R reloads all feeds the same way, one at a time. If you'd rather have a fixed gap, a larger number such as `stagger = 20` also works.

### Auto-reload (optional, off by default)

Some stream sites don't start every time, and the feed has to be reloaded once or twice. With `auto_reload = yes` (or `--auto-reload` for one run), multiview watches each web feed. If no video has started playing after `auto_reload_after` seconds (default 20), it reloads that feed and prints a line saying so. It also prints when each feed starts playing (`feed 2 playing (12 s after loading, ...)`) and when you reload one by hand, so the terminal shows what happened to each feed. The wait gets longer with each try (20 s, 40 s, 60 s ...), and after `auto_reload_tries` reloads (default 3) it stops and leaves the feed for you to reload with R. Pressing R yourself starts the count over. Automatic reloads take turns: only one feed (re)loads at a time, so the site is never hit by several at once.

```ini
auto_reload = yes
auto_reload_after = 20
auto_reload_tries = 3
```

Only feeds that have **never** started are touched. A feed that has played, even if it's now paused or buffering, is left alone. Videos inside embedded player frames from other sites are detected too. Cameras already reconnect on their own.

### Ad blocking details

| | With `adblock` installed | Without it |
| --- | --- | --- |
| Engine | Brave adblock-rust | built-in domain matcher |
| Network filtering | full uBO / ABP syntax: paths, `$script`, `$third-party`, `$domain=` and the rest | `\|\|domain^` rules (~94k domains) |
| Hiding ad elements | site-specific and generic `##` rules | – |
| Pop-up and redirect guard | ✅ | ✅ |

- Filter lists are cached in `~/.cache/multiview/` and refreshed every 4 days, or right away with `--update-filters`. The compiled engine is cached too, so after the first run it loads in a fraction of a second.
- **Your own rules** go in `my-filters.txt` next to the script, in standard uBO syntax:
  ```
  ||annoying-ad-host.com^
  example.com##.overlay-ad
  @@||cdn-i-actually-need.com^
  ```
- Run with `-v` to print every blocked request, which helps when writing rules.
- `--no-adblock` turns blocking off for one run.

**Known limit:** uBO's `##+js(...)` scriptlet rules (mostly used against anti-adblock walls) aren't run, because their code isn't part of Brave's engine. Network and element-hiding rules all work.

## Notes

- **Wayland (GNOME, KDE, COSMIC):** VLC can only draw into an X11 window, so when any feed uses VLC, multiview runs through XWayland automatically. With only web feeds it runs natively.
- Web views share one private, in-memory profile. Nothing is saved to disk between runs.
- multiview is a viewer. It doesn't download, record or re-share anything. Only watch streams you have the right to watch.

## License

[GPL-3.0](LICENSE) © crash101g

This is a personal project, shared as-is.
