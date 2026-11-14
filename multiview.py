#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-only
# multiview - Copyright (C) 2026 crash101g  (https://github.com/crash101g/multiview)
"""
multiview.py - watch 2-4 feeds side by side in one window, with ad blocking.

Each feed can be either:
  * a web page / embed player  (https://...  or a pasted <iframe src="..."> tag)
      -> shown in a built-in web view (Qt WebEngine)
  * a direct media stream      (rtsp://, udp://, .m3u8, .ts, .mp4, .mkv ...)
      -> played with VLC (python-vlc), same idea as tablo-vlc.py

Ad blocking (web feeds):
  * Brave's ad-block engine (adblock-rust, via the "adblock" Python package)
    loaded with the uBlock Origin filter lists + EasyList + EasyPrivacy +
    Peter Lowe's list. Blocks ad/tracker requests in every frame, and hides
    leftover ad boxes with the lists' cosmetic (element-hiding) rules.
  * Without the "adblock" package it falls back to a built-in blocker that
    only blocks by domain, using the same lists' ||domain^ rules.
  * Pop-up / new-window ads are dropped, window.open() is stubbed out, and
    redirects of a feed to some other site are blocked.
  * Your own rules: my-filters.txt next to this script (uBO/ABP syntax).
  * Lists are cached in ~/.cache/multiview and refreshed every 4 days.

Usage:
  ./multiview.py URL1 URL2 [URL3 [URL4]]
  ./multiview.py                      # uses the [feeds] list in multiview.ini
  ./multiview.py --update-filters ... # force a fresh download of the lists
  ./multiview.py --no-adblock ...     # turn blocking off for this run
  ./multiview.py -v ...               # print every blocked request (handy for my-filters.txt)

Keys:
  click    click a feed to hear it (others are muted; all start muted)
  1-4      give audio to that feed
  A        audio from all feeds at once
  M        mute / unmute everything
  S        solo the audio feed full-window (press again to go back to grid)
  R        reload the feed you're listening to (all feeds if none has audio)
  Shift+R  reload all feeds
  H        hide / show the little title bars
  F, F11   fullscreen (Ctrl+Cmd+F on macOS)   Esc  back to the normal window (leaves fullscreen and solo)
  Q, Ctrl+C, Ctrl+X   quit (Ctrl+C in the terminal works too; press it twice to force-kill)

Install (Ubuntu / Pop!_OS):
  sudo apt install python3-pyqt6 python3-pyqt6.qtwebengine
  pip install --user --break-system-packages adblock    # Brave's engine (recommended)
  sudo apt install vlc python3-vlc                       # only needed for direct streams
"""

import configparser
import json
import os
import re
import signal
import sys
import threading
import time
import urllib.request
from pathlib import Path
from urllib.parse import urlsplit

HERE = Path(__file__).resolve().parent
INI = HERE / "multiview.ini"
MY_FILTERS = HERE / "my-filters.txt"
CACHE = Path(os.environ.get("XDG_CACHE_HOME", Path.home() / ".cache")) / "multiview"
UPDATE_DAYS = 4

MEDIA_SCHEMES = ("rtsp://", "rtsps://", "rtmp://", "udp://", "rtp://", "mms://", "file://")
MEDIA_EXTS = (".m3u8", ".m3u", ".ts", ".mp4", ".mkv", ".webm", ".mov", ".flv", ".mpd", ".mp3", ".aac")

# The same default lists uBlock Origin ships with (GitHub mirrors are used
# first because they are fast and rarely rate-limited).
FILTER_LISTS = {
    "ubo-filters":     ["https://raw.githubusercontent.com/uBlockOrigin/uAssets/master/filters/filters.txt",
                        "https://ublockorigin.github.io/uAssets/filters/filters.txt"],
    "ubo-badware":     ["https://raw.githubusercontent.com/uBlockOrigin/uAssets/master/filters/badware.txt",
                        "https://ublockorigin.github.io/uAssets/filters/badware.txt"],
    "ubo-privacy":     ["https://raw.githubusercontent.com/uBlockOrigin/uAssets/master/filters/privacy.txt",
                        "https://ublockorigin.github.io/uAssets/filters/privacy.txt"],
    "ubo-quick-fixes": ["https://raw.githubusercontent.com/uBlockOrigin/uAssets/master/filters/quick-fixes.txt",
                        "https://ublockorigin.github.io/uAssets/filters/quick-fixes.txt"],
    "ubo-unbreak":     ["https://raw.githubusercontent.com/uBlockOrigin/uAssets/master/filters/unbreak.txt",
                        "https://ublockorigin.github.io/uAssets/filters/unbreak.txt"],
    "easylist":        ["https://raw.githubusercontent.com/easylist/easylist/gh-pages/easylist.txt",
                        "https://easylist.to/easylist/easylist.txt"],
    "easyprivacy":     ["https://raw.githubusercontent.com/easylist/easylist/gh-pages/easyprivacy.txt",
                        "https://easylist.to/easylist/easyprivacy.txt"],
    "peter-lowe":      ["https://pgl.yoyo.org/adservers/serverlist.php?hostformat=adblockplus"
                        "&showintro=0&mimetype=plaintext"],
}

