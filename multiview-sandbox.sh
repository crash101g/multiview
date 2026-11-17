#!/usr/bin/env bash
# SPDX-License-Identifier: GPL-3.0-only
# multiview-sandbox.sh - run multiview inside an OS sandbox.
#
# Same app, same feeds, same codecs - the sandbox only limits what it can SEE.
# If a malicious web page ever broke out of the browser engine, it would land
# in a box that has no access to your real home folder (~/.ssh, browser logins,
# documents ...), cannot change multiview's own code, and cannot talk to your
# desktop session bus.
#
#   Linux: bubblewrap (bwrap)       sudo apt install bubblewrap
#   macOS: sandbox-exec + multiview.sb (built into macOS)
#
# multiview.py runs this for you (unless --no-sandbox / sandbox = no), so you
# normally don't start it yourself. Usage: same arguments as multiview.py, e.g.
#   ./multiview-sandbox.sh
#   ./multiview-sandbox.sh -v URL1 URL2
#   MULTIVIEW_SANDBOX_DEBUG=1 ./multiview-sandbox.sh   # print the sandbox command

set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd -P)"

case "$(uname -s)" in
# ---------------------------------------------------------------------- Linux
Linux)
    command -v bwrap >/dev/null || { echo "multiview-sandbox: bwrap not found (sudo apt install bubblewrap)" >&2; exit 1; }

    RUNDIR="${XDG_RUNTIME_DIR:-/run/user/$(id -u)}"
    CACHE="${XDG_CACHE_HOME:-$HOME/.cache}/multiview"
    mkdir -p "$CACHE"

    args=(
        --die-with-parent
        --unshare-all --share-net          # own pid/ipc/uts/user namespaces; network is needed for feeds
        --new-session                      # no typing into the launching terminal
        # the operating system, read-only
        --ro-bind /usr /usr
        --symlink usr/bin /bin --symlink usr/sbin /sbin
        --symlink usr/lib /lib --symlink usr/lib64 /lib64
        --ro-bind /etc /etc
        --ro-bind-try /opt /opt            # Google Chrome's Widevine copy lives here
        --proc /proc
        --dev /dev
        --ro-bind /sys /sys                # GPU drivers read device info here
        --dev-bind-try /dev/dri /dev/dri   # GPU (video decode + drawing)
        --tmpfs /tmp
        --tmpfs /var --symlink ../tmp /var/tmp
        --tmpfs /run
        --ro-bind-try /run/systemd/resolve /run/systemd/resolve   # DNS (/etc/resolv.conf points here)
        # an empty, throw-away home folder
        --tmpfs "$HOME"
        --dir "$RUNDIR" --chmod 0700 "$RUNDIR"
        # multiview's own folder: read-only, so nothing can rewrite the code
        --ro-bind "$HERE" "$HERE"
        # ad-block list cache: the only writable place that survives
        --bind "$CACHE" "$CACHE"
        # display: X11 (Qt + mpv use it) and Wayland
        --ro-bind-try /tmp/.X11-unix /tmp/.X11-unix
        # audio
        --ro-bind-try "$RUNDIR/pipewire-0" "$RUNDIR/pipewire-0"
        --ro-bind-try "$RUNDIR/pulse/native" "$RUNDIR/pulse/native"
        --setenv HOME "$HOME"
        --setenv MULTIVIEW_SANDBOXED 1     # tells multiview.py not to restart itself in a sandbox
        --setenv XDG_RUNTIME_DIR "$RUNDIR"
        --setenv XDG_CACHE_HOME "${CACHE%/multiview}"
        --unsetenv DBUS_SESSION_BUS_ADDRESS  # no session bus: it can launch programs outside
        --unsetenv SESSION_MANAGER
        --chdir "$HERE"
    )
    [ -n "${WAYLAND_DISPLAY:-}" ] && [ -S "$RUNDIR/$WAYLAND_DISPLAY" ] &&
        args+=(--ro-bind "$RUNDIR/$WAYLAND_DISPLAY" "$RUNDIR/$WAYLAND_DISPLAY")
    [ -n "${XAUTHORITY:-}" ] && [ -f "$XAUTHORITY" ] &&
        args+=(--ro-bind "$XAUTHORITY" "$XAUTHORITY")
    [ -f "$HOME/.Xauthority" ] && args+=(--ro-bind "$HOME/.Xauthority" "$HOME/.Xauthority")

    # pip --user packages (the "adblock" engine), read-only
    pyuser="$(python3 -c 'import site; print(site.getusersitepackages())' 2>/dev/null || true)"
    [ -n "$pyuser" ] && [ -d "$pyuser" ] && args+=(--ro-bind "$pyuser" "$pyuser")

    # Widevine (DRM) copies kept by Chrome/Chromium/Edge/Electron... in ~/.config,
    # ~/.var (flatpak) - read-only. Only the WidevineCdm folders, nothing else.
    shopt -s nullglob
    for d in "$HOME"/.config/*/WidevineCdm "$HOME"/.config/*/*/WidevineCdm \
             "$HOME"/.var/app/*/config/*/WidevineCdm "$HOME"/.var/app/*/config/*/*/WidevineCdm \
             "$HOME"/.local/share/flatpak/app/*/*/*/*/files/extra/WidevineCdm; do
        args+=(--ro-bind "$d" "$d")
    done
    for d in /var/lib/flatpak/app/*/*/*/*/files/extra/WidevineCdm; do
        args+=(--ro-bind "$d" "$d")
    done
    # a widevine = /path/libwidevinecdm.so set in multiview.ini
    wv="$(sed -n 's/^[[:space:]]*widevine[[:space:]]*=[[:space:]]*\(\/.*\)$/\1/p' "$HERE/multiview.ini" 2>/dev/null | tail -1)"
    [ -n "$wv" ] && [ -f "$wv" ] && args+=(--ro-bind "$wv" "$wv")
    shopt -u nullglob

    [ -n "${MULTIVIEW_SANDBOX_DEBUG:-}" ] && printf '%q ' bwrap "${args[@]}" python3 "$HERE/multiview.py" "$@" >&2 && echo >&2
    echo "multiview: running inside the bwrap sandbox" >&2
    exec bwrap "${args[@]}" python3 "$HERE/multiview.py" "$@"
    ;;

