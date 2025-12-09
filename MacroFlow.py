#!/usr/bin/env python3
# MacroFlow - Manual icon capture version (MINIMAL UI)

import os
import sys
import time
import json
import threading
import logging
from datetime import datetime
from math import floor

import pyautogui
from pynput import mouse, keyboard
from PIL import Image, ImageGrab
import numpy as np
import cv2
import tkinter as tk
from tkinter import ttk, filedialog, messagebox, scrolledtext

# -----------------------
# Fix dla AppImage/OneFile - DODANE NA SAMYM POCZĄTKU
# -----------------------
def setup_appimage_paths():
    """Ustaw poprawne ścieżki dla AppImage/OneFile"""
    # Sprawdź czy jesteśmy w trybie zamrożonym (Nuitka/AppImage)
    is_frozen = getattr(sys, 'frozen', False)
    has_appdir = 'APPDIR' in os.environ
    
    if is_frozen or has_appdir:
        # Użyj katalogu domowego użytkownika
        home_dir = os.path.expanduser("~")
        app_data_dir = os.path.join(home_dir, ".macroflow")
        
        # Utwórz katalog jeśli nie istnieje
        os.makedirs(app_data_dir, exist_ok=True)
        
        # Zwróć poprawione ścieżki
        return {
            "log_file": os.path.join(app_data_dir, "macroflow_mini.log"),
            "data_file": os.path.join(app_data_dir, "macroflow_mini.json"),
            "template_dir": os.path.join(app_data_dir, "templates_mini"),
            "app_data_dir": app_data_dir,
            "is_appimage": True
        }
    else:
        # Normalny tryb Pythona
        return {
            "log_file": "macroflow_mini.log",
            "data_file": "macroflow_mini.json",
            "template_dir": "templates_mini",
            "app_data_dir": ".",
            "is_appimage": False
        }

# Uruchom setup i pobierz ścieżki
PATHS = setup_appimage_paths()

# -----------------------
# Config z poprawionymi ścieżkami
# -----------------------
APP_NAME = "MacroFlow Mini"
LOG_FILE = PATHS["log_file"]  # Użyj poprawnej ścieżki
DATA_FILE = PATHS["data_file"]
TEMPLATE_DIR = PATHS["template_dir"]
APP_DATA_DIR = PATHS["app_data_dir"]
DEFAULT_TEMPLATE_SIZE = 40
TEMPLATE_MATCH_THRESH = 0.70
RETRY_RADII = [10, 30, 60, 120]

# Sampling interval for drag (seconds)
SAMPLE_INTERVAL = 0.01

# pyautogui tweaks
pyautogui.FAILSAFE = False
pyautogui.MINIMUM_DURATION = 0
pyautogui.MINIMUM_SLEEP = 0.005

# -----------------------
# Color Scheme - Minimal Dark
# -----------------------
COLORS = {
    "bg": "#1a1a1a",
    "fg": "#e0e0e0",
    "accent": "#4a9eff",
    "secondary": "#555555",
    "success": "#2ecc71",
    "error": "#e74c3c",
    "warning": "#f39c12",
    "card": "#2d2d2d",
    "border": "#444444",
    "input_bg": "#3a3a3a"
}

# -----------------------
# Logging z poprawioną ścieżką
# -----------------------
def setup_logging():
    """Konfiguruj logowanie z obsługą błędów"""
    try:
        # Upewnij się że katalog istnieje
        log_dir = os.path.dirname(LOG_FILE)
        if log_dir and not os.path.exists(log_dir):
            os.makedirs(log_dir, exist_ok=True)
        
        # Konfiguruj logging
        logging.basicConfig(
            filename=LOG_FILE, 
            level=logging.INFO,
            format="%(asctime)s - %(levelname)s - %(message)s",
            filemode='a'  # Append zamiast write
        )
        
        # Dodaj też handler konsoli dla AppImage
        if PATHS["is_appimage"]:
            console_handler = logging.StreamHandler()
            console_handler.setLevel(logging.INFO)
            formatter = logging.Formatter('%(asctime)s - %(levelname)s - %(message)s')
            console_handler.setFormatter(formatter)
            logging.getLogger().addHandler(console_handler)
            print(f"AppImage mode: Logging to {LOG_FILE}")
        
        logging.info("=== MacroFlow Mini start ===")
        logging.info(f"AppImage mode: {PATHS['is_appimage']}")
        logging.info(f"Data directory: {APP_DATA_DIR}")
        
    except Exception as e:
        # Fallback do logowania w konsoli
        logging.basicConfig(level=logging.INFO)
        logging.error(f"Nie można skonfigurować logowania do pliku: {e}")
        print(f"Log setup error: {e}")
        print(f"Using fallback logging to console")

# Uruchom setup logowania
setup_logging()

# -----------------------
# Globals
# -----------------------
events = []  # recorded events
recording = False
playing = False
last_event_time = None

# drag state
_dragging = False
_drag_start = None
_drag_start_time = None
_drag_samples = []
_drag_button = None  # Track which button is being dragged

# template store
templates = []

# threading control
_playback_thread = None

# listeners
_mouse_listener = None
_keyboard_listener = None

# GUI app placeholder
APP = None

# Hotkey configuration
HOTKEYS = {
    "start_record": "F2",
    "stop_record": "F4", 
    "start_play": "F8",
    "stop_play": "F10"
}

# Compact mode state
compact_mode = False
compact_window = None

# ensure template dir exists - UŻYJ POPRAWNEJ ŚCIEŻKI
os.makedirs(TEMPLATE_DIR, exist_ok=True)

# Dodaj informację o ścieżkach na konsolę dla debugowania
print(f"=== MacroFlow Configuration ===")
print(f"LOG_FILE: {LOG_FILE}")
print(f"DATA_FILE: {DATA_FILE}")
print(f"TEMPLATE_DIR: {TEMPLATE_DIR}")
print(f"Is AppImage: {PATHS['is_appimage']}")
print(f"===============================")

# -----------------------
# Helpers: screenshot conversions
# -----------------------
def pil_to_cv2(img_pil):
    arr = np.array(img_pil)
    if arr.ndim == 2:
        return arr
    return cv2.cvtColor(arr, cv2.COLOR_RGB2BGR)

def screenshot_full_pil():
    try:
        return ImageGrab.grab()
    except Exception as e:
        logging.exception("screenshot_full_pil error")
        try:
            return pyautogui.screenshot()
        except Exception as e2:
            logging.exception("fallback screenshot error")
            return None

def screenshot_region_pil(left, top, w, h):
    try:
        return ImageGrab.grab(bbox=(left, top, left + w, top + h))
    except Exception as e:
        logging.exception("screenshot_region_pil error")
        try:
            return pyautogui.screenshot(region=(left, top, w, h))
        except Exception:
            return None

def get_pixel_color(x, y):
    """Return RGB tuple at screen pixel (x,y)."""
    try:
        im = screenshot_region_pil(x, y, 1, 1)
        if im is None:
            return (0,0,0)
        return im.getpixel((0,0))
    except Exception as e:
        logging.exception("get_pixel_color error")
        return (0,0,0)

# -----------------------
# Template utilities
# -----------------------
def save_template_from_rect(left, top, w, h, name_prefix="tmpl"):
    """Capture region and save PNG; return path and BGR numpy array or (None, None)"""
    im = screenshot_region_pil(left, top, w, h)
    if im is None:
        return None, None
    ts = int(time.time()*1000)
    fname = f"{name_prefix}_{ts}_{left}_{top}_{w}x{h}.png"
    path = os.path.join(TEMPLATE_DIR, fname)
    try:
        im.save(path)
    except Exception as e:
        logging.exception(f"save_template_from_rect save error: {e}")
        return None, None
    bgr = pil_to_cv2(im)
    return path, bgr

def load_template_from_file(path):
    try:
        im = Image.open(path).convert("RGB")
        bgr = cv2.cvtColor(np.array(im), cv2.COLOR_RGB2BGR)
        return bgr
    except Exception as e:
        logging.exception("load_template_from_file error")
        return None

def register_template(name, path, bgr):
    templates.append({"name": name, "path": path, "bgr": bgr})

# -----------------------
# Template matching
# -----------------------
def match_template_search(template_bgr, bbox=None, threshold=TEMPLATE_MATCH_THRESH):
    """
    Search template on screen.
    Return center_x, center_y, score or (None,None,0).
    """
    try:
        if bbox is None:
            pil = screenshot_full_pil()
            if pil is None:
                return None, None, 0.0
            search_img = pil_to_cv2(pil)
            offx, offy = 0, 0
        else:
            left, top, w, h = bbox
            pil = screenshot_region_pil(left, top, w, h)
            if pil is None:
                return None, None, 0.0
            search_img = pil_to_cv2(pil)
            offx, offy = left, top

        res = cv2.matchTemplate(search_img, template_bgr, cv2.TM_CCOEFF_NORMED)
        if res is None:
            return None, None, 0.0
        min_val, max_val, min_loc, max_loc = cv2.minMaxLoc(res)
        if max_val >= threshold:
            th, tw = template_bgr.shape[0], template_bgr.shape[1]
            center_x = offx + max_loc[0] + tw // 2
            center_y = offy + max_loc[1] + th // 2
            return center_x, center_y, float(max_val)
        return None, None, float(max_val)
    except Exception as e:
        logging.exception("match_template_search error")
        return None, None, 0.0