DEFAULT_INI = """\
; multiview.ini - one feed per line under [feeds] (2 to 4 of them).
; Web pages, pasted <iframe ...> tags, or direct stream URLs all work.
[feeds]
1 =
2 =
3 =
4 =

[options]
; which feed gets audio at start (0 = all muted, 1-4, or all).
; Click a feed to give it the audio.
audio = 0
; block pop-up / new-window ads from embed pages
block_popups = yes
; ad blocking with uBlock Origin / EasyList filter lists
adblock = yes
; stop a feed from being redirected to a different site (ad hijacks)
lock_navigation = yes
; extra filter-list URLs, comma separated (optional)
extra_lists =
; strict page: the outer feed page may only load third-party scripts from
; well-known CDNs (stops rotating-domain ad networks). The player frame inside
; the page is not affected.
strict_page = yes
; extra domains the outer page may load scripts from, comma separated
allow_scripts =
; DRM (Widevine) for "protected content" players: auto = find one installed by
; Chrome/Edge/Vivaldi/Chromium etc., no = off, or a path to libwidevinecdm.so
widevine = auto
; seconds between starting each web feed (and between reloads with Shift+R),
; so the site isn't hit with every stream/license request at once. 0 = all at once
stagger = 3
"""

DEFAULT_MY_FILTERS = """\
! my-filters.txt - your own ad-block rules (uBlock Origin / AdBlock Plus syntax).
! Reload multiview after editing. Examples:
!   ||annoying-ad-host.com^          block a domain everywhere
!   example.com##.overlay-ad         hide an element on one site
!   @@||cdn-i-need.com^              never block this domain
"""


# --------------------------------------------------------------------------- input helpers
def clean_source(text):
    """Accept a bare URL or a pasted <iframe src="..."> tag; return the URL."""
    text = (text or "").strip()
    if not text:
        return ""
    m = re.search(r"""src\s*=\s*["']([^"']+)["']""", text, re.I)
    if m:
        text = m.group(1)
    if text.startswith("//"):
        text = "https:" + text
    if os.path.exists(text):
        text = Path(text).resolve().as_uri()
    return text


def is_media(url):
    low = url.lower().split("?", 1)[0]
    return low.startswith(MEDIA_SCHEMES) or low.endswith(MEDIA_EXTS)


def host_of(url):
    try:
        return (urlsplit(url).hostname or "").lower()
    except ValueError:
        return ""


def site_of(host):
    """Rough registrable domain: last two labels (three for co.uk-style)."""
    parts = host.split(".")
    if len(parts) >= 3 and len(parts[-2]) <= 3 and len(parts[-1]) == 2:
        return ".".join(parts[-3:])
    return ".".join(parts[-2:])


def load_config():
    cfg = configparser.ConfigParser()
    if not INI.exists():
        INI.write_text(DEFAULT_INI)
    cfg.read(INI)
    feeds = [clean_source(v) for _, v in cfg.items("feeds")] if cfg.has_section("feeds") else []
    opts = {
        "audio": cfg.get("options", "audio", fallback="0").strip().lower(),
        "block_popups": cfg.getboolean("options", "block_popups", fallback=True),
        "adblock": cfg.getboolean("options", "adblock", fallback=True),
        "lock_navigation": cfg.getboolean("options", "lock_navigation", fallback=True),
        "extra_lists": [u.strip() for u in cfg.get("options", "extra_lists", fallback="").split(",")
                        if u.strip()],
        "strict_page": cfg.getboolean("options", "strict_page", fallback=True),
        "allow_scripts": {d.strip().lower() for d in
                          cfg.get("options", "allow_scripts", fallback="").split(",") if d.strip()},
        "widevine": cfg.get("options", "widevine", fallback="auto").strip(),
        "stagger": max(0.0, cfg.getfloat("options", "stagger", fallback=3.0)),
    }
    return [f for f in feeds if f], opts


# Pick sources before importing Qt: VLC can only embed into an X11 window, so on
# Wayland (Pop!_OS COSMIC) we ask Qt to run through XWayland when VLC is needed.
_cli = [clean_source(a) for a in sys.argv[1:] if not a.startswith("-")]
_ini_feeds, OPTS = load_config()
VERBOSE = "--verbose" in sys.argv or "-v" in sys.argv
if "--no-adblock" in sys.argv:
    OPTS["adblock"] = False
SOURCES = (_cli or _ini_feeds)[:4]

if any(is_media(s) for s in SOURCES) and sys.platform.startswith("linux"):
    os.environ.setdefault("QT_QPA_PLATFORM", "xcb")


# --------------------------------------------------------------------------- ad blocking
class SimpleEngine:
    """Fallback when the 'adblock' package is missing: domain rules only."""

    RULE = re.compile(r"^(@@)?\|\|([a-z0-9.-]+)\^(?:\$(.*))?$")

    def __init__(self, texts):
        self.block, self.allow = set(), set()
        for text in texts:
            for line in text.splitlines():
                m = self.RULE.match(line.strip())
                if not m:
                    continue
                opts = m.group(3) or ""
                # skip rules restricted to particular sites / types: we can't honour them
                if "domain=" in opts or "~third-party" in opts or (opts and opts not in
                                                                    ("third-party", "3p", "all", "important")):
                    continue
                (self.allow if m.group(1) else self.block).add(m.group(2))

    def _hit(self, host, table):
        parts = host.split(".")
        return any(".".join(parts[i:]) in table for i in range(len(parts) - 1))

    def should_block(self, url, source, rtype):
        h = host_of(url)
        return bool(h) and self._hit(h, self.block) and not self._hit(h, self.allow)

    def cosmetic(self, url):
        return [], set(), True

    def generic(self, classes, ids, exceptions):
        return []