# ---------------------------------------------------------------------- macOS
Darwin)
    PROFILE="$HERE/multiview.sb"
    [ -f "$PROFILE" ] || { echo "multiview-sandbox: $PROFILE is missing" >&2; exit 1; }
    CACHE="$HOME/Library/Caches/multiview"
    mkdir -p "$CACHE"
    export XDG_CACHE_HOME="$HOME/Library/Caches"     # multiview.py keeps its lists in $XDG_CACHE_HOME/multiview
    export MULTIVIEW_SANDBOXED=1                     # tells multiview.py not to restart itself in a sandbox
    PY="${MULTIVIEW_PYTHON:-$(command -v python3)}"
    # Resolve symlinks so the profile can allow the real paths.
    PY_REAL="$("$PY" -c 'import sys, os; print(os.path.realpath(sys.executable))')"
    PY_PREFIX="$("$PY" -c 'import sys, os; print(os.path.realpath(sys.prefix))')"
    PY_BASE="$("$PY" -c 'import sys, os; print(os.path.realpath(sys.base_prefix))')"
    PY_USER="$("$PY" -c 'import site; print(site.getusersitepackages())')"
    params=(
        -D "HERE=$HERE"
        -D "HOME=$HOME"
        -D "CACHE=$CACHE"
        -D "PY_PREFIX=$PY_PREFIX"
        -D "PY_BASE=$PY_BASE"
        -D "PY_USER=$PY_USER"
    )
    [ -n "${MULTIVIEW_SANDBOX_DEBUG:-}" ] && echo "sandbox-exec -f $PROFILE ${params[*]} $PY_REAL $HERE/multiview.py $*" >&2
    echo "multiview: running inside the macOS sandbox (sandbox-exec)" >&2
    cd "$HERE"
    exec sandbox-exec -f "$PROFILE" "${params[@]}" "$PY_REAL" "$HERE/multiview.py" "$@"
    ;;

*)
    echo "multiview-sandbox: no sandbox support for $(uname -s) - run multiview.py directly" >&2
    exit 1
    ;;
esac