# -----------------------
# Recording handlers (pynput) - ORIGINAL VERSION with RIGHT CLICK SUPPORT
# -----------------------
def _on_move(x, y):
    global _dragging, _drag_samples
    try:
        if recording and _dragging:
            _drag_samples.append({"x": int(x), "y": int(y), "t": time.perf_counter()})
    except Exception:
        logging.exception("_on_move error (ignored)")

def _on_click(x, y, button, pressed):
    global recording, events, last_event_time
    global _dragging, _drag_start, _drag_start_time, _drag_samples, _drag_button

    if not recording:
        return

    now = time.time()
    try:
        if pressed:
            _dragging = True
            _drag_start = (int(x), int(y))
            _drag_start_time = now
            _drag_samples = [{"x": int(x), "y": int(y), "t": time.perf_counter()}]
            _drag_button = button  # Store which button is being used
            logging.info(f"Record {button} press at {_drag_start}")
            return

        # release
        if _dragging and button == _drag_button:  # Only process if it's the same button
            _drag_samples.append({"x": int(x), "y": int(y), "t": time.perf_counter()})
            duration = max(0.0, now - (_drag_start_time or now))
            # compute delay since last event
            if last_event_time is None:
                delay = 0.0
            else:
                delay = max(0.0, now - last_event_time)

            # Determine button name
            button_name = "left"
            if button == mouse.Button.right:
                button_name = "right"
            elif button == mouse.Button.middle:
                button_name = "middle"

            # treat short drags as clicks (few samples)
            if len(_drag_samples) < 3:
                ev = {
                    "type": "click",
                    "pos": (int(x), int(y)),
                    "button": button_name,
                    "timestamp": now,
                    "delay": delay,
                    "template": None
                }
                logging.info(f"Recorded {button_name.upper()} CLICK at {(x,y)}")
            else:
                # normalize dt deltas
                normalized = []
                prev_t = _drag_samples[0]["t"]
                for s in _drag_samples:
                    dt = s["t"] - prev_t
                    normalized.append({"x": int(s["x"]), "y": int(s["y"]), "dt": float(dt)})
                    prev_t = s["t"]
                ev = {
                    "type": "drag",
                    "start": (_drag_start[0], _drag_start[1]),
                    "end": (int(x), int(y)),
                    "button": button_name,
                    "timestamp": now,
                    "delay": delay,
                    "duration": duration,
                    "samples": normalized,
                    "template": None
                }
                logging.info(f"Recorded {button_name.upper()} DRAG {ev['start']} -> {ev['end']} samples={len(normalized)} dur={duration:.3f}s")

            events.append(ev)
            last_event_time = now

            # reset drag state
            _dragging = False
            _drag_start = None
            _drag_start_time = None
            _drag_samples = []
            _drag_button = None
    except Exception:
        logging.exception("_on_click error")

def _on_key_press_record(key):
    """Handle keyboard key press during recording"""
    global recording, events, last_event_time
    
    if not recording:
        return
    
    now = time.time()
    try:
        # Get key name
        try:
            # Try to get character
            if hasattr(key, 'char') and key.char:
                key_name = key.char
            else:
                # Get key name (like 'space', 'enter', etc.)
                key_name = str(key).replace("Key.", "")
        except:
            key_name = str(key)
        
        # Don't record hotkeys used to control the app
        if key_name in ['f2', 'f4', 'f8', 'f10']:
            return
        
        # Calculate delay
        delay = 0.0 if last_event_time is None else max(0.0, now - last_event_time)
        
        # Create key press event
        ev = {
            "type": "key_press",
            "key": key_name,
            "timestamp": now,
            "delay": delay
        }
        
        events.append(ev)
        last_event_time = now
        logging.info(f"Recorded KEY PRESS: {key_name}")
        
    except Exception:
        logging.exception("Error in _on_key_press_record")

def _on_key_release_record(key):
    """Handle keyboard key release during recording"""
    global recording, events
    
    if not recording:
        return
    
    now = time.time()
    try:
        # Get key name
        try:
            if hasattr(key, 'char') and key.char:
                key_name = key.char
            else:
                key_name = str(key).replace("Key.", "")
        except:
            key_name = str(key)
        
        # Don't record hotkeys used to control the app
        if key_name in ['f2', 'f4', 'f8', 'f10']:
            return
        
        # Create key release event (no delay for releases)
        ev = {
            "type": "key_release",
            "key": key_name,
            "timestamp": now,
            "delay": 0.0
        }
        
        events.append(ev)
        logging.info(f"Recorded KEY RELEASE: {key_name}")
        
    except Exception:
        logging.exception("Error in _on_key_release_record")

# -----------------------
# Playback functions
# -----------------------
def play_click_event(ev, gui_log=None):
    pos = ev.get("pos")
    button = ev.get("button", "left")
    tpl_info = ev.get("template")
    
    # try match by template
    if tpl_info:
        tpl_bgr = None
        if isinstance(tpl_info, dict) and tpl_info.get("bgr") is not None:
            try:
                tpl_bgr = np.array(tpl_info["bgr"], dtype=np.uint8)
            except Exception:
                tpl_bgr = None
        elif isinstance(tpl_info, str) and os.path.exists(tpl_info):
            tpl_bgr = load_template_from_file(tpl_info)
        if tpl_bgr is not None:
            # try fullscreen then expanding radii
            cx, cy, sc = match_template_search(tpl_bgr, bbox=None)
            if cx is not None:
                if button == "left":
                    pyautogui.click(cx, cy)
                elif button == "right":
                    pyautogui.click(cx, cy, button='right')
                elif button == "middle":
                    pyautogui.click(cx, cy, button='middle')
                if gui_log: gui_log(f"{button.upper()} CLICK matched at {cx},{cy} score={sc:.3f}")
                return
            # else retry radii around recorded pos if available
            if pos:
                for r in RETRY_RADII:
                    bbox = (pos[0]-r, pos[1]-r, r*2, r*2)
                    cx, cy, sc = match_template_search(tpl_bgr, bbox=bbox)
                    if cx is not None:
                        if button == "left":
                            pyautogui.click(cx, cy)
                        elif button == "right":
                            pyautogui.click(cx, cy, button='right')
                        elif button == "middle":
                            pyautogui.click(cx, cy, button='middle')
                        if gui_log: gui_log(f"{button.upper()} CLICK matched near pos at {cx},{cy} score={sc:.3f}")
                        return
    # fallback to raw pos
    if pos:
        if button == "left":
            pyautogui.click(pos[0], pos[1])
        elif button == "right":
            pyautogui.click(pos[0], pos[1], button='right')
        elif button == "middle":
            pyautogui.click(pos[0], pos[1], button='middle')
        if gui_log: gui_log(f"{button.upper()} CLICK fallback at {pos}")