class BraveEngine:
    """Brave's adblock-rust engine: full network + cosmetic filtering."""

    def __init__(self, texts, cache_file, stamp):
        import adblock
        self.engine = None
        if cache_file.exists() and cache_file.stat().st_mtime >= stamp:
            try:
                eng = adblock.Engine(adblock.FilterSet())
                eng.deserialize_from_file(str(cache_file))
                self.engine = eng
            except Exception:
                self.engine = None
        if self.engine is None:
            fs = adblock.FilterSet()
            for text in texts:
                fs.add_filter_list(text)
            self.engine = adblock.Engine(fs)
            try:
                self.engine.serialize_to_file(str(cache_file))
            except Exception:
                pass

    def should_block(self, url, source, rtype):
        try:
            r = self.engine.check_network_urls(url, source or url, rtype)
            return r.matched and not r.exception
        except Exception:
            return False

    def cosmetic(self, url):
        try:
            c = self.engine.url_cosmetic_resources(url)
            return list(c.hide_selectors), set(c.exceptions), c.generichide
        except Exception:
            return [], set(), True

    def generic(self, classes, ids, exceptions):
        try:
            return list(self.engine.hidden_class_id_selectors(classes, ids, exceptions))
        except Exception:
            return []


def fetch_lists(extra, force):
    """Download (or reuse cached) filter lists. Returns (texts, newest_mtime)."""
    CACHE.mkdir(parents=True, exist_ok=True)
    lists = dict(FILTER_LISTS)
    for i, u in enumerate(extra):
        lists[f"extra-{i}"] = [u]
    texts, newest = [], 0.0
    for name, urls in lists.items():
        path = CACHE / f"{name}.txt"
        stale = force or not path.exists() or time.time() - path.stat().st_mtime > UPDATE_DAYS * 86400
        if stale:
            for u in urls:
                try:
                    req = urllib.request.Request(u, headers={"User-Agent": "multiview"})
                    with urllib.request.urlopen(req, timeout=20) as resp:
                        data = resp.read().decode("utf-8", "replace")
                    if len(data) > 200:
                        path.write_text(data)
                        print(f"  updated {name}")
                        break
                except Exception:
                    continue
            else:
                if not path.exists():
                    print(f"  could not download {name} (skipped)")
        if path.exists():
            texts.append(path.read_text(errors="replace"))
            newest = max(newest, path.stat().st_mtime)
    if not MY_FILTERS.exists():
        MY_FILTERS.write_text(DEFAULT_MY_FILTERS)
    texts.append(MY_FILTERS.read_text(errors="replace"))
    newest = max(newest, MY_FILTERS.stat().st_mtime)
    return texts, newest


def build_blocker():
    if not OPTS["adblock"] or not any(not is_media(s) for s in SOURCES):
        return None
    print("multiview: loading ad-block filter lists ...")
    texts, newest = fetch_lists(OPTS["extra_lists"], "--update-filters" in sys.argv)
    if len(texts) <= 1:
        print("multiview: no filter lists available - ad blocking is off")
        return None
    try:
        eng = BraveEngine(texts, CACHE / "engine.dat", newest)
        print("multiview: ad blocking on (Brave adblock-rust engine)")
    except ImportError:
        eng = SimpleEngine(texts)
        print(f"multiview: ad blocking on (basic domain blocker, {len(eng.block):,} domains)\n"
              "           for full uBlock-style blocking: "
              "pip install --user --break-system-packages adblock")
    eng.count = 0
    return eng


BLOCKER = build_blocker()


from PyQt6.QtCore import QEvent, QMetaObject, Qt, QTimer, QUrl                             # noqa: E402
from PyQt6.QtGui import QColor, QKeySequence, QPalette, QShortcut                       # noqa: E402
from PyQt6.QtWidgets import (QApplication, QFrame, QGridLayout,      # noqa: E402
                             QHBoxLayout, QLabel, QMainWindow,
                             QPushButton, QVBoxLayout, QWidget, QMessageBox)

try:
    from PyQt6.QtWebEngineCore import (QWebEnginePage, QWebEngineProfile, QWebEngineScript,
                                       QWebEngineSettings, QWebEngineUrlRequestInfo,
                                       QWebEngineUrlRequestInterceptor)
    from PyQt6.QtWebEngineWidgets import QWebEngineView
    HAVE_WEB = True
except ImportError:
    HAVE_WEB = False

try:
    import vlc
    HAVE_VLC = True
except Exception:
    HAVE_VLC = False


