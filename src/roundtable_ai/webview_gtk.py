"""Roundtable's native window on Linux: GTK with WebKit, the system's own web view.

Run by the system Python (the GTK bindings come with the desktop, not with pip),
so this file imports nothing from roundtable_ai:

    /usr/bin/python3 -I webview_gtk.py URL TITLE ICON_DIR STATE_FILE DATA_DIR

GTK 4 with WebKit 6 is used when present, otherwise GTK 3 with WebKit2 4.1 / 4.0.
Links to other sites open in your browser. Ctrl +/-/0 zoom, Ctrl+R reloads,
Ctrl+W / Ctrl+Q close. Size, maximized state and zoom are remembered.
"""

import json
import os
import sys

import gi

URL, TITLE, ICON_DIR, STATE_FILE, DATA_DIR = sys.argv[1:6]
APP_ID = "ai.roundtable.Roundtable"

API = 0
for gtk, wk, name in (("4.0", "6.0", "WebKit"), ("3.0", "4.1", "WebKit2"), ("3.0", "4.0", "WebKit2")):
    try:
        gi.require_version("Gtk", gtk)
        gi.require_version(name, wk)
        API = 6 if name == "WebKit" else 4
        break
    except ValueError:
        continue
if not API:
    sys.exit(3)

from gi.repository import Gdk, Gio, GLib, Gtk  # noqa: E402

if API == 6:
    from gi.repository import WebKit  # noqa: E402
else:
    from gi.repository import WebKit2 as WebKit  # noqa: E402

GLib.set_prgname(APP_ID)
GLib.set_application_name(TITLE)


def load_state():
    try:
        with open(STATE_FILE, encoding="utf-8") as fh:
            st = json.load(fh)
        return st if isinstance(st, dict) else {}
    except (OSError, ValueError):
        return {}


def save_state(st):
    try:
        os.makedirs(os.path.dirname(STATE_FILE), exist_ok=True)
        with open(STATE_FILE, "w", encoding="utf-8") as fh:
            json.dump(st, fh)
    except OSError:
        pass


STATE = load_state()
ORIGIN = "/".join(URL.split("/")[:3])


def make_view():
    os.makedirs(DATA_DIR, exist_ok=True)
    data, cache = os.path.join(DATA_DIR, "data"), os.path.join(DATA_DIR, "cache")
    if API == 6:
        view = WebKit.WebView(network_session=WebKit.NetworkSession.new(data, cache))
    else:
        mgr = WebKit.WebsiteDataManager(base_data_directory=data, base_cache_directory=cache)
        view = WebKit.WebView.new_with_context(WebKit.WebContext.new_with_website_data_manager(mgr))
    settings = view.get_settings()
    for prop, value in (("enable-developer-extras", bool(os.environ.get("RT_DEVTOOLS"))), ("enable-back-forward-navigation-gestures", False),
                        ("javascript-can-open-windows-automatically", False)):
        try:
            settings.set_property(prop, value)
        except TypeError:
            pass
    view.set_zoom_level(float(STATE.get("zoom") or 1.0))
    view.connect("decide-policy", on_policy)
    view.connect("permission-request", on_permission)
    return view


def on_policy(view, decision, kind):
    if kind not in (WebKit.PolicyDecisionType.NAVIGATION_ACTION, WebKit.PolicyDecisionType.NEW_WINDOW_ACTION):
        return False
    try:
        uri = decision.get_navigation_action().get_request().get_uri()
    except Exception:
        return False
    if uri.startswith(ORIGIN + "/") or uri == ORIGIN or uri.startswith("about:"):
        if kind == WebKit.PolicyDecisionType.NEW_WINDOW_ACTION:
            view.load_uri(uri)
            decision.ignore()
            return True
        return False
    try:
        Gio.AppInfo.launch_default_for_uri(uri, None)
    except GLib.Error:
        pass
    decision.ignore()
    return True


def on_permission(view, request):
    if isinstance(request, WebKit.NotificationPermissionRequest):
        request.allow()
        return True
    request.deny()
    return True


def on_key(view, ctrl, key):
    zoom = view.get_zoom_level()
    if key in ("plus", "equal", "KP_Add"):
        view.set_zoom_level(min(2.5, zoom + 0.1))
    elif key in ("minus", "KP_Subtract"):
        view.set_zoom_level(max(0.5, zoom - 0.1))
    elif key in ("0", "KP_0"):
        view.set_zoom_level(1.0)
    elif key in ("r", "R"):
        view.reload()
    elif key in ("w", "W", "q", "Q"):
        return "close"
    else:
        return False
    STATE["zoom"] = round(view.get_zoom_level(), 2)
    return True


def remember(win):
    if API == 6:
        w, h = win.get_default_size()
        maximized = win.is_maximized()
    else:
        w, h = win.get_size()
        maximized = win.is_maximized()
    if not maximized and w > 200 and h > 200:
        STATE["width"], STATE["height"] = w, h
    STATE["maximized"] = bool(maximized)
    save_state(STATE)


def build_window(win):
    win.set_title(TITLE)
    win.set_default_size(int(STATE.get("width") or 1440), int(STATE.get("height") or 920))
    view = make_view()
    if API == 6:
        win.set_child(view)
        keys = Gtk.EventControllerKey()

        def pressed(_c, keyval, _code, mods):
            if not mods & Gdk.ModifierType.CONTROL_MASK:
                return False
            r = on_key(view, True, Gdk.keyval_name(keyval) or "")
            if r == "close":
                win.close()
                return True
            return bool(r)

        keys.connect("key-pressed", pressed)
        win.add_controller(keys)
        win.connect("close-request", lambda w: (remember(w), False)[1])
        try:
            theme = Gtk.IconTheme.get_for_display(win.get_display())
            theme.add_search_path(ICON_DIR)
        except Exception:
            pass
        win.set_icon_name(APP_ID)
    else:
        win.add(view)

        def pressed(w, event):
            if not event.state & Gdk.ModifierType.CONTROL_MASK:
                return False
            r = on_key(view, True, Gdk.keyval_name(event.keyval) or "")
            if r == "close":
                w.close()
                return True
            return bool(r)

        win.connect("key-press-event", pressed)
        win.connect("delete-event", lambda w, _e: (remember(w), False)[1])
        for name in ("ai.roundtable.Roundtable.png", "ai.roundtable.Roundtable.svg"):
            path = os.path.join(ICON_DIR, name)
            if os.path.exists(path):
                try:
                    win.set_icon_from_file(path)
                    break
                except GLib.Error:
                    pass
    if STATE.get("maximized"):
        win.maximize()
    view.load_uri(URL)
    return view


if API == 6:
    app = Gtk.Application(application_id=APP_ID, flags=Gio.ApplicationFlags.NON_UNIQUE)

    def activate(application):
        win = Gtk.ApplicationWindow(application=application)
        build_window(win)
        win.present()

    app.connect("activate", activate)
    sys.exit(app.run([sys.argv[0]]))
else:
    window = Gtk.Window()
    build_window(window)
    window.connect("destroy", lambda _w: Gtk.main_quit())
    window.show_all()
    Gtk.main()