def play_drag_event(ev, gui_log=None):
    start = ev.get("start")
    end = ev.get("end")
    button = ev.get("button", "left")
    tpl_info = ev.get("template")

    # find corrected start:
    corrected = None
    tpl_bgr = None
    if tpl_info:
        if isinstance(tpl_info, dict) and tpl_info.get("bgr") is not None:
            try:
                tpl_bgr = np.array(tpl_info["bgr"], dtype=np.uint8)
            except Exception:
                tpl_bgr = None
        elif isinstance(tpl_info, str) and os.path.exists(tpl_info):
            tpl_bgr = load_template_from_file(tpl_info)

    if tpl_bgr is not None:
        # try full then radii
        cx, cy, sc = match_template_search(tpl_bgr, bbox=None)
        if cx is not None:
            corrected = (cx, cy)
        else:
            for r in RETRY_RADII:
                bbox = (start[0]-r, start[1]-r, r*2, r*2)
                cx, cy, sc = match_template_search(tpl_bgr, bbox=bbox)
                if cx is not None:
                    corrected = (cx, cy)
                    break

    if corrected is None:
        # fallback: approximate start by pixel color
        color = get_pixel_color(start[0], start[1])
        corrected = find_color_near_simple(start[0], start[1], color, radius=10)
        if corrected is None:
            logging.warning("play_drag_event: cannot locate start; aborting drag")
            if gui_log: gui_log(f"{button.upper()} DRAG aborted: start not found")
            return

    sx, sy = corrected
    # play samples
    samples = ev.get("samples", [])
    if not samples:
        # fallback: native dragTo
        try:
            pyautogui.moveTo(sx, sy)
            if button == "left":
                pyautogui.mouseDown(button='left')
                pyautogui.dragTo(end[0], end[1], duration=max(0.01, ev.get("duration", 0.2)), button='left')
                pyautogui.mouseUp(button='left')
            elif button == "right":
                pyautogui.mouseDown(button='right')
                pyautogui.dragTo(end[0], end[1], duration=max(0.01, ev.get("duration", 0.2)), button='right')
                pyautogui.mouseUp(button='right')
            elif button == "middle":
                pyautogui.mouseDown(button='middle')
                pyautogui.dragTo(end[0], end[1], duration=max(0.01, ev.get("duration", 0.2)), button='middle')
                pyautogui.mouseUp(button='middle')
            if gui_log: gui_log(f"{button.upper()} DRAG fallback dragTo executed")
            return
        except Exception as e:
            logging.exception("play_drag_event fallback dragTo exception")
            return

    # original start in samples[0]
    orig_x = samples[0]["x"]
    orig_y = samples[0]["y"]

    pyautogui.moveTo(sx, sy)
    
    # Mouse down with correct button
    if button == "left":
        pyautogui.mouseDown(button='left')
    elif button == "right":
        pyautogui.mouseDown(button='right')
    elif button == "middle":
        pyautogui.mouseDown(button='middle')
    
    for s in samples[1:]:
        dx = s["x"] - orig_x
        dy = s["y"] - orig_y
        tx = int(round(sx + dx))
        ty = int(round(sy + dy))
        dt = max(0.001, float(s.get("dt", 0.01)))
        try:
            pyautogui.moveTo(tx, ty, duration=dt)
        except Exception:
            pyautogui.moveTo(tx, ty)
    
    pyautogui.moveTo(end[0], end[1])
    
    # Mouse up with correct button
    if button == "left":
        pyautogui.mouseUp(button='left')
    elif button == "right":
        pyautogui.mouseUp(button='right')
    elif button == "middle":
        pyautogui.mouseUp(button='middle')
    
    if gui_log: gui_log(f"{button.upper()} DRAG executed to {end}")

def play_key_event(ev, gui_log=None):
    """Play keyboard key press/release event"""
    key = ev.get("key")
    event_type = ev.get("type")
    
    if not key:
        return
    
    try:
        # Map special keys to pyautogui format
        key_mapping = {
            'space': 'space',
            'enter': 'enter',
            'tab': 'tab',
            'backspace': 'backspace',
            'esc': 'esc',
            'shift': 'shift',
            'ctrl': 'ctrl',
            'alt': 'alt',
            'cmd': 'win' if sys.platform == 'win32' else 'command',
            'win': 'win',
            'up': 'up',
            'down': 'down',
            'left': 'left',
            'right': 'right',
            'page_up': 'pageup',
            'page_down': 'pagedown',
            'home': 'home',
            'end': 'end',
            'insert': 'insert',
            'delete': 'delete',
            'caps_lock': 'capslock',
            'num_lock': 'numlock',
            'scroll_lock': 'scrolllock',
            'print_screen': 'printscreen',
            'pause': 'pause',
            'f1': 'f1',
            'f2': 'f2',
            'f3': 'f3',
            'f4': 'f4',
            'f5': 'f5',
            'f6': 'f6',
            'f7': 'f7',
            'f8': 'f8',
            'f9': 'f9',
            'f10': 'f10',
            'f11': 'f11',
            'f12': 'f12',
        }
        
        # Convert key to pyautogui format
        if key in key_mapping:
            pyautogui_key = key_mapping[key]
        elif len(key) == 1:  # Single character
            pyautogui_key = key.lower()
        else:
            pyautogui_key = key.lower()
        
        if event_type == "key_press":
            pyautogui.keyDown(pyautogui_key)
            if gui_log: gui_log(f"KEY DOWN: {key}")
        elif event_type == "key_release":
            pyautogui.keyUp(pyautogui_key)
            if gui_log: gui_log(f"KEY UP: {key}")
            
    except Exception as e:
        logging.exception(f"Error playing key event: {key}")
        if gui_log: gui_log(f"Error playing key: {key}")

def find_color_near_simple(x, y, color, radius=10):
    target_r, target_g, target_b = color
    radii = [radius, radius*2, radius*3]
    for rad in radii:
        left = max(0, x-rad)
        top = max(0, y-rad)
        w = rad*2
        h = rad*2
        img = screenshot_region_pil(left, top, w, h)
        if img is None:
            continue
        for dx in range(img.width):
            for dy in range(img.height):
                r,g,b = img.getpixel((dx,dy))
                if abs(r-target_r) <= 4 and abs(g-target_g) <= 4 and abs(b-target_b) <= 4:
                    return (left+dx, top+dy)
    return None

# -----------------------
# Playback controller
# -----------------------
def playback_worker(delay_start, repeat_minutes, status_label, gui_log):
    if delay_start > 0:
        for s in range(delay_start, 0, -1):
            if not getattr(playback_worker, "running", True):
                status_label.config(text="Stopped")
                return
            status_label.config(text=f"Starting in {s}s")
            time.sleep(1)

    while getattr(playback_worker, "running", True):
        status_label.config(text="Playing...")
        snapshot = events.copy()
        for ev in snapshot:
            if not getattr(playback_worker, "running", True):
                break
            try:
                d = ev.get("delay", 0.0)
                if d > 0:
                    time.sleep(d)
                
                if ev["type"] == "click":
                    play_click_event(ev, gui_log=gui_log)
                elif ev["type"] == "drag":
                    play_drag_event(ev, gui_log=gui_log)
                elif ev["type"] in ["key_press", "key_release"]:
                    play_key_event(ev, gui_log=gui_log)
                    
            except Exception:
                logging.exception("Error during playback evt")
        if repeat_minutes <= 0:
            break
        wait = repeat_minutes * 60
        for s in range(wait, 0, -1):
            if not getattr(playback_worker, "running", True):
                break
            status_label.config(text=f"Next in {s}s")
            time.sleep(1)
    status_label.config(text="Ready")
    global playing
    playing = False