# --------------------------------------------------------------------------- web plumbing
# Runs in every frame before the page's own scripts: neuters window.open()
# pop-unders while handing back a fake window so ad scripts don't retry.
POPUP_STUB_JS = r"""
(() => {
  try {
    const fake = { closed: false, focus(){}, blur(){}, close(){ this.closed = true; },
                   postMessage(){}, document: { write(){}, close(){} },
                   location: { href: '', replace(){}, assign(){} } };
    Object.defineProperty(window, 'open', { value: () => fake, writable: false });
  } catch (e) {}
})();
"""

# Adds/updates a <style> block and returns the page's class and id names
# so generic cosmetic rules can be matched against them.
COSMETIC_JS = r"""
(css => {
  let s = document.getElementById('__mv_adblock');
  if (!s) { s = document.createElement('style'); s.id = '__mv_adblock';
            (document.head || document.documentElement).appendChild(s); }
  if (css) s.textContent += css;
  const cls = new Set(), ids = new Set();
  for (const el of document.querySelectorAll('[class],[id]')) {
    if (el.id) ids.add(el.id);
    for (const c of el.classList) cls.add(c);
    if (cls.size + ids.size > 5000) break;
  }
  return [Array.from(cls), Array.from(ids)];
})
"""

# Stream players start muted (autoplay rules) and show an "UNMUTE" button.
# multiview decides what you hear with per-feed muting, so keep the players
# themselves unmuted.
UNMUTE_JS = r"""
(() => {
  if (window.__mvUnmute) return;
  window.__mvUnmute = true;
  const clicked = new WeakSet();
  const fix = () => {
    try {
      for (const v of document.querySelectorAll('video, audio')) {
        if (v.muted) v.muted = false;
        if (v.volume === 0) v.volume = 1;
      }
      if (typeof window.jwplayer === 'function') {
        const p = window.jwplayer();
        if (p && p.getMute && p.getMute()) p.setMute(false);
      }
      for (const b of document.querySelectorAll('button, div, span, a')) {
        if (clicked.has(b) || b.children.length > 2) continue;
        if ((b.textContent || '').trim().toUpperCase() === 'UNMUTE' && b.offsetParent) {
          clicked.add(b); b.click();
        }
      }
    } catch (e) {}
  };
  document.addEventListener('playing', fix, true);
  document.addEventListener('loadedmetadata', fix, true);
  let n = 0;
  const t = setInterval(() => { fix(); if (++n >= 30) clearInterval(t); }, 1000);
})();
"""

if HAVE_WEB:
    RT = QWebEngineUrlRequestInfo.ResourceType
    RTYPES = {
        RT.ResourceTypeMainFrame: "main_frame", RT.ResourceTypeSubFrame: "sub_frame",
        RT.ResourceTypeStylesheet: "stylesheet", RT.ResourceTypeScript: "script",
        RT.ResourceTypeImage: "image", RT.ResourceTypeFontResource: "font",
        RT.ResourceTypeObject: "object", RT.ResourceTypeMedia: "media",
        RT.ResourceTypeXhr: "xmlhttprequest", RT.ResourceTypePing: "ping",
        RT.ResourceTypeFavicon: "image", RT.ResourceTypeWorker: "script",
        RT.ResourceTypeSharedWorker: "script", RT.ResourceTypeServiceWorker: "script",
        RT.ResourceTypePrefetch: "other", RT.ResourceTypeSubResource: "other",
    }

    class AdInterceptor(QWebEngineUrlRequestInterceptor):
        """Checks every request from every frame against the filter lists."""

        def interceptRequest(self, info):
            rtype = RTYPES.get(info.resourceType(), "other")
            if rtype == "main_frame":
                return                      # never block the feed page itself
            url = info.requestUrl().toString()
            if not url.startswith(("http://", "https://", "ws://", "wss://")):
                return
            source = info.firstPartyUrl().toString()
            if BLOCKER.should_block(url, source, rtype) or self.strict_block(info, url, source, rtype):
                info.block(True)
                BLOCKER.count += 1
                if VERBOSE:
                    print(f"  blocked {rtype:<14} {url[:110]}")

        @staticmethod
        def strict_block(info, url, source, rtype):
            """Outer feed page may only pull third-party scripts from trusted CDNs."""
            if not OPTS["strict_page"] or rtype != "script":
                return False
            top = site_of(host_of(source))
            if site_of(host_of(info.initiator().toString())) != top:
                return False                # request comes from the embedded player frame
            target = site_of(host_of(url))
            return bool(target) and target != top and target not in TRUSTED_SCRIPT_SITES

    class QuietPage(QWebEnginePage):
        """Swallows pop-ups, blocks off-site redirects, allows in-page fullscreen."""

        def __init__(self, profile, parent):
            super().__init__(profile, parent)
            self.home_site = None
            self.on_fullscreen = None        # set by the Cell: called with True/False
            self.in_fullscreen = False
            self.fullScreenRequested.connect(self._fullscreen)

        def _fullscreen(self, req):
            req.accept()
            self.in_fullscreen = req.toggleOn()
            if self.on_fullscreen:
                self.on_fullscreen(self.in_fullscreen)

        def createWindow(self, _type):
            if OPTS["block_popups"]:
                return None                 # pop-up ad -> dropped
            return super().createWindow(_type)

        def acceptNavigationRequest(self, url, nav_type, is_main_frame):
            target = url.toString()
            NT = QWebEnginePage.NavigationType
            if is_main_frame:
                site = site_of(host_of(target))
                if self.home_site is None or nav_type in (NT.NavigationTypeTyped,):
                    self.home_site = site
                elif (OPTS["lock_navigation"] and site and site != self.home_site
                      and nav_type not in (NT.NavigationTypeReload, NT.NavigationTypeBackForward,
                                           NT.NavigationTypeRedirect)):
                    print(f"multiview: blocked redirect to {target[:100]}")
                    return False
            elif BLOCKER and BLOCKER.should_block(target, self.url().toString(), "sub_frame"):
                BLOCKER.count += 1
                return False
            return super().acceptNavigationRequest(url, nav_type, is_main_frame)

        def javaScriptConsoleMessage(self, *args):
            pass                            # keep the terminal quiet

    # Script hosts the outer page may still use in strict_page mode.
    TRUSTED_SCRIPT_SITES = {
        "cloudflare.com", "jsdelivr.net", "jquery.com", "googleapis.com", "gstatic.com",
        "unpkg.com", "bootstrapcdn.com", "jwpcdn.com", "jwplayer.com", "jwplatform.com",
        "recaptcha.net", "google.com", "hcaptcha.com", "videojs.com", "cloudfront.net",
        "fontawesome.com", "clappr.io",
    } | OPTS["allow_scripts"]

    _PROFILE = None
    _INTERCEPTOR = None

    def web_profile():
        """One shared profile with the ad blocker and pop-up stub installed."""
        global _PROFILE, _INTERCEPTOR
        if _PROFILE is None:
            _PROFILE = QWebEngineProfile.defaultProfile()
            if BLOCKER:
                _INTERCEPTOR = AdInterceptor()
                _PROFILE.setUrlRequestInterceptor(_INTERCEPTOR)
            u = QWebEngineScript()
            u.setName("mv-unmute")
            u.setSourceCode(UNMUTE_JS)
            u.setInjectionPoint(QWebEngineScript.InjectionPoint.DocumentReady)
            u.setWorldId(QWebEngineScript.ScriptWorldId.MainWorld)
            u.setRunsOnSubFrames(True)
            _PROFILE.scripts().insert(u)
            if OPTS["block_popups"]:
                s = QWebEngineScript()
                s.setName("mv-popup-stub")
                s.setSourceCode(POPUP_STUB_JS)
                s.setInjectionPoint(QWebEngineScript.InjectionPoint.DocumentCreation)
                s.setWorldId(QWebEngineScript.ScriptWorldId.MainWorld)
                s.setRunsOnSubFrames(True)
                _PROFILE.scripts().insert(s)
        return _PROFILE


# --------------------------------------------------------------------------- players
class Player:
    """Common interface over a web view or a VLC player."""

    def __init__(self, url, parent, delay_ms=0):
        self.url = url
        self.started = False
        self.kind = "vlc" if is_media(url) else "web"
        if self.kind == "web" and not HAVE_WEB:
            raise RuntimeError("PyQt6-WebEngine is not installed "
                               "(sudo apt install python3-pyqt6.qtwebengine)")
        if self.kind == "vlc" and not HAVE_VLC:
            raise RuntimeError("python-vlc is not installed (sudo apt install vlc python3-vlc)")

        if self.kind == "web":
            self.widget = QWebEngineView(parent)
            page = QuietPage(web_profile(), self.widget)
            s = page.settings()
            s.setAttribute(QWebEngineSettings.WebAttribute.PlaybackRequiresUserGesture, False)
            s.setAttribute(QWebEngineSettings.WebAttribute.FullScreenSupportEnabled, True)
            s.setAttribute(QWebEngineSettings.WebAttribute.JavascriptCanOpenWindows, False)
            page.setBackgroundColor(QColor("black"))      # no white flash / white edges
            self.widget.setPage(page)
            if BLOCKER:
                page.loadFinished.connect(self._on_loaded)
            if delay_ms > 0:
                QTimer.singleShot(delay_ms, self.start)
            else:
                self.start()
        else:
            self.widget = QFrame(parent)
            self.widget.setStyleSheet("background:black;")
            self.widget.setAttribute(Qt.WidgetAttribute.WA_NativeWindow, True)
            self.inst = vlc.Instance("--no-xlib", "--network-caching=1000", "--quiet")
            self.mp = self.inst.media_player_new()
            wid = int(self.widget.winId())
            if sys.platform.startswith("linux"):
                self.mp.set_xwindow(wid)
            elif sys.platform == "win32":
                self.mp.set_hwnd(wid)
            elif sys.platform == "darwin":
                self.mp.set_nsobject(wid)
            self.mp.set_media(self.inst.media_new(url))
            self.mp.play()

    # ---- cosmetic filtering (hide ad elements the network filter didn't catch)
    def _on_loaded(self, ok):
        page_url = self.widget.url().toString()
        selectors, self._exceptions, self._generichide = BLOCKER.cosmetic(page_url)
        self._seen = set()
        self._inject(selectors)
        # pages keep adding ad boxes after load; re-check a few times
        for delay in (2000, 6000, 15000):
            QTimer.singleShot(delay, lambda: self._inject([]))

    def _inject(self, selectors):
        css = self._css(selectors)
        self.widget.page().runJavaScript(f"{COSMETIC_JS}({json.dumps(css)})", self._on_names)

    def _on_names(self, result):
        if not result or self._generichide:
            return
        classes, ids = result
        classes = [c for c in classes if ("c" + c) not in self._seen]
        ids = [i for i in ids if ("i" + i) not in self._seen]
        self._seen.update("c" + c for c in classes)
        self._seen.update("i" + i for i in ids)
        sels = BLOCKER.generic(classes, ids, self._exceptions)
        if sels:
            self.widget.page().runJavaScript(f"{COSMETIC_JS}({json.dumps(self._css(sels))})")

    @staticmethod
    def _css(selectors):
        sels = [s for s in selectors if "{" not in s and "}" not in s]
        out = []
        for i in range(0, len(sels), 200):          # keep rule groups small
            out.append(",".join(sels[i:i + 200]) + "{display:none !important}")
        return "\n".join(out)

    # ---- controls
    def set_muted(self, muted):
        if self.kind == "web":
            self.widget.page().setAudioMuted(muted)
        else:
            self.mp.audio_set_mute(muted)

    def start(self):
        """First load of a web feed (may be delayed so feeds don't all start at once)."""
        if self.kind == "web" and not self.started:
            self.started = True
            self.widget.setUrl(QUrl(self.url))

    def reload(self):
        if self.kind == "web":
            if not self.started:
                self.start()
            else:
                self.widget.reload()
        else:
            self.mp.stop()
            self.mp.play()

    def stop(self):
        if self.kind == "vlc":
            self.mp.stop()
            self.mp.release()
            self.inst.release()
        else:
            self.widget.setUrl(QUrl("about:blank"))