# -----------------------
# Compact Mode Window
# -----------------------
class CompactModeWindow:
    def __init__(self, master_app):
        self.master = master_app
        self.window = tk.Toplevel(master_app.root)
        self.window.title("MacroFlow - Compact Mode")
        self.window.geometry("300x150")
        self.window.configure(bg=COLORS["bg"])
        
        # Zawsze na wierzchu
        self.window.attributes("-topmost", True)
        
        # Bez ramek okna
        self.window.overrideredirect(True)
        
        # Przeciągalne okno
        self.window.bind('<Button-1>', self.start_move)
        self.window.bind('<B1-Motion>', self.on_move)
        
        # Nagłówek
        header = tk.Frame(self.window, bg=COLORS["accent"], height=30)
        header.pack(fill=tk.X)
        header.bind('<Button-1>', self.start_move)
        header.bind('<B1-Motion>', self.on_move)
        
        # Tytuł
        title = tk.Label(header, text="⚡ Compact Mode", 
                        bg=COLORS["accent"], fg="white",
                        font=("Segoe UI", 10, "bold"))
        title.pack(side=tk.LEFT, padx=10)
        title.bind('<Button-1>', self.start_move)
        title.bind('<B1-Motion>', self.on_move)
        
        # Przycisk zamknięcia
        close_btn = tk.Button(header, text="✕", 
                             bg=COLORS["accent"], fg="white",
                             font=("Segoe UI", 10, "bold"),
                             borderwidth=0, command=self.close_compact)
        close_btn.pack(side=tk.RIGHT, padx=5)
        
        # Główny obszar z przyciskami
        main_area = tk.Frame(self.window, bg=COLORS["bg"])
        main_area.pack(fill=tk.BOTH, expand=True, padx=10, pady=10)
        
        # Przyciski nagrywania
        record_frame = tk.Frame(main_area, bg=COLORS["bg"])
        record_frame.pack(fill=tk.X, pady=(0, 10))
        
        tk.Label(record_frame, text="Recording:", 
                bg=COLORS["bg"], fg=COLORS["fg"],
                font=("Segoe UI", 9, "bold")).pack(anchor=tk.W)
        
        btn_frame1 = tk.Frame(record_frame, bg=COLORS["bg"])
        btn_frame1.pack(fill=tk.X, pady=5)
        
        self.compact_record_start = tk.Button(btn_frame1,
            text=f"▶ Rec ({HOTKEYS['start_record']})",
            bg=COLORS["accent"], fg="white",
            font=("Segoe UI", 9), borderwidth=0,
            padx=15, pady=8, command=self.master.start_record)
        self.compact_record_start.pack(side=tk.LEFT, padx=2)
        
        self.compact_record_stop = tk.Button(btn_frame1,
            text=f"⏹ Stop ({HOTKEYS['stop_record']})",
            bg=COLORS["error"], fg="white",
            font=("Segoe UI", 9), borderwidth=0,
            padx=15, pady=8, command=self.master.stop_record)
        self.compact_record_stop.pack(side=tk.LEFT, padx=2)
        
        # Przyciski odtwarzania
        play_frame = tk.Frame(main_area, bg=COLORS["bg"])
        play_frame.pack(fill=tk.X)
        
        tk.Label(play_frame, text="Playback:", 
                bg=COLORS["bg"], fg=COLORS["fg"],
                font=("Segoe UI", 9, "bold")).pack(anchor=tk.W)
        
        btn_frame2 = tk.Frame(play_frame, bg=COLORS["bg"])
        btn_frame2.pack(fill=tk.X, pady=5)
        
        self.compact_play_start = tk.Button(btn_frame2,
            text=f"▶ Play ({HOTKEYS['start_play']})",
            bg=COLORS["success"], fg="white",
            font=("Segoe UI", 9), borderwidth=0,
            padx=15, pady=8, command=self.master.start_play)
        self.compact_play_start.pack(side=tk.LEFT, padx=2)
        
        self.compact_play_stop = tk.Button(btn_frame2,
            text=f"⏹ Stop ({HOTKEYS['stop_play']})",
            bg=COLORS["error"], fg="white",
            font=("Segoe UI", 9), borderwidth=0,
            padx=15, pady=8, command=self.master.stop_play)
        self.compact_play_stop.pack(side=tk.LEFT, padx=2)
        
        # Status
        self.compact_status = tk.Label(main_area,
            text="Status: Ready", bg=COLORS["bg"],
            fg=COLORS["fg"], font=("Segoe UI", 8))
        self.compact_status.pack(pady=(10, 0))
        
        # Zmienne do przeciągania
        self.x = 0
        self.y = 0
    
    def start_move(self, event):
        self.x = event.x
        self.y = event.y
    
    def on_move(self, event):
        deltax = event.x - self.x
        deltay = event.y - self.y
        x = self.window.winfo_x() + deltax
        y = self.window.winfo_y() + deltay
        self.window.geometry(f"+{x}+{y}")
    
    def close_compact(self):
        """Zamknij compact mode i wróć do normalnego okna"""
        global compact_mode
        compact_mode = False
        self.window.destroy()
        self.master.root.deiconify()  # Przywróć główne okno
        self.master.root.lift()
        self.master.root.focus_force()
        self.master.log("Compact mode closed")
    
    def update_status(self, text):
        """Aktualizuj status w compact mode"""
        self.compact_status.config(text=f"Status: {text}")
    
    def update_hotkeys(self):
        """Aktualizuj hotkey na przyciskach"""
        self.compact_record_start.config(text=f"▶ Rec ({HOTKEYS['start_record']})")
        self.compact_record_stop.config(text=f"⏹ Stop ({HOTKEYS['stop_record']})")
        self.compact_play_start.config(text=f"▶ Play ({HOTKEYS['start_play']})")
        self.compact_play_stop.config(text=f"⏹ Stop ({HOTKEYS['stop_play']})")