def paint_black(widget):
    """Make a plain container widget actually fill its background with black
    (Qt leaves plain QWidgets unpainted, which shows up as white gaps)."""
    pal = widget.palette()
    pal.setColor(QPalette.ColorRole.Window, QColor("black"))
    widget.setPalette(pal)
    widget.setAutoFillBackground(True)


class Cell(QWidget):
    """One grid tile: a small title bar + the player."""

    def __init__(self, index, url, window, delay_ms=0):
        super().__init__()
        paint_black(self)
        self.index, self.window = index, window
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)

        self.bar = QWidget()
        self.bar.setStyleSheet("background:#1b1b1b; color:#ddd;")
        bl = QHBoxLayout(self.bar)
        bl.setContentsMargins(6, 2, 6, 2)
        short = url if len(url) < 70 else url[:67] + "..."
        self.title = QLabel(f"{index}  {short}")
        self.btn_audio = QPushButton()
        self.btn_solo = QPushButton("⛶")
        self.btn_reload = QPushButton("⟳")
        for b in (self.btn_audio, self.btn_solo, self.btn_reload):
            b.setFlat(True)
            b.setFixedWidth(30)
            b.setFocusPolicy(Qt.FocusPolicy.NoFocus)
            b.setStyleSheet("color:#ddd; font-size:14px;")
        self.btn_audio.clicked.connect(lambda: window.set_audio(index))
        self.btn_solo.clicked.connect(lambda: window.toggle_solo(index))
        self.btn_reload.clicked.connect(lambda: self.player and self.player.reload())
        bl.addWidget(self.title, 1)
        bl.addWidget(self.btn_audio)
        bl.addWidget(self.btn_solo)
        bl.addWidget(self.btn_reload)
        lay.addWidget(self.bar)

        try:
            self.player = Player(url, self, delay_ms)
            lay.addWidget(self.player.widget, 1)
            if self.player.kind == "web":
                self.player.widget.page().on_fullscreen = \
                    lambda on: window.page_fullscreen(index, on)
        except RuntimeError as e:
            self.player = None
            err = QLabel(str(e))
            err.setAlignment(Qt.AlignmentFlag.AlignCenter)
            err.setStyleSheet("background:black; color:#f66;")
            lay.addWidget(err, 1)

    def set_audio_icon(self, on):
        self.btn_audio.setText("🔊" if on else "🔇")
        self.title.setStyleSheet("color:#7cf;" if on else "color:#ddd;")


class MultiView(QMainWindow):
    def __init__(self, sources):
        super().__init__()
        self.base_title = f"multiview - {len(sources)} feeds"
        self.setWindowTitle(self.base_title)
        self.resize(1600, 900)
        self.setStyleSheet("background:black;")
        self.solo = None
        self.all_muted = False
        self.audio = 0
        self.audio_all = False
        self.was_maximized = False
        self.bars_visible = True

        central = QWidget()
        paint_black(central)
        self.grid = QGridLayout(central)
        self.grid.setContentsMargins(0, 0, 0, 0)
        self.grid.setSpacing(2)
        self.setCentralWidget(central)

        step = int(OPTS["stagger"] * 1000)
        web_n = 0
        self.cells = []
        for i, url in enumerate(sources):
            delay = 0 if is_media(url) else web_n * step
            web_n += 0 if is_media(url) else 1
            self.cells.append(Cell(i + 1, url, self, delay))
        self.layout_grid()
        start = OPTS["audio"]
        if start == "all":
            self.set_audio_all()
        else:
            start = int(start) if start.isdigit() else 0
            self.set_audio(start if 1 <= start <= len(self.cells) else 0)

        if BLOCKER:
            self.stats = QTimer(self)
            self.stats.timeout.connect(self.update_title)
            self.stats.start(1000)

        keys = {
            "Q": self.close, "Ctrl+Q": self.close,
            "Ctrl+C": self.close, "Ctrl+X": self.close,
            "M": self.toggle_mute_all,
            "S": lambda: self.toggle_solo(self.audio or 1),
            "R": self.reload_current,
            "Shift+R": self.reload_all,
            "H": self.toggle_bars,
            "A": self.set_audio_all,
            "F": self.toggle_fullscreen,
            "F11": self.toggle_fullscreen,
            "Esc": self.escape,
        }
        for n in range(1, len(self.cells) + 1):
            keys[str(n)] = lambda n=n: self.set_audio(n)
        QApplication.instance().installEventFilter(self)
        for k, fn in keys.items():
            sc = QShortcut(QKeySequence(k), self)
            sc.setContext(Qt.ShortcutContext.ApplicationShortcut)
            sc.activated.connect(fn)
        # The platform's own fullscreen keys too: macOS takes F11 for "Show Desktop"
        # and uses Ctrl+Cmd+F instead. Skip any that repeat F11, since two shortcuts
        # bound to the same key are ambiguous in Qt and neither one fires.
        for seq in QKeySequence.keyBindings(QKeySequence.StandardKey.FullScreen):
            if seq != QKeySequence("F11"):
                sc = QShortcut(seq, self)
                sc.setContext(Qt.ShortcutContext.ApplicationShortcut)
                sc.activated.connect(self.toggle_fullscreen)

    def eventFilter(self, obj, ev):
        """A mouse click anywhere on a feed gives that feed the audio."""
        if ev.type() == QEvent.Type.MouseButtonPress and isinstance(obj, QWidget):
            for cell in self.cells:
                w = cell.player.widget if cell.player else None
                if w is not None and (obj is w or w.isAncestorOf(obj)):
                    if self.audio != cell.index or self.audio_all or self.all_muted:
                        self.set_audio(cell.index)
                    break
        return False                        # let the click reach the player too

    def update_title(self):
        self.setWindowTitle(f"{self.base_title}  -  {BLOCKER.count:,} ads/trackers blocked")

    # ---- layout
    def layout_grid(self):
        n = len(self.cells)
        positions = {1: [(0, 0)], 2: [(0, 0), (0, 1)],
                     3: [(0, 0), (0, 1), (1, 0)], 4: [(0, 0), (0, 1), (1, 0), (1, 1)]}[n]
        for cell, (r, c) in zip(self.cells, positions):
            self.grid.addWidget(cell, r, c)
            cell.show()
        for i in range(2):
            self.grid.setRowStretch(i, 1 if n > 2 or i == 0 else 0)
            self.grid.setColumnStretch(i, 1)

    def toggle_solo(self, index):
        if self.solo == index:
            self.solo = None
            for cell in self.cells:
                cell.show()
        else:
            self.solo = index
            for cell in self.cells:
                cell.setVisible(cell.index == index)
            self.set_audio(index)

    # ---- audio
    def set_audio_all(self):
        self.audio_all = True
        self.all_muted = False
        for cell in self.cells:
            if cell.player:
                cell.player.set_muted(False)
            cell.set_audio_icon(True)

    def set_audio(self, index):
        self.audio = index
        self.audio_all = False
        self.all_muted = False
        for cell in self.cells:
            on = cell.index == index
            if cell.player:
                cell.player.set_muted(not on)
            cell.set_audio_icon(on)

    def toggle_mute_all(self):
        self.all_muted = not self.all_muted
        for cell in self.cells:
            on = (not self.all_muted) and (self.audio_all or cell.index == self.audio)
            if cell.player:
                cell.player.set_muted(not on)
            cell.set_audio_icon(on)

    # ---- misc
    def reload_current(self):
        """Reload only the feed that has the audio (click a broken feed, then press R)."""
        cell = next((c for c in self.cells if c.index == self.audio), None)
        if cell and not self.audio_all:
            if cell.player:
                cell.player.reload()
        else:
            self.reload_all()

    def reload_all(self):
        """Reload every feed, spaced out by the stagger setting."""
        step = int(OPTS["stagger"] * 1000)
        n = 0
        for cell in self.cells:
            if not cell.player:
                continue
            if cell.player.kind == "web" and step:
                QTimer.singleShot(n * step, cell.player.reload)
                n += 1
            else:
                cell.player.reload()

    def toggle_bars(self):
        self.bars_visible = not self.bars_visible
        self.apply_bars()

    def apply_bars(self):
        """Title bars (feed number + URL) never show in fullscreen."""
        show = self.bars_visible and not self.isFullScreen()
        for cell in self.cells:
            cell.bar.setVisible(show)

    def enter_fullscreen(self):
        if not self.isFullScreen():
            self.was_maximized = self.isMaximized()
            self.showFullScreen()
        self.apply_bars()

    def leave_fullscreen(self):
        if self.isFullScreen():
            self.showMaximized() if self.was_maximized else self.showNormal()
        self.apply_bars()

    def toggle_fullscreen(self):
        self.leave_fullscreen() if self.isFullScreen() else self.enter_fullscreen()

    def page_fullscreen(self, index, on):
        """The player's own fullscreen button: that feed alone, whole screen."""
        if on:
            if self.solo != index:
                self.toggle_solo(index)
            self.enter_fullscreen()
        else:
            self.escape()

    def escape(self):
        """Esc: always back to the normal window with every feed showing."""
        for cell in self.cells:
            page = cell.player.widget.page() if cell.player and cell.player.kind == "web" else None
            if page is not None and page.in_fullscreen:
                page.in_fullscreen = False
                page.triggerAction(QWebEnginePage.WebAction.ExitFullScreen)
        if self.solo is not None:
            self.toggle_solo(self.solo)
        self.leave_fullscreen()

    def closeEvent(self, ev):
        for cell in self.cells:
            if cell.player:
                cell.player.stop()
        super().closeEvent(ev)