# -----------------------
# GUI: MINIMAL main app with System Tray, Compact Mode and Info Tab
# -----------------------
class MacroFlowMiniApp:
    def __init__(self):
        global _mouse_listener, _keyboard_listener
        self.root = tk.Tk()
        self.root.title(f"{APP_NAME} - {APP_DATA_DIR}")
        self.root.geometry("700x600")
        self.root.configure(bg=COLORS["bg"])
        
        # Zmienna do śledzenia czy okno jest ukryte
        self.hidden_to_tray = False
        self.compact_window = None
        
        # Keyboard recording listener
        self.keyboard_listener = None
        
        # Ustaw ikonę okna
        try:
            # Prosta ikona w pamięci
            self.root.iconphoto(True, tk.PhotoImage(width=16, height=16))
        except:
            pass
        
        # Tab Control
        self.tab_control = ttk.Notebook(self.root)
        
        # Main Tab
        self.main_tab = tk.Frame(self.tab_control, bg=COLORS["bg"])
        self.tab_control.add(self.main_tab, text='Main')
        
        # Settings Tab
        self.settings_tab = tk.Frame(self.tab_control, bg=COLORS["bg"])
        self.tab_control.add(self.settings_tab, text='Settings')
        
        # Info Tab
        self.info_tab = tk.Frame(self.tab_control, bg=COLORS["bg"])
        self.tab_control.add(self.info_tab, text='Info')
        
        self.tab_control.pack(expand=1, fill="both", padx=10, pady=5)
        
        # ========== MAIN TAB CONTENT ==========
        # Header w Main tab
        header_frame = tk.Frame(self.main_tab, bg=COLORS["bg"], height=40)
        header_frame.pack(fill=tk.X, padx=10, pady=5)
        
        tk.Label(header_frame, 
                text="⚡ MacroFlow Mini",
                bg=COLORS["bg"],
                fg=COLORS["accent"],
                font=("Segoe UI", 14, "bold")).pack(side=tk.LEFT)
        
        # Pokazuj ścieżkę danych w statusie dla debugowania
        status_text = f"Status: Ready | Data: {os.path.basename(APP_DATA_DIR)}"
        self.status_label = tk.Label(header_frame,
                                    text=status_text,
                                    bg=COLORS["card"],
                                    fg=COLORS["fg"],
                                    font=("Segoe UI", 9),
                                    padx=10,
                                    pady=3)
        self.status_label.pack(side=tk.RIGHT, padx=5)
        
        # ========== COMPACT MODE BUTTON ==========
        compact_button_frame = tk.Frame(self.main_tab, bg=COLORS["bg"])
        compact_button_frame.pack(fill=tk.X, padx=10, pady=(0, 5))
        
        self.compact_mode_btn = tk.Button(compact_button_frame,
                 text="📱 Compact Mode",
                 bg=COLORS["warning"],
                 fg="white",
                 font=("Segoe UI", 9),
                 borderwidth=0,
                 padx=12,
                 pady=6,
                 command=self.toggle_compact_mode)
        self.compact_mode_btn.pack(side=tk.RIGHT, padx=5)
        
        # ========== RECORDING OPTIONS ==========
        options_frame = tk.Frame(self.main_tab, bg=COLORS["bg"])
        options_frame.pack(fill=tk.X, padx=10, pady=5)
        
        tk.Label(options_frame,
                text="Record:",
                bg=COLORS["bg"],
                fg=COLORS["fg"],
                font=("Segoe UI", 9, "bold")).pack(side=tk.LEFT, padx=(0, 10))
        
        # Checkbox for keyboard recording
        self.record_keys_var = tk.BooleanVar(value=True)
        self.record_keys_check = tk.Checkbutton(options_frame,
                                              text="Keyboard",
                                              variable=self.record_keys_var,
                                              bg=COLORS["bg"],
                                              fg=COLORS["fg"],
                                              selectcolor=COLORS["card"],
                                              activebackground=COLORS["bg"],
                                              activeforeground=COLORS["fg"])
        self.record_keys_check.pack(side=tk.LEFT, padx=5)
        
        # Checkbox for mouse recording
        self.record_mouse_var = tk.BooleanVar(value=True)
        self.record_mouse_check = tk.Checkbutton(options_frame,
                                               text="Mouse",
                                               variable=self.record_mouse_var,
                                               bg=COLORS["bg"],
                                               fg=COLORS["fg"],
                                               selectcolor=COLORS["card"],
                                               activebackground=COLORS["bg"],
                                               activeforeground=COLORS["fg"])
        self.record_mouse_check.pack(side=tk.LEFT, padx=5)
        
        # Checkbox for right mouse button recording
        self.record_right_click_var = tk.BooleanVar(value=True)
        self.record_right_click_check = tk.Checkbutton(options_frame,
                                                      text="Right Click",
                                                      variable=self.record_right_click_var,
                                                      bg=COLORS["bg"],
                                                      fg=COLORS["fg"],
                                                      selectcolor=COLORS["card"],
                                                      activebackground=COLORS["bg"],
                                                      activeforeground=COLORS["fg"])
        self.record_right_click_check.pack(side=tk.LEFT, padx=5)
        
        # ========== COMPACT CONTROLS ==========
        controls_frame = tk.Frame(self.main_tab, bg=COLORS["bg"])
        controls_frame.pack(fill=tk.X, padx=10, pady=5)
        
        # Left control buttons - RECORDING
        left_controls = tk.Frame(controls_frame, bg=COLORS["bg"])
        left_controls.pack(side=tk.LEFT, fill=tk.Y, padx=(0, 20))
        
        # Nagrywanie - górny wiersz
        record_label = tk.Label(left_controls,
                               text="Recording:",
                               bg=COLORS["bg"],
                               fg=COLORS["fg"],
                               font=("Segoe UI", 9, "bold"))
        record_label.pack(anchor=tk.W, pady=(0, 5))
        
        record_buttons = tk.Frame(left_controls, bg=COLORS["bg"])
        record_buttons.pack(fill=tk.X)
        
        self.record_start_btn = tk.Button(record_buttons,
                 text=f"▶ Start Rec ({HOTKEYS['start_record']})",
                 bg=COLORS["accent"],
                 fg="white",
                 font=("Segoe UI", 9),
                 borderwidth=0,
                 padx=12,
                 pady=6,
                 command=self.start_record)
        self.record_start_btn.pack(side=tk.LEFT, padx=2)
        
        self.record_stop_btn = tk.Button(record_buttons,
                 text=f"⏹ Stop Rec ({HOTKEYS['stop_record']})",
                 bg=COLORS["error"],
                 fg="white",
                 font=("Segoe UI", 9),
                 borderwidth=0,
                 padx=12,
                 pady=6,
                 command=self.stop_record)
        self.record_stop_btn.pack(side=tk.LEFT, padx=2)
        
        # PLAYBACK - środkowy wiersz (pod Recording)
        playback_label = tk.Label(left_controls,
                                 text="Playback:",
                                 bg=COLORS["bg"],
                                 fg=COLORS["fg"],
                                 font=("Segoe UI", 9, "bold"))
        playback_label.pack(anchor=tk.W, pady=(10, 5))
        
        playback_buttons = tk.Frame(left_controls, bg=COLORS["bg"])
        playback_buttons.pack(fill=tk.X)
        
        self.play_start_btn = tk.Button(playback_buttons,
                 text=f"▶ Play ({HOTKEYS['start_play']})",
                 bg=COLORS["success"],
                 fg="white",
                 font=("Segoe UI", 9),
                 borderwidth=0,
                 padx=12,
                 pady=6,
                 command=self.start_play)
        self.play_start_btn.pack(side=tk.LEFT, padx=2)
        
        self.play_stop_btn = tk.Button(playback_buttons,
                 text=f"⏹ Stop ({HOTKEYS['stop_play']})",
                 bg=COLORS["error"],
                 fg="white",
                 font=("Segoe UI", 9),
                 borderwidth=0,
                 padx=12,
                 pady=6,
                 command=self.stop_play)
        self.play_stop_btn.pack(side=tk.LEFT, padx=2)
        
        # SETTINGS - dolny wiersz (pod Playback)
        settings_label = tk.Label(left_controls,
                                 text="Settings:",
                                 bg=COLORS["bg"],
                                 fg=COLORS["fg"],
                                 font=("Segoe UI", 9, "bold"))
        settings_label.pack(anchor=tk.W, pady=(10, 5))
        
        settings_frame = tk.Frame(left_controls, bg=COLORS["bg"])
        settings_frame.pack(fill=tk.X)
        
        # Delay setting
        delay_frame = tk.Frame(settings_frame, bg=COLORS["bg"])
        delay_frame.pack(fill=tk.X, pady=2)
        
        tk.Label(delay_frame,
                text="Delay start (s):",
                bg=COLORS["bg"],
                fg=COLORS["fg"],
                font=("Segoe UI", 9),
                width=15,
                anchor=tk.W).pack(side=tk.LEFT)
        
        self.delay_entry = tk.Entry(delay_frame,
                                   width=8,
                                   bg=COLORS["input_bg"],
                                   fg=COLORS["fg"],
                                   insertbackground=COLORS["fg"],
                                   borderwidth=1,
                                   font=("Segoe UI", 9))
        self.delay_entry.insert(5, "5")
        self.delay_entry.pack(side=tk.LEFT, padx=5)
        
        # Repeat setting
        repeat_frame = tk.Frame(settings_frame, bg=COLORS["bg"])
        repeat_frame.pack(fill=tk.X, pady=2)
        
        tk.Label(repeat_frame,
                text="Repeat (min):",
                bg=COLORS["bg"],
                fg=COLORS["fg"],
                font=("Segoe UI", 9),
                width=15,
                anchor=tk.W).pack(side=tk.LEFT)
        
        self.repeat_entry = tk.Entry(repeat_frame,
                                    width=8,
                                    bg=COLORS["input_bg"],
                                    fg=COLORS["fg"],
                                    insertbackground=COLORS["fg"],
                                    borderwidth=1,
                                    font=("Segoe UI", 9))
        self.repeat_entry.insert(0, "0")
        self.repeat_entry.pack(side=tk.LEFT, padx=5)
        
        # Right control buttons (Save/Load)
        right_controls = tk.Frame(controls_frame, bg=COLORS["bg"])
        right_controls.pack(side=tk.RIGHT, fill=tk.Y)
        
        tk.Button(right_controls,
                 text="💾 Save",
                 bg=COLORS["secondary"],
                 fg="white",
                 font=("Segoe UI", 9),
                 borderwidth=0,
                 padx=12,
                 pady=6,
                 command=self.save_file).pack(side=tk.LEFT, padx=2, pady=(0, 10))
        
        tk.Button(right_controls,
                 text="📂 Load",
                 bg=COLORS["secondary"],
                 fg="white",
                 font=("Segoe UI", 9),
                 borderwidth=0,
                 padx=12,
                 pady=6,
                 command=self.load_file).pack(side=tk.LEFT, padx=2, pady=(0, 10))
        
        # ========== COMPACT MAIN AREA ==========
        main_area = tk.Frame(self.main_tab, bg=COLORS["bg"])
        main_area.pack(fill=tk.BOTH, expand=True, padx=10, pady=5)
        
        # Events list
        events_frame = tk.Frame(main_area, bg=COLORS["card"], bd=1, relief="solid")
        events_frame.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        
        tk.Label(events_frame,
                text="Recorded Events",
                bg=COLORS["card"],
                fg=COLORS["accent"],
                font=("Segoe UI", 10, "bold"),
                pady=5).pack(fill=tk.X)
        
        self.events_listbox = tk.Listbox(events_frame,
                                        bg=COLORS["input_bg"],
                                        fg=COLORS["fg"],
                                        selectbackground=COLORS["accent"],
                                        borderwidth=0,
                                        font=("Consolas", 9))
        self.events_listbox.pack(fill=tk.BOTH, expand=True, padx=5, pady=5)
        
        # ========== MINIMAL LOG AREA ==========
        log_frame = tk.Frame(self.main_tab, bg=COLORS["card"], bd=1, relief="solid")
        log_frame.pack(fill=tk.X, padx=10, pady=(5, 10))
        
        tk.Label(log_frame,
                text="Activity Log",
                bg=COLORS["card"],
                fg=COLORS["accent"],
                font=("Segoe UI", 10, "bold"),
                pady=3).pack(fill=tk.X)
        
        self.log_box = scrolledtext.ScrolledText(log_frame,
                                                height=4,
                                                bg=COLORS["input_bg"],
                                                fg=COLORS["fg"],
                                                insertbackground=COLORS["fg"],
                                                borderwidth=0,
                                                font=("Consolas", 8))
        self.log_box.pack(fill=tk.X, padx=5, pady=5)
        
        # ========== SETTINGS TAB CONTENT ==========
        settings_header = tk.Frame(self.settings_tab, bg=COLORS["bg"])
        settings_header.pack(fill=tk.X, padx=10, pady=10)
        
        tk.Label(settings_header,
                text="⚙️ Settings",
                bg=COLORS["bg"],
                fg=COLORS["accent"],
                font=("Segoe UI", 16, "bold")).pack(side=tk.LEFT)
        
        # Hotkey Configuration Section
        hotkey_frame = tk.Frame(self.settings_tab, bg=COLORS["card"], bd=1, relief="solid")
        hotkey_frame.pack(fill=tk.BOTH, expand=True, padx=20, pady=20)
        
        tk.Label(hotkey_frame,
                text="Keyboard Shortcuts",
                bg=COLORS["card"],
                fg=COLORS["accent"],
                font=("Segoe UI", 12, "bold"),
                pady=10).pack(fill=tk.X)
        
        # Hotkey grid
        hotkey_grid = tk.Frame(hotkey_frame, bg=COLORS["card"])
        hotkey_grid.pack(fill=tk.BOTH, expand=True, padx=20, pady=10)
        
        # Start Recording
        row1 = tk.Frame(hotkey_grid, bg=COLORS["card"])
        row1.pack(fill=tk.X, pady=5)
        tk.Label(row1, text="Start Recording:", bg=COLORS["card"], fg=COLORS["fg"], 
                font=("Segoe UI", 10), width=20, anchor=tk.W).pack(side=tk.LEFT)
        self.start_record_var = tk.StringVar(value=HOTKEYS["start_record"])
        self.start_record_entry = tk.Entry(row1, textvariable=self.start_record_var,
                                          bg=COLORS["input_bg"], fg=COLORS["fg"],
                                          font=("Segoe UI", 10), width=15)
        self.start_record_entry.pack(side=tk.LEFT, padx=10)
        tk.Label(row1, text="(Default: F2)", bg=COLORS["card"], fg=COLORS["secondary"],
                font=("Segoe UI", 9)).pack(side=tk.LEFT)
        
        # Stop Recording
        row2 = tk.Frame(hotkey_grid, bg=COLORS["card"])
        row2.pack(fill=tk.X, pady=5)
        tk.Label(row2, text="Stop Recording:", bg=COLORS["card"], fg=COLORS["fg"], 
                font=("Segoe UI", 10), width=20, anchor=tk.W).pack(side=tk.LEFT)
        self.stop_record_var = tk.StringVar(value=HOTKEYS["stop_record"])
        self.stop_record_entry = tk.Entry(row2, textvariable=self.stop_record_var,
                                         bg=COLORS["input_bg"], fg=COLORS["fg"],
                                         font=("Segoe UI", 10), width=15)
        self.stop_record_entry.pack(side=tk.LEFT, padx=10)
        tk.Label(row2, text="(Default: F4)", bg=COLORS["card"], fg=COLORS["secondary"],
                font=("Segoe UI", 9)).pack(side=tk.LEFT)
        
        # Start Playback
        row3 = tk.Frame(hotkey_grid, bg=COLORS["card"])
        row3.pack(fill=tk.X, pady=5)
        tk.Label(row3, text="Start Playback:", bg=COLORS["card"], fg=COLORS["fg"], 
                font=("Segoe UI", 10), width=20, anchor=tk.W).pack(side=tk.LEFT)
        self.start_play_var = tk.StringVar(value=HOTKEYS["start_play"])
        self.start_play_entry = tk.Entry(row3, textvariable=self.start_play_var,
                                        bg=COLORS["input_bg"], fg=COLORS["fg"],
                                        font=("Segoe UI", 10), width=15)
        self.start_play_entry.pack(side=tk.LEFT, padx=10)
        tk.Label(row3, text="(Default: F8)", bg=COLORS["card"], fg=COLORS["secondary"],
                font=("Segoe UI", 9)).pack(side=tk.LEFT)
        
        # Stop Playback
        row4 = tk.Frame(hotkey_grid, bg=COLORS["card"])
        row4.pack(fill=tk.X, pady=5)
        tk.Label(row4, text="Stop Playback:", bg=COLORS["card"], fg=COLORS["fg"], 
                font=("Segoe UI", 10), width=20, anchor=tk.W).pack(side=tk.LEFT)
        self.stop_play_var = tk.StringVar(value=HOTKEYS["stop_play"])
        self.stop_play_entry = tk.Entry(row4, textvariable=self.stop_play_var,
                                       bg=COLORS["input_bg"], fg=COLORS["fg"],
                                       font=("Segoe UI", 10), width=15)
        self.stop_play_entry.pack(side=tk.LEFT, padx=10)
        tk.Label(row4, text="(Default: F10)", bg=COLORS["card"], fg=COLORS["secondary"],
                font=("Segoe UI", 9)).pack(side=tk.LEFT)
        
        # Save Settings Button
        button_frame = tk.Frame(hotkey_frame, bg=COLORS["card"])
        button_frame.pack(fill=tk.X, pady=20)
        
        tk.Button(button_frame,
                 text="💾 Save Settings",
                 bg=COLORS["accent"],
                 fg="white",
                 font=("Segoe UI", 10),
                 borderwidth=0,
                 padx=20,
                 pady=8,
                 command=self.save_settings).pack(pady=5)
        
        tk.Button(button_frame,
                 text="🔄 Reset to Defaults",
                 bg=COLORS["secondary"],
                 fg="white",
                 font=("Segoe UI", 10),
                 borderwidth=0,
                 padx=20,
                 pady=8,
                 command=self.reset_settings).pack(pady=5)
        
        # Info label
        info_label = tk.Label(hotkey_frame,
                             text="Note: Shortcuts will be updated after saving and restarting the application.",
                             bg=COLORS["card"],
                             fg=COLORS["warning"],
                             font=("Segoe UI", 9),
                             wraplength=400,
                             justify=tk.LEFT)
        info_label.pack(pady=10)
        
        # ========== INFO TAB CONTENT ==========
        info_header = tk.Frame(self.info_tab, bg=COLORS["bg"])
        info_header.pack(fill=tk.X, padx=10, pady=10)
        
        tk.Label(info_header,
                text="📖 MacroFlow Mini - User Manual",
                bg=COLORS["bg"],
                fg=COLORS["accent"],
                font=("Segoe UI", 16, "bold")).pack(side=tk.LEFT)
        
        # Main info container with scrollbar
        info_container = tk.Frame(self.info_tab, bg=COLORS["bg"])
        info_container.pack(fill=tk.BOTH, expand=True, padx=10, pady=5)
        
        # Add scrollbar
        scrollbar = tk.Scrollbar(info_container)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        
        # Text widget for instructions
        info_text = tk.Text(info_container,
                          bg=COLORS["card"],
                          fg=COLORS["fg"],
                          font=("Segoe UI", 10),
                          wrap=tk.WORD,
                          padx=15,
                          pady=15,
                          yscrollcommand=scrollbar.set)
        info_text.pack(fill=tk.BOTH, expand=True)
        
        scrollbar.config(command=info_text.yview)
        
        # Insert instructions
        instructions = """
╔══════════════════════════════════════════════════════════════╗
║                  MACROFLOW MINI - USER MANUAL                ║
╚══════════════════════════════════════════════════════════════╝

📌 INTRODUCTION
MacroFlow Mini is a lightweight automation tool that records and replays 
mouse actions (left/right clicks and drags) AND keyboard actions on your computer. 
Perfect for automating repetitive tasks!

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

🎯 QUICK START
1. Select what to record (Keyboard, Mouse, Right Click)
2. Click "▶ Start Rec (F2)" to begin recording
3. Perform your actions (mouse clicks, drags, keyboard typing)
4. Click "⏹ Stop Rec (F4)" when finished
5. Click "▶ Play (F8)" to replay your actions

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

⌨️ KEYBOARD SHORTCUTS
• F2  - Start Recording
• F4  - Stop Recording
• F8  - Start Playback
• F10 - Stop Playback

You can customize these shortcuts in the Settings tab.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

🔧 MAIN FEATURES

📝 RECORDING OPTIONS
• Keyboard - Records key presses and releases
• Mouse - Records left mouse button clicks and drags
• Right Click - Records right mouse button clicks and drags
• All can be enabled/disabled independently

📝 RECORDING DETAILS
• Records left mouse clicks and drags
• Records right mouse clicks and drags (context menu)
• Records keyboard key presses and releases
• Captures delays between actions automatically
• Events are displayed in the "Recorded Events" list

▶️ PLAYBACK
• Replays recorded actions exactly as performed
• Supports delay before start (in seconds)
• Supports repeating playback (in minutes)
• Status is shown in real-time

⚙️ SETTINGS
• Customizable keyboard shortcuts
• Delay before playback start
• Repeat interval for continuous playback

📱 COMPACT MODE
• Click "📱 Compact Mode" for a minimal interface
• Small floating window with 4 main buttons
• Always on top of other windows
• Draggable - move it anywhere on screen
• Close with ✕ to return to normal mode

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

💾 FILE MANAGEMENT

SAVE YOUR MACROS
1. Click "💾 Save" button
2. Choose location and filename
3. Your macro is saved as JSON file
4. Can be loaded later for reuse

LOAD EXISTING MACROS
1. Click "📂 Load" button
2. Select your saved JSON file
3. Macro is loaded and ready to play

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

🔄 PLAYBACK OPTIONS

DELAY START
• Enter number of seconds to wait before playback starts
• Useful when you need time to switch to target application

REPEAT PLAYBACK
• Enter number of minutes between repetitions
• Set to 0 for single playback
• Set to 1+ for continuous looping

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

📊 STATUS INDICATORS
• Ready - Waiting for commands
• Recording - Currently recording mouse/keyboard actions
• Playing... - Playback in progress
• Starting in Xs - Countdown before playback

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

⚠️ TIPS & TROUBLESHOOTING

RECORDING TIPS
1. Record in the actual application where you'll use the macro
2. Include small delays between complex actions
3. Test playback immediately after recording
4. Save your macros with descriptive names
5. For keyboard recording, ensure correct keyboard layout
6. Right-click recording is perfect for context menus

PLAYBACK TIPS
1. Ensure target application is visible and focused
2. Adjust delay if needed for application loading
3. Use compact mode for quick access during work
4. For keyboard playback, ensure correct input language
5. Right-click playback works for opening context menus

COMMON ISSUES
• If playback doesn't work, check if target window is active
• For drag operations, ensure start position is visible
• If hotkeys don't work, check keyboard focus
• Keyboard recording might not work in some secure applications
• Right-click might not work in applications that block automation

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

🔧 SYSTEM TRAY
• Click "📌 Minimize to Tray" to hide to system tray
• Right-click tray icon for quick options
• "Show MacroFlow" - Restore main window
• "Compact Mode" - Switch to compact mode
• "Exit" - Close the application

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

📞 SUPPORT
• Check activity log for detailed information
• Logs are saved to: macroflow_mini.log
• Macros are saved as JSON files
• Settings are saved to: macroflow_settings.json

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

🎉 GETTING STARTED EXAMPLE

1. OPEN TARGET APPLICATION
   Open the program where you want to automate tasks

2. RECORD A SIMPLE MACRO
   • Enable Keyboard, Mouse, and Right Click recording
   • Click "▶ Start Rec (F2)"
   • Type some text in your application
   • Right-click to open a context menu
   • Select an option from the menu
   • Click "⏹ Stop Rec (F4)"

3. TEST PLAYBACK
   • Click "▶ Play (F8)"
   • Watch the macro execute keyboard, left-click and right-click actions

4. SAVE FOR LATER USE
   • Click "💾 Save"
   • Name it "MyFirstMacro.json"

Now you have a reusable automation!

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

Enjoy automating with MacroFlow Mini! 🚀
"""
        
        info_text.insert(tk.END, instructions)
        info_text.config(state=tk.DISABLED)  # Make read-only
        
        # ========== KEYBOARD LISTENERS ==========
        self.k_listener = keyboard.Listener(on_press=self._on_key_press)
        self.k_listener.start()
        
        _mouse_listener = mouse.Listener(on_move=_on_move, on_click=_on_click)
        _mouse_listener.start()
        
        # ========== SYSTEM TRAY SETUP ==========
        self.setup_system_tray()
        
        # ========== MINIMIZE TO TRAY BUTTON ==========
        # Dodaj przycisk do minimalizacji do tray
        tray_button_frame = tk.Frame(self.main_tab, bg=COLORS["bg"])
        tray_button_frame.pack(fill=tk.X, padx=10, pady=(0, 5))
        
        tk.Button(tray_button_frame,
                 text="📌 Minimize to Tray",
                 bg=COLORS["secondary"],
                 fg="white",
                 font=("Segoe UI", 9),
                 borderwidth=0,
                 padx=12,
                 pady=4,
                 command=self.hide_to_tray_func).pack(side=tk.RIGHT, padx=5)
        
        # ========== REFRESH UI ==========
        self.root.after(400, self._refresh_ui)
        self.play_thread = None
        
        # Wczytaj ustawienia przy starcie
        self.load_settings()
        
        # Obsługa zamknięcia okna - minimalizuj do tray zamiast zamykać
        self.root.protocol("WM_DELETE_WINDOW", self.hide_to_tray_func)
        
        # Timer do aktualizacji statusu w compact mode
        self.root.after(1000, self._update_compact_status)

    def toggle_compact_mode(self):
        """Przełącz między trybem normalnym a compact"""
        global compact_mode
        
        if not compact_mode:
            self.enter_compact_mode()
        else:
            self.exit_compact_mode()
    
    def enter_compact_mode(self):
        """Wejdź w tryb compact"""
        global compact_mode
        
        # Ukryj główne okno
        self.root.withdraw()
        
        # Utwórz okno compact mode
        self.compact_window = CompactModeWindow(self)
        
        # Ustaw pozycję (prawy górny róg)
        screen_width = self.root.winfo_screenwidth()
        screen_height = self.root.winfo_screenheight()
        window_width = 220
        window_height = 220
        x = screen_width - window_width - 20
        y = 20
        self.compact_window.window.geometry(f"{window_width}x{window_height}+{x}+{y}")
        
        compact_mode = True
        self.log("Entered compact mode")
    
    def exit_compact_mode(self):
        """Wyjdź z trybu compact"""
        global compact_mode
        
        if self.compact_window:
            self.compact_window.close_compact()
            self.compact_window = None
        
        compact_mode = False
    
    def _update_compact_status(self):
        """Aktualizuj status w compact mode"""
        if compact_mode and self.compact_window:
            # Pobierz aktualny status z głównego okna
            current_status = self.status_label.cget("text").replace("Status: ", "")
            self.compact_window.update_status(current_status)
        
        # Uruchom ponownie po sekundzie
        self.root.after(1000, self._update_compact_status)

    def setup_keyboard_recording(self):
        """Setup keyboard listener for recording"""
        if self.keyboard_listener:
            self.keyboard_listener.stop()
        
        # Start keyboard listener for recording
        self.keyboard_listener = keyboard.Listener(
            on_press=_on_key_press_record,
            on_release=_on_key_release_record
        )
        self.keyboard_listener.start()
    
    def stop_keyboard_recording(self):
        """Stop keyboard recording listener"""
        if self.keyboard_listener:
            self.keyboard_listener.stop()
            self.keyboard_listener = None

    def setup_system_tray(self):
        """Utwórz ikonę w system tray"""
        try:
            # Import pystray jeśli dostępny
            try:
                import pystray
                from PIL import Image, ImageDraw
                
                # Stwórz prostą ikonę
                def create_image():
                    # Utwórz obrazek 64x64 z niebieskim kółkiem
                    image = Image.new('RGB', (64, 64), color=(74, 158, 255))
                    draw = ImageDraw.Draw(image)
                    draw.ellipse([10, 10, 54, 54], fill=(255, 255, 255))
                    return image
                
                # Menu dla system tray
                menu = pystray.Menu(
                    pystray.MenuItem('Show MacroFlow', self.show_from_tray),
                    pystray.MenuItem('Compact Mode', self.enter_compact_mode),
                    pystray.MenuItem('Exit', self.exit_app)
                )
                
                # Utwórz ikonę
                image = create_image()
                self.tray_icon = pystray.Icon("macroflow", image, "MacroFlow Mini", menu)
                
                # Uruchom w osobnym wątku
                tray_thread = threading.Thread(target=self.tray_icon.run, daemon=True)
                tray_thread.start()
                
                self.log("System tray icon created")
                
            except ImportError:
                self.log("pystray not installed. Run: pip install pystray")
                # Fallback: prosty system tray bez pystray
                self.tray_icon = None
                
        except Exception as e:
            self.log(f"System tray setup error: {str(e)}")
            self.tray_icon = None

    def hide_to_tray_func(self):
        """Ukryj okno do system tray"""
        if hasattr(self, 'tray_icon') and self.tray_icon:
            self.root.withdraw()  # Ukryj okno
            self.hidden_to_tray = True
            self.log("Minimized to system tray")
        else:
            # Jeśli nie ma system tray, po prostu minimalizuj
            self.root.iconify()
            self.log("Minimized to taskbar")

    def show_from_tray(self):
        """Pokaż okno z system tray"""
        self.root.deiconify()  # Przywróć okno
        self.root.lift()       # Na wierzch
        self.root.focus_force() # Daj fokus
        self.hidden_to_tray = False
        self.log("Restored from system tray")

    def exit_app(self):
        """Zamknij aplikację całkowicie"""
        if hasattr(self, 'tray_icon') and self.tray_icon:
            self.tray_icon.stop()
        self.on_close()

    def save_settings(self):
        """Zapisz ustawienia skrótów klawiszowych"""
        global HOTKEYS
        
        new_hotkeys = {
            "start_record": self.start_record_var.get().strip().upper() or "F2",
            "stop_record": self.stop_record_var.get().strip().upper() or "F4",
            "start_play": self.start_play_var.get().strip().upper() or "F8",
            "stop_play": self.stop_play_var.get().strip().upper() or "F10"
        }
        
        # Sprawdź czy skróty są unikalne
        hotkey_values = list(new_hotkeys.values())
        if len(hotkey_values) != len(set(hotkey_values)):
            messagebox.showerror("Error", "Hotkeys must be unique!")
            return
        
        # Aktualizuj globalne hotkeys
        HOTKEYS.update(new_hotkeys)
        
        # Aktualizuj przyciski w Main tab
        self.record_start_btn.config(text=f"▶ Start Rec ({HOTKEYS['start_record']})")
        self.record_stop_btn.config(text=f"⏹ Stop Rec ({HOTKEYS['stop_record']})")
        self.play_start_btn.config(text=f"▶ Play ({HOTKEYS['start_play']})")
        self.play_stop_btn.config(text=f"⏹ Stop ({HOTKEYS['stop_play']})")
        
        # Aktualizuj przyciski w compact mode jeśli istnieje
        if self.compact_window:
            self.compact_window.update_hotkeys()
        
        # Zapisz do pliku w katalogu danych aplikacji
        try:
            settings_file = os.path.join(APP_DATA_DIR, "macroflow_settings.json")
            with open(settings_file, "w") as f:
                json.dump(HOTKEYS, f, indent=2)
            self.log(f"Settings saved successfully to {settings_file}")
            messagebox.showinfo("Success", f"Settings saved to {settings_file}")
        except Exception as e:
            messagebox.showerror("Error", f"Failed to save settings: {str(e)}")

    def reset_settings(self):
        """Resetuj ustawienia do domyślnych"""
        self.start_record_var.set("F2")
        self.stop_record_var.set("F4")
        self.start_play_var.set("F8")
        self.stop_play_var.set("F10")
        self.log("Settings reset to defaults")

    def load_settings(self):
        """Wczytaj ustawienia z pliku"""
        global HOTKEYS
        try:
            # Spróbuj najpierw z katalogu danych aplikacji
            settings_file_app = os.path.join(APP_DATA_DIR, "macroflow_settings.json")
            settings_file_local = "macroflow_settings.json"
            
            if os.path.exists(settings_file_app):
                with open(settings_file_app, "r") as f:
                    saved_settings = json.load(f)
                    HOTKEYS.update(saved_settings)
                    self.log(f"Loaded settings from {settings_file_app}")
            elif os.path.exists(settings_file_local):
                with open(settings_file_local, "r") as f:
                    saved_settings = json.load(f)
                    HOTKEYS.update(saved_settings)
                    self.log(f"Loaded settings from {settings_file_local}")
            
            # Aktualizuj pola w Settings tab
            self.start_record_var.set(HOTKEYS.get("start_record", "F2"))
            self.stop_record_var.set(HOTKEYS.get("stop_record", "F4"))
            self.start_play_var.set(HOTKEYS.get("start_play", "F8"))
            self.stop_play_var.set(HOTKEYS.get("stop_play", "F10"))
            
        except Exception as e:
            self.log(f"Failed to load settings: {str(e)}")

    def _on_key_press(self, key):
        """Obsługa skrótów klawiszowych (działa gdy aplikacja ma fokus)"""
        try:
            key_str = None
            try:
                key_str = key.char.upper() if key.char else None
            except AttributeError:
                # Dla klawiszy funkcyjnych
                if hasattr(key, 'name'):
                    key_str = key.name.upper()
                else:
                    key_str = str(key).replace("Key.", "").upper()
            
            if not key_str:
                return
                
            # Sprawdź skróty
            if key_str == HOTKEYS["start_record"].upper():
                self.start_record()
            elif key_str == HOTKEYS["stop_record"].upper():
                self.stop_record()
            elif key_str == HOTKEYS["start_play"].upper():
                self.start_play()
            elif key_str == HOTKEYS["stop_play"].upper():
                self.stop_play()
                
        except Exception as e:
            logging.exception("Error in _on_key_press")

    def log(self, text):
        logging.info(text)
        self.log_box.insert(tk.END, f"{datetime.now().strftime('%H:%M:%S')} - {text}\n")
        self.log_box.see(tk.END)

    def _refresh_ui(self):
        try:
            # events
            self.events_listbox.delete(0, tk.END)
            for i, e in enumerate(events):
                if e["type"] == "click":
                    self.events_listbox.insert(tk.END, f"{i}: CLICK pos={e['pos']}")
                elif e["type"] == "drag":
                    self.events_listbox.insert(tk.END, f"{i}: DRAG {e['start']}->{e['end']}")
                elif e["type"] == "key_press":
                    self.events_listbox.insert(tk.END, f"{i}: KEY PRESS: {e['key']}")
                elif e["type"] == "key_release":
                    self.events_listbox.insert(tk.END, f"{i}: KEY RELEASE: {e['key']}")
        except Exception:
            pass
        self.root.after(400, self._refresh_ui)

    def start_record(self):
        global recording, events, last_event_time
        
        # Check if at least one recording option is selected
        if not self.record_keys_var.get() and not self.record_mouse_var.get():
            messagebox.showwarning("Warning", "Please select at least one recording option (Keyboard or Mouse)")
            return
        
        events.clear()
        recording = True
        last_event_time = None
        
        # Setup keyboard recording if enabled
        if self.record_keys_var.get():
            self.setup_keyboard_recording()
            self.log("Keyboard recording enabled")
        else:
            self.stop_keyboard_recording()
        
        self.status_label.config(text="Status: Recording")
        # Aktualizuj status w compact mode jeśli jest aktywny
        if compact_mode and self.compact_window:
            self.compact_window.update_status("Recording")
        
        options = []
        if self.record_keys_var.get():
            options.append("Keyboard")
        if self.record_mouse_var.get():
            options.append("Mouse")
        
        self.log(f"Recording started (Hotkey: {HOTKEYS['start_record']}) - Recording: {', '.join(options)}")

    def stop_record(self):
        global recording
        
        # Stop keyboard recording listener
        self.stop_keyboard_recording()
        
        recording = False
        self.status_label.config(text="Status: Ready")
        # Aktualizuj status w compact mode jeśli jest aktywny
        if compact_mode and self.compact_window:
            self.compact_window.update_status("Ready")
        self.log(f"Recording stopped; events={len(events)} (Hotkey: {HOTKEYS['stop_record']})")

    def start_play(self):
        global playing, _playback_thread
        if playing:
            self.log("Already playing")
            return
        try:
            delay = int(self.delay_entry.get())
        except Exception:
            delay = 0
        try:
            repeat = int(self.repeat_entry.get())
        except Exception:
            repeat = 0
        playing = True
        playback_worker.running = True
        _playback_thread = threading.Thread(target=playback_worker, 
                                           args=(delay, repeat, self.status_label, self.log), 
                                           daemon=True)
        _playback_thread.start()
        self.status_label.config(text="Status: Playing...")
        # Aktualizuj status w compact mode jeśli jest aktywny
        if compact_mode and self.compact_window:
            self.compact_window.update_status("Playing...")
        self.log(f"Playback started (Hotkey: {HOTKEYS['start_play']})")

    def stop_play(self):
        playback_worker.running = False
        global playing
        playing = False
        self.status_label.config(text="Status: Ready")
        # Aktualizuj status w compact mode jeśli jest aktywny
        if compact_mode and self.compact_window:
            self.compact_window.update_status("Ready")
        self.log(f"Playback stopped (Hotkey: {HOTKEYS['stop_play']})")

    def save_file(self):
        # Domyślnie zapisuj w katalogu danych aplikacji
        default_dir = APP_DATA_DIR
        default_file = os.path.join(default_dir, DATA_FILE)
        
        fname = filedialog.asksaveasfilename(
            defaultextension=".json", 
            initialfile=os.path.basename(default_file),
            initialdir=default_dir
        )
        if not fname:
            return
        export = []
        for e in events:
            ee = dict(e)
            # Usuwamy template z zapisu
            if "template" in ee:
                del ee["template"]
            export.append(ee)
        try:
            with open(fname, "w", encoding="utf-8") as fh:
                json.dump(export, fh, indent=2)
            self.log(f"Saved events to {fname}")
        except Exception as e:
            messagebox.showerror("Save error", str(e))

    def load_file(self):
        # Zacznij od katalogu danych aplikacji
        initial_dir = APP_DATA_DIR if os.path.exists(APP_DATA_DIR) else "."
        
        fname = filedialog.askopenfilename(
            initialdir=initial_dir,
            filetypes=[("JSON", "*.json"), ("All", "*.*")]
        )
        if not fname:
            return
        try:
            with open(fname, "r", encoding="utf-8") as fh:
                data = json.load(fh)
            global events
            events = data
            self.log(f"Loaded events from {fname}")
        except Exception as e:
            messagebox.showerror("Load error", str(e))

    def on_close(self):
        """Zamknij aplikację całkowicie"""
        try:
            self.k_listener.stop()
        except Exception:
            pass
        try:
            _mouse_listener.stop()
        except Exception:
            pass
        # Stop keyboard recording if active
        self.stop_keyboard_recording()
        
        playback_worker.running = False
        if hasattr(self, 'tray_icon') and self.tray_icon:
            self.tray_icon.stop()
        if self.compact_window:
            self.compact_window.window.destroy()
        self.root.quit()
        self.root.destroy()

# -----------------------
# Main
# -----------------------
def main():
    global APP
    APP = MacroFlowMiniApp()
    APP.root.mainloop()

if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        logging.exception("Fatal error in main")
        print(f"Fatal error. See log: {LOG_FILE}")
        print(f"Error details: {str(e)}")
        sys.exit(1)