def find_widevine():
    """Return the newest libwidevinecdm.so installed by any Chromium-based app."""
    setting = OPTS["widevine"]
    if setting.lower() in ("no", "off", "false", "0", ""):
        return None
    if setting.lower() != "auto":
        return setting if os.path.exists(setting) else None
    home = Path.home()
    lib = "_platform_specific/linux_x64/libwidevinecdm.so"
    patterns = [                       # where Chrome, Chromium, Edge, Vivaldi, Brave, Electron... keep it
        (Path("/opt"), f"*/*/WidevineCdm/{lib}"),
        (Path("/opt"), f"*/*/*/WidevineCdm/{lib}"),
        (Path("/usr/lib"), f"*/WidevineCdm/{lib}"),
        (home / ".config", f"*/WidevineCdm/*/{lib}"),
        (home / ".config", f"*/*/WidevineCdm/*/{lib}"),
        (home / ".var/app", f"*/config/*/WidevineCdm/*/{lib}"),
        (home / ".var/app", f"*/config/*/*/WidevineCdm/*/{lib}"),
        (home / ".local/share/flatpak/app", f"*/*/*/*/files/extra/WidevineCdm/{lib}"),
        (Path("/var/lib/flatpak/app"), f"*/*/*/*/files/extra/WidevineCdm/{lib}"),
    ]
    best, best_ver = None, ()
    for root, pattern in patterns:
        if not root.is_dir():
            continue
        try:
            for found in root.glob(pattern):
                ver = ()
                try:
                    ver = tuple(int(x) for x in json.loads(
                        (found.parents[2] / "manifest.json").read_text())["version"].split("."))
                except Exception:
                    pass
                if best is None or ver > best_ver:
                    best, best_ver = found, ver
        except OSError:
            continue
    return str(best) if best else None


def enable_widevine():
    lib = find_widevine()
    if not lib:
        if OPTS["widevine"].lower() not in ("no", "off", "false", "0", ""):
            print("multiview: no Widevine (DRM) library found - protected streams won't play.\n"
                  "           Installing Google Chrome provides one.")
        return
    flags = os.environ.get("QTWEBENGINE_CHROMIUM_FLAGS", "")
    if "--widevine-path" not in flags:
        os.environ["QTWEBENGINE_CHROMIUM_FLAGS"] = f'{flags} --widevine-path="{lib}"'.strip()
    print(f"multiview: DRM (Widevine) on: {lib}")


def install_terminal_quit():
    """Make Ctrl+C (SIGINT) / SIGTERM from the terminal always work.

    Qt's event loop keeps Python's normal signal handling from running, and a
    hung page could freeze the GUI thread entirely.  So the signals are blocked
    here (before Qt starts any threads, which inherit the mask) and a separate
    thread waits for them: the first one asks Qt to quit cleanly, and if the
    app is still alive 3 s later - or a second Ctrl+C arrives - it is killed.
    """
    sigs = {signal.SIGINT, signal.SIGTERM}
    signal.pthread_sigmask(signal.SIG_BLOCK, sigs)

    def waiter():
        signal.sigwait(sigs)
        print("\nmultiview: quitting (Ctrl+C again to force)", flush=True)
        app = QApplication.instance()
        if app is not None:
            QMetaObject.invokeMethod(app, "quit", Qt.ConnectionType.QueuedConnection)
            signal.sigtimedwait(sigs, 3)
        print("multiview: forced exit", flush=True)
        os._exit(130)

    threading.Thread(target=waiter, daemon=True).start()


def main():
    if "-h" in sys.argv or "--help" in sys.argv:
        print(__doc__)
        return
    install_terminal_quit()
    if HAVE_WEB and any(not is_media(s) for s in SOURCES):
        enable_widevine()
    app = QApplication(sys.argv)
    if len(SOURCES) < 1:
        QMessageBox.information(None, "multiview",
                                f"No feeds given.\n\nPass 2-4 URLs on the command line, "
                                f"or fill in the [feeds] list in:\n{INI}")
        return
    win = MultiView(SOURCES)
    win.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
