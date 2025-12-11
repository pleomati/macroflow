#!/usr/bin/env python3
# MacroFlow Mini - HYBRID VERSION with Algorithm A & B
# Supports switching between algorithms in Settings

import os
import sys
import time
import json
import threading
import logging
import queue
from datetime import datetime
from math import floor

import pyautogui
from pynput import mouse, keyboard
from PIL import Image, ImageGrab
import numpy as np
import cv2
import tkinter as tk
from tkinter import ttk, filedialog, messagebox, scrolledtext

# ==================== ALGORITHM A IMPORTS & SETUP ====================
import keyboard as kb  # For global hooks in Algorithm A

# ==================== FIX FOR APPMAGE/ONEFILE ====================
def setup_appimage_paths():
    """Set correct paths for AppImage/OneFile"""
    is_frozen = getattr(sys, 'frozen', False)
    has_appdir = 'APPDIR' in os.environ
    
    if is_frozen or has_appdir:
        home_dir = os.path.expanduser("~")
        app_data_dir = os.path.join(home_dir, ".macroflow")
        os.makedirs(app_data_dir, exist_ok=True)
        
        return {
            "log_file": os.path.join(app_data_dir, "macroflow_hybrid.log"),
            "data_file": os.path.join(app_data_dir, "macroflow_hybrid.json"),
            "template_dir": os.path.join(app_data_dir, "templates_hybrid"),
            "app_data_dir": app_data_dir,
            "is_appimage": True
        }
    else:
        return {
            "log_file": "macroflow_hybrid.log",
            "data_file": "macroflow_hybrid.json",
            "template_dir": "templates_hybrid",
            "app_data_dir": ".",
            "is_appimage": False
        }

PATHS = setup_appimage_paths()

# ==================== CONFIGURATION ====================
APP_NAME = "MacroFlow Hybrid"
LOG_FILE = PATHS["log_file"]
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

# ==================== COLOR SCHEME ====================
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

# ==================== LOGGING ====================
def setup_logging():
    """Configure logging with error handling"""
    try:
        log_dir = os.path.dirname(LOG_FILE)
        if log_dir and not os.path.exists(log_dir):
            os.makedirs(log_dir, exist_ok=True)
        
        logging.basicConfig(
            filename=LOG_FILE, 
            level=logging.INFO,
            format="%(asctime)s - %(levelname)s - %(message)s",
            filemode='a'
        )
        
        if PATHS["is_appimage"]:
            console_handler = logging.StreamHandler()
            console_handler.setLevel(logging.INFO)
            formatter = logging.Formatter('%(asctime)s - %(levelname)s - %(message)s')
            console_handler.setFormatter(formatter)
            logging.getLogger().addHandler(console_handler)
            print(f"AppImage mode: Logging to {LOG_FILE}")
        
        logging.info("=== MacroFlow Hybrid start ===")
        logging.info(f"AppImage mode: {PATHS['is_appimage']}")
        logging.info(f"Data directory: {APP_DATA_DIR}")
        
    except Exception as e:
        logging.basicConfig(level=logging.INFO)
        logging.error(f"Cannot configure file logging: {e}")
        print(f"Log setup error: {e}")
        print(f"Using fallback logging to console")

setup_logging()

# ==================== ALGORITHM A GLOBALS ====================
# Recording
events_a = []
recording_a = False
last_event_time_a = None

# Drag helpers
drag_in_progress_a = False
drag_start_pos_a = None
drag_start_time_a = None
drag_samples_a = []
drag_color_a = None

# Listeners
mouse_listener_a = None
hotkeys_registered_a = False
current_hotkeys_a = {}

# Thread-safe queue for mouse samples
mouse_queue_a = queue.Queue()

# Default shortcuts for Algorithm A
DEFAULT_SHORTCUTS_A = {
    "start_recording": "f2",
    "stop_recording": "f4",
    "start_playback": "f8",
    "stop_playback": "f9",
    "always_on_top": "f11",
    "show_settings": "f12"
}

# ==================== ALGORITHM B GLOBALS ====================
# Muszą być zadeklarowane PRZED użyciem w funkcjach
events_b = []
recording_b = False
playing_b = False  # TU jest deklaracja - PRZED funkcjami
last_event_time_b = None

# drag state
_dragging_b = False
_drag_start_b = None
_drag_start_time_b = None
_drag_samples_b = []
_drag_button_b = None

# template store
templates = []

# threading control
_playback_thread_b = None

# listeners
_mouse_listener_b = None
_keyboard_listener_b = None

# Hotkey configuration for Algorithm B
HOTKEYS_B = {
    "start_record": "F2",
    "stop_record": "F4", 
    "start_play": "F8",
    "stop_play": "F10"
}

# ==================== SHARED GLOBALS ====================
compact_mode = False
compact_window = None
APP = None

# Ensure template dir exists
os.makedirs(TEMPLATE_DIR, exist_ok=True)

print(f"=== MacroFlow Hybrid Configuration ===")
print(f"LOG_FILE: {LOG_FILE}")
print(f"DATA_FILE: {DATA_FILE}")
print(f"TEMPLATE_DIR: {TEMPLATE_DIR}")
print(f"Is AppImage: {PATHS['is_appimage']}")
print(f"===============================")

# ==================== ALGORITHM A FUNCTIONS ====================
def load_config_a():
    """Load configuration for Algorithm A"""
    config = {
        "shortcuts": DEFAULT_SHORTCUTS_A.copy(),
        "always_on_top": False,
        "window_position": None,
        "delay_start": 300,
        "repeat_minutes": 0
    }
    
    try:
        config_file = os.path.join(APP_DATA_DIR, "macro_config_a.json")
        if os.path.exists(config_file):
            with open(config_file, 'r') as f:
                saved_config = json.load(f)
                if "shortcuts" in saved_config:
                    config["shortcuts"].update(saved_config["shortcuts"])
                config.update({k: v for k, v in saved_config.items() if k != "shortcuts"})
            logging.info("Algorithm A configuration loaded from file")
    except Exception as e:
        logging.exception(f"Error loading Algorithm A config: {e}")
    
    return config

def save_config_a(config):
    """Save Algorithm A configuration"""
    try:
        config_file = os.path.join(APP_DATA_DIR, "macro_config_a.json")
        with open(config_file, 'w') as f:
            json.dump(config, f, indent=4)
        logging.info("Algorithm A configuration saved")
        return True
    except Exception as e:
        logging.exception(f"Error saving Algorithm A config: {e}")
        return False

def get_pixel_color_a(x, y):
    """Algorithm A: Get pixel color at coordinates"""
    try:
        img = ImageGrab.grab(bbox=(int(x), int(y), int(x)+1, int(y)+1))
        return img.getpixel((0, 0))
    except Exception as e:
        logging.exception(f"get_pixel_color_a error: {e}")
        return (0, 0, 0)

def find_color_near_a(x, y, color, radius=15):
    """Algorithm A: Windows optimized color search"""
    target_r, target_g, target_b = color
    search_radii = [radius, radius*2, radius*3, 60, 100]

    for rad in search_radii:
        try:
            bbox = (
                max(0, int(x)-rad),
                max(0, int(y)-rad),
                int(x)+rad,
                int(y)+rad
            )
            img = ImageGrab.grab(bbox=bbox)
        except Exception as e:
            continue

        w, h = img.size
        tolerance = 10 if rad <= radius else 15 if rad <= 60 else 20
        
        for dx in range(0, w, 2):
            for dy in range(0, h, 2):
                r, g, b = img.getpixel((dx, dy))
                if (abs(r-target_r) <= tolerance and
                    abs(g-target_g) <= tolerance and
                    abs(b-target_b) <= tolerance):
                    return (bbox[0] + dx, bbox[1] + dy)
    return None

def mouse_sampler_thread_a():
    """Algorithm A: Thread sampling mouse position during drag"""
    global drag_in_progress_a, drag_samples_a
    
    last_sample_time = time.time()
    min_sample_interval = 0.005  # 5ms między próbkami
    
    while True:
        try:
            if not drag_in_progress_a:
                time.sleep(0.01)
                continue
            
            current_time = time.time()
            # Pobierz najnowszą pozycję z kolejki
            try:
                pos = mouse_queue_a.get_nowait()
                mouse_queue_a.queue.clear()  # Wyczyść starą kolejkę
            except queue.Empty:
                # Jeśli nie ma nowych pozycji, spróbuj pobrać aktualną
                try:
                    import pyautogui
                    pos = pyautogui.position()
                except:
                    time.sleep(0.001)
                    continue
            
            # Dodaj próbkę tylko jeśli minęło wystarczająco czasu
            if current_time - last_sample_time >= min_sample_interval:
                drag_samples_a.append({
                    "pos": pos,
                    "timestamp": current_time
                })
                last_sample_time = current_time
                
        except Exception as e:
            logging.exception(f"mouse_sampler_thread_a error: {e}")
            time.sleep(0.01)

def on_move_a(x, y):
    """Algorithm A: Mouse movement handler"""
    global recording_a, drag_in_progress_a
    if recording_a and drag_in_progress_a:
        mouse_queue_a.put((int(x), int(y)))

def on_click_a(x, y, button, pressed):
    """Algorithm A: Mouse click handler (left button only)"""
    global recording_a, events_a, drag_in_progress_a, drag_start_pos_a
    global drag_start_time_a, drag_samples_a, drag_color_a, last_event_time_a
    
    try:
        if button != mouse.Button.left:
            return
        
        if not recording_a:
            return
        
        now = time.time()
        x, y = int(x), int(y)
        
        if pressed:
            # Rozpoczynamy nasłuchiwanie - może być kliknięciem lub przeciągnięciem
            drag_in_progress_a = True
            drag_start_pos_a = (x, y)
            drag_start_time_a = now
            drag_samples_a = []
            drag_color_a = get_pixel_color_a(x, y)
            
            # Dodaj pierwszą próbkę
            drag_samples_a.append({
                "pos": (x, y),
                "timestamp": now
            })
            
            logging.debug(f"Algorithm A: Mouse PRESS at {x}, {y}")
            return
        
        # Obsługa puszczenia przycisku (release)
        if drag_in_progress_a:
            # Dodajemy końcową pozycję
            drag_samples_a.append({
                "pos": (x, y),
                "timestamp": now
            })
            
            # Oblicz czas trwania
            duration = max(0.001, now - drag_start_time_a)
            
            # Oblicz opóźnienie od poprzedniego eventu
            if last_event_time_a is None:
                delay = 0.0
            else:
                delay = max(0.0, now - last_event_time_a)
            
            # SPRAWDZENIE CZY TO JEST KLIK CZY DRAG
            # Obliczamy odległość między punktem początkowym a końcowym
            start_x, start_y = drag_start_pos_a
            dx = abs(x - start_x)
            dy = abs(y - start_y)
            distance = (dx**2 + dy**2)**0.5
            
            # DEBUG: logujemy parametry dla analizy
            logging.debug(f"Algorithm A click/drag analysis:")
            logging.debug(f"  Duration: {duration:.3f}s")
            logging.debug(f"  Distance: {distance:.1f}px")
            logging.debug(f"  Samples: {len(drag_samples_a)}")
            logging.debug(f"  Start: {drag_start_pos_a}")
            logging.debug(f"  End: ({x}, {y})")
            
            # Parametry do rozróżniania kliknięcia od przeciągnięcia
            # Możesz je dostosować w zależności od potrzeb:
            CLICK_MAX_DURATION = 0.2      # Maks. czas dla kliknięcia (sekundy)
            CLICK_MAX_DISTANCE = 8         # Maks. odległość dla kliknięcia (piksele)
            MIN_DRAG_SAMPLES = 4           # Min. próbek dla przeciągnięcia
            
            # Rozróżnienie kliknięcia od przeciągnięcia
            is_click = (duration < CLICK_MAX_DURATION and      # krótki czas
                       distance < CLICK_MAX_DISTANCE) #and      # mała odległość
                       #len(drag_samples_a) < MIN_DRAG_SAMPLES)  # mało próbek
            
            if is_click:
                # To jest kliknięcie
                evt = {
                    "type": "click",
                    "pos": (x, y),
                    "color": drag_color_a,
                    "timestamp": now,
                    "delay": delay
                }
                logging.info(f"Algorithm A: CLICK recorded at {x}, {y} "
                           f"(duration: {duration:.3f}s, distance: {distance:.1f}px)")
            else:
                # To jest przeciągnięcie
                
                # OPTYMALIZACJA: Filtruj zduplikowane próbki
                unique_samples = []
                last_unique_pos = None
                for sample in drag_samples_a:
                    if last_unique_pos is None or sample["pos"] != last_unique_pos:
                        unique_samples.append(sample)
                        last_unique_pos = sample["pos"]
                
                # Jeśli po filtracji mamy za mało próbek, dodajmy start i end
                if len(unique_samples) < 2:
                    unique_samples = [drag_samples_a[0], drag_samples_a[-1]]
                
                evt = {
                    "type": "drag",
                    "start": drag_start_pos_a,
                    "end": (x, y),
                    "color": drag_color_a,
                    "timestamp": drag_start_time_a,
                    "delay": delay,
                    "duration": duration,
                    "samples": unique_samples,  # Używamy unikalnych próbek
                    "sample_count": len(unique_samples),
                    "original_sample_count": len(drag_samples_a),  # Dla diagnostyki
                    "distance": distance  # Dodajemy odległość dla debugowania
                }
                
                logging.info(f"Algorithm A: DRAG recorded:")
                logging.info(f"  Samples: {len(unique_samples)}/{len(drag_samples_a)}")
                logging.info(f"  Distance: {distance:.1f}px")
                logging.info(f"  Duration: {duration:.3f}s")
                logging.info(f"  Path: {drag_start_pos_a} -> ({x}, {y})")
            
            # Dodaj event do listy
            events_a.append(evt)
            last_event_time_a = now
            
            # Reset stanu drag
            drag_in_progress_a = False
            drag_start_pos_a = None
            drag_start_time_a = None
            drag_samples_a = []
            drag_color_a = None
            return
        
        # TEN BLOK KODU POWINIEN BYĆ RZADKO OSIĄGANY
        # (tylko jeśli coś poszło nie tak z drag_in_progress_a)
        logging.warning(f"Algorithm A: Unexpected click handling at {x}, {y}")
        
        if last_event_time_a is None:
            delay = 0.0
        else:
            delay = max(0.0, now - last_event_time_a)
        
        evt = {
            "type": "click",
            "pos": (x, y),
            "color": get_pixel_color_a(x, y),
            "timestamp": now,
            "delay": delay
        }
        events_a.append(evt)
        logging.warning(f"Algorithm A: Fallback CLICK recorded at {x}, {y}")
        last_event_time_a = now
        
    except Exception as e:
        logging.exception(f"on_click_a error: {e}")
        # Reset stanu w przypadku błędu
        drag_in_progress_a = False
        drag_start_pos_a = None
        drag_start_time_a = None
        drag_samples_a = []
        drag_color_a = None

def execute_in_main_thread(func):
    """Execute function in the main Tkinter thread"""
    if APP and APP.root:
        APP.root.after(0, func)

def start_global_keyboard_hooks_a(app_instance, shortcuts_config):
    """Algorithm A: Start global keyboard hooks"""
    global hotkeys_registered_a, current_hotkeys_a
    
    if hotkeys_registered_a:
        stop_global_keyboard_hooks_a()
    
    logging.info("Algorithm A: Registering global keyboard hotkeys...")
    
    try:
        current_hotkeys_a = {}
        
        # Start recording
        hotkey = shortcuts_config.get("start_recording", "f2")
        current_hotkeys_a["start_recording"] = hotkey
        kb.add_hotkey(hotkey, lambda: execute_in_main_thread(app_instance.start_record))
        
        # Stop recording
        hotkey = shortcuts_config.get("stop_recording", "f4")
        current_hotkeys_a["stop_recording"] = hotkey
        kb.add_hotkey(hotkey, lambda: execute_in_main_thread(app_instance.stop_record))
        
        # Start playback
        hotkey = shortcuts_config.get("start_playback", "f8")
        current_hotkeys_a["start_playback"] = hotkey
        kb.add_hotkey(hotkey, lambda: execute_in_main_thread(app_instance.start_play))
        
        # Stop playback
        hotkey = shortcuts_config.get("stop_playback", "f9")
        current_hotkeys_a["stop_playback"] = hotkey
        kb.add_hotkey(hotkey, lambda: execute_in_main_thread(app_instance.stop_play))
        
        hotkeys_registered_a = True
        logging.info(f"Algorithm A: Global keyboard hotkeys registered: {current_hotkeys_a}")
        
    except Exception as e:
        logging.exception(f"Algorithm A: Error registering hotkeys: {e}")
        messagebox.showerror("Hotkey Error", 
                           f"Cannot register hotkeys: {str(e)}\n"
                           f"Make sure hotkeys are not already in use.")

def stop_global_keyboard_hooks_a():
    """Algorithm A: Remove all global keyboard hotkeys"""
    global hotkeys_registered_a, current_hotkeys_a
    try:
        kb.unhook_all_hotkeys()
        current_hotkeys_a = {}
        hotkeys_registered_a = False
        logging.info("Algorithm A: Global keyboard hotkeys unregistered")
    except Exception as e:
        logging.exception(f"Algorithm A: Error stopping keyboard hooks: {e}")

def start_listeners_a():
    """Algorithm A: Start both mouse and keyboard listeners"""
    global mouse_listener_a
    if mouse_listener_a is None:
        mouse_listener_a = mouse.Listener(on_click=on_click_a, on_move=on_move_a)
        mouse_listener_a.start()
        logging.info("Algorithm A: Mouse listener started")
    
    # Start mouse sampler thread
    sampler_thread = threading.Thread(target=mouse_sampler_thread_a, daemon=True)
    sampler_thread.start()

def play_click_a(event, gui_log=None):
    """Algorithm A: Play click event"""
    x, y = event["pos"]
    corrected = find_color_near_a(x, y, event["color"], radius=15)
    if corrected is None:
        pyautogui.click(x, y)
        if gui_log: gui_log(f"ALG A: CLICK fallback at {x},{y}")
        return
    pyautogui.click(corrected[0], corrected[1])
    if gui_log: gui_log(f"ALG A: CLICK corrected to {corrected}")

def play_drag_a(event, gui_log=None):
    """Algorithm A: Play drag event with precise shape reproduction"""
    # Pobierz próbki z eventu
    original_samples = event.get("samples", [])
    if not original_samples or len(original_samples) < 2:
        if gui_log: gui_log("ALG A: DRAG aborted - no samples")
        return
    
    # Przetwórz próbki dla lepszego odtwarzania
    samples = preprocess_samples_a(original_samples)
    if len(samples) < 2:
        samples = original_samples  # Fallback
    
    start_pos = samples[0]["pos"]
    
    # Znajdź skorygowaną pozycję startową
    corrected = find_color_near_a(start_pos[0], start_pos[1], event["color"], radius=15)
    if corrected is None:
        corrected = start_pos
        if gui_log: gui_log(f"ALG A: DRAG start color not found, using original position")
    
    cx, cy = corrected
    
    try:
        # 1. Przenieś mysz do punktu startowego (płynnie)
        pyautogui.moveTo(cx, cy, duration=0.15, tween=pyautogui.easeOutQuad)
        time.sleep(0.03)
        
        # 2. Naciśnij przycisk myszy
        pyautogui.mouseDown()
        time.sleep(0.02)
        
        # 3. Odtwórz ścieżkę z próbek
        if len(samples) >= 3:
            # Używamy próbek dla dokładnego kształtu
            prev_x, prev_y = cx, cy
            
            for i in range(1, len(samples)):
                sample = samples[i]
                orig_dx = sample["pos"][0] - start_pos[0]
                orig_dy = sample["pos"][1] - start_pos[1]
                target_x = cx + orig_dx
                target_y = cy + orig_dy
                
                # Oblicz odległość do pokonania
                move_dist = ((target_x - prev_x)**2 + (target_y - prev_y)**2)**0.5
                
                if move_dist > 0:
                    # Oblicz czas między próbkami
                    if i > 0:
                        time_diff = sample["timestamp"] - samples[i-1]["timestamp"]
                        # Dostosuj czas ruchu w zależności od odległości
                        base_duration = max(0.001, time_diff)
                        # Szybszy ruch dla krótszych dystansów
                        move_duration = min(0.1, base_duration * (move_dist / max(1, move_dist)))
                        
                        # Użyj odpowiedniej krzywej ruchu
                        if move_dist < 10:
                            tween_func = pyautogui.easeOutQuad
                        else:
                            tween_func = pyautogui.easeInOutQuad
                        
                        pyautogui.moveTo(
                            target_x, 
                            target_y, 
                            duration=move_duration,
                            tween=tween_func
                        )
                    else:
                        pyautogui.moveTo(target_x, target_y)
                    
                    prev_x, prev_y = target_x, target_y
        else:
            # Dla bardzo krótkich dragów
            end_pos = samples[-1]["pos"]
            orig_dx = end_pos[0] - start_pos[0]
            orig_dy = end_pos[1] - start_pos[1]
            target_x = cx + orig_dx
            target_y = cy + orig_dy
            
            duration = max(0.15, min(1.0, event.get("duration", 0.3)))
            pyautogui.dragTo(
                target_x, 
                target_y, 
                duration=duration, 
                button='left',
                tween=pyautogui.easeInOutQuad
            )
        
        # 4. Zwolnij przycisk myszy
        time.sleep(0.02)
        pyautogui.mouseUp()
        
        if gui_log: 
            gui_log(f"ALG A: DRAG executed {len(samples)}/{len(original_samples)} samples")
        
    except Exception as e:
        logging.exception(f"ALG A: PLAY DRAG error: {e}")
        try:
            pyautogui.mouseUp()  # Upewnij się, że przycisk jest puszczony
        except:
            pass
            
def preprocess_samples_a(samples):
    """Wygladź próbki dla lepszego odtwarzania"""
    if len(samples) < 3:
        return samples
    
    processed = []
    # Zawsze dodaj pierwszą próbkę
    processed.append(samples[0])
    
    for i in range(1, len(samples)-1):
        current = samples[i]
        prev = samples[i-1]
        next_sample = samples[i+1]
        
        # Proste wygładzanie - średnia z trzech sąsiednich punktów
        if (abs(current["pos"][0] - prev["pos"][0]) > 20 or 
            abs(current["pos"][1] - prev["pos"][1]) > 20):
            # Pomiń duże skoki (prawdopodobnie błąd próbkowania)
            continue
        
        avg_x = (prev["pos"][0] + current["pos"][0] + next_sample["pos"][0]) // 3
        avg_y = (prev["pos"][1] + current["pos"][1] + next_sample["pos"][1]) // 3
        
        processed.append({
            "pos": (avg_x, avg_y),
            "timestamp": current["timestamp"]
        })
    
    # Dodaj ostatnią próbkę
    processed.append(samples[-1])
    
    return processed
    
def playback_once_a(events_list, gui_log=None):
    """Algorithm A: Playback recorded events once"""
    if not events_list:
        return
    
    start_time = time.time()
    
    for evt in events_list:
        try:
            event_time = evt.get("timestamp", 0)
            delay = evt.get("delay", 0)
            
            elapsed = time.time() - start_time
            target_time = event_time - events_list[0].get("timestamp", 0)
            
            if elapsed < target_time:
                time.sleep(target_time - elapsed)
            
            if evt["type"] == "click":
                play_click_a(evt, gui_log=gui_log)
            elif evt["type"] == "drag":
                play_drag_a(evt, gui_log=gui_log)
            
            time.sleep(0.01)
            
        except Exception as e:
            logging.exception(f"ALG A: playback_once error on event {evt}: {e}")

# ==================== ALGORITHM B FUNCTIONS ====================
def pil_to_cv2(img_pil):
    """Algorithm B: Convert PIL image to OpenCV format"""
    arr = np.array(img_pil)
    if arr.ndim == 2:
        return arr
    return cv2.cvtColor(arr, cv2.COLOR_RGB2BGR)

def screenshot_full_pil():
    """Algorithm B: Take full screenshot"""
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
    """Algorithm B: Take screenshot of region"""
    try:
        return ImageGrab.grab(bbox=(left, top, left + w, top + h))
    except Exception as e:
        logging.exception("screenshot_region_pil error")
        try:
            return pyautogui.screenshot(region=(left, top, w, h))
        except Exception:
            return None

def get_pixel_color_b(x, y):
    """Algorithm B: Get pixel color"""
    try:
        im = screenshot_region_pil(x, y, 1, 1)
        if im is None:
            return (0,0,0)
        return im.getpixel((0,0))
    except Exception as e:
        logging.exception("get_pixel_color_b error")
        return (0,0,0)

def load_template_from_file(path):
    """Algorithm B: Load template from file"""
    try:
        im = Image.open(path).convert("RGB")
        bgr = cv2.cvtColor(np.array(im), cv2.COLOR_RGB2BGR)
        return bgr
    except Exception as e:
        logging.exception("load_template_from_file error")
        return None

def match_template_search(template_bgr, bbox=None, threshold=TEMPLATE_MATCH_THRESH):
    """Algorithm B: Search template on screen"""
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

def _on_move_b(x, y):
    """Algorithm B: Mouse movement handler"""
    global recording_b, _dragging_b, _drag_samples_b
    try:
        if recording_b and _dragging_b:
            _drag_samples_b.append({"x": int(x), "y": int(y), "t": time.perf_counter()})
    except Exception:
        logging.exception("_on_move_b error (ignored)")

def _on_click_b(x, y, button, pressed):
    """Algorithm B: Mouse click handler (all buttons)"""
    global recording_b, events_b, last_event_time_b
    global _dragging_b, _drag_start_b, _drag_start_time_b, _drag_samples_b, _drag_button_b

    if not recording_b:
        return

    now = time.time()
    try:
        if pressed:
            # Rozpoczynamy nasłuchiwanie - MOŻE być początkiem drag lub click
            _dragging_b = True
            _drag_start_b = (int(x), int(y))
            _drag_start_time_b = now
            _drag_samples_b = [{"x": int(x), "y": int(y), "t": time.perf_counter()}]
            _drag_button_b = button
            logging.info(f"Algorithm B: Record {button} press at {_drag_start_b}")
            return

        # release
        if _dragging_b and button == _drag_button_b:
            _drag_samples_b.append({"x": int(x), "y": int(y), "t": time.perf_counter()})
            duration = max(0.0, now - (_drag_start_time_b or now))
            
            if last_event_time_b is None:
                delay = 0.0
            else:
                delay = max(0.0, now - last_event_time_b)

            # Determine button name
            button_name = "left"
            if button == mouse.Button.right:
                button_name = "right"
            elif button == mouse.Button.middle:
                button_name = "middle"

            # SPRAWDZENIE CZY TO JEST KLIK CZY DRAG
            # Warunki dla kliknięcia (nie przeciągnięcia):
            # 1. Krótki czas (np. < 0.2 sekundy)
            # 2. Mała odległość (np. < 5 pikseli)
            # 3. Mało próbek ruchu
            
            dx = abs(x - _drag_start_b[0])
            dy = abs(y - _drag_start_b[1])
            distance = (dx**2 + dy**2)**0.5
            
            is_click = (duration < 0.2 and  # krótki czas
                       distance < 5 and     # mała odległość
                       len(_drag_samples_b) < 5)  # mało próbek
            
            if is_click:
                # To jest kliknięcie
                ev = {
                    "type": "click",
                    "pos": (int(x), int(y)),
                    "button": button_name,
                    "timestamp": now,
                    "delay": delay,
                    "template": None
                }
                logging.info(f"Algorithm B: Recorded {button_name.upper()} CLICK at {(x,y)}")
            else:
                # To jest przeciągnięcie
                # normalize dt deltas
                normalized = []
                prev_t = _drag_samples_b[0]["t"]
                for s in _drag_samples_b:
                    dt = s["t"] - prev_t
                    normalized.append({"x": int(s["x"]), "y": int(s["y"]), "dt": float(dt)})
                    prev_t = s["t"]
                ev = {
                    "type": "drag",
                    "start": (_drag_start_b[0], _drag_start_b[1]),
                    "end": (int(x), int(y)),
                    "button": button_name,
                    "timestamp": now,
                    "delay": delay,
                    "duration": duration,
                    "samples": normalized,
                    "template": None
                }
                logging.info(f"Algorithm B: Recorded {button_name.upper()} DRAG {ev['start']} -> {ev['end']}")

            events_b.append(ev)
            last_event_time_b = now

            # reset drag state
            _dragging_b = False
            _drag_start_b = None
            _drag_start_time_b = None
            _drag_samples_b = []
            _drag_button_b = None
    except Exception:
        logging.exception("_on_click_b error")

def _on_key_press_record_b(key):
    """Algorithm B: Handle keyboard key press during recording"""
    global recording_b, events_b, last_event_time_b
    
    if not recording_b:
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
        if key_name.lower() in ['f2', 'f4', 'f8', 'f10']:
            return
        
        # Calculate delay
        delay = 0.0 if last_event_time_b is None else max(0.0, now - last_event_time_b)
        
        # Create key press event
        ev = {
            "type": "key_press",
            "key": key_name,
            "timestamp": now,
            "delay": delay
        }
        
        events_b.append(ev)
        last_event_time_b = now
        logging.info(f"Algorithm B: Recorded KEY PRESS: {key_name}")
        
    except Exception:
        logging.exception("Error in _on_key_press_record_b")

def _on_key_release_record_b(key):
    """Algorithm B: Handle keyboard key release during recording"""
    global recording_b, events_b
    
    if not recording_b:
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
        if key_name.lower() in ['f2', 'f4', 'f8', 'f10']:
            return
        
        # Create key release event
        ev = {
            "type": "key_release",
            "key": key_name,
            "timestamp": now,
            "delay": 0.0
        }
        
        events_b.append(ev)
        logging.info(f"Algorithm B: Recorded KEY RELEASE: {key_name}")
        
    except Exception:
        logging.exception("Error in _on_key_release_record_b")

def find_color_near_simple(x, y, color, radius=10):
    """Algorithm B: Simple color search"""
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

def play_click_event_b(ev, gui_log=None):
    """Algorithm B: Play click event"""
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
                if gui_log: gui_log(f"ALG B: {button.upper()} CLICK matched at {cx},{cy} score={sc:.3f}")
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
                        if gui_log: gui_log(f"ALG B: {button.upper()} CLICK matched near pos at {cx},{cy} score={sc:.3f}")
                        return
    # fallback to raw pos
    if pos:
        if button == "left":
            pyautogui.click(pos[0], pos[1])
        elif button == "right":
            pyautogui.click(pos[0], pos[1], button='right')
        elif button == "middle":
            pyautogui.click(pos[0], pos[1], button='middle')
        if gui_log: gui_log(f"ALG B: {button.upper()} CLICK fallback at {pos}")

def play_drag_event_b(ev, gui_log=None):
    """Algorithm B: Play drag event"""
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
        color = get_pixel_color_b(start[0], start[1])
        corrected = find_color_near_simple(start[0], start[1], color, radius=10)
        if corrected is None:
            logging.warning("ALG B: play_drag_event: cannot locate start; aborting drag")
            if gui_log: gui_log(f"ALG B: {button.upper()} DRAG aborted: start not found")
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
            if gui_log: gui_log(f"ALG B: {button.upper()} DRAG fallback dragTo executed")
            return
        except Exception as e:
            logging.exception("ALG B: play_drag_event fallback dragTo exception")
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
    
    if gui_log: gui_log(f"ALG B: {button.upper()} DRAG executed to {end}")

def play_key_event_b(ev, gui_log=None):
    """Algorithm B: Play keyboard event"""
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
        elif len(key) == 1:
            pyautogui_key = key.lower()
        else:
            pyautogui_key = key.lower()
        
        if event_type == "key_press":
            pyautogui.keyDown(pyautogui_key)
            if gui_log: gui_log(f"ALG B: KEY DOWN: {key}")
        elif event_type == "key_release":
            pyautogui.keyUp(pyautogui_key)
            if gui_log: gui_log(f"ALG B: KEY UP: {key}")
            
    except Exception as e:
        logging.exception(f"ALG B: Error playing key event: {key}")
        if gui_log: gui_log(f"ALG B: Error playing key: {key}")

# ==================== EVENT CONVERSION FUNCTIONS ====================
def convert_a_to_b_events(events_a_list):
    """Convert Algorithm A events to Algorithm B format"""
    events_b_list = []
    for evt_a in events_a_list:
        if evt_a["type"] == "click":
            evt_b = {
                "type": "click",
                "pos": evt_a["pos"],
                "button": "left",
                "timestamp": evt_a["timestamp"],
                "delay": evt_a["delay"],
                "template": None
            }
        elif evt_a["type"] == "drag":
            # Convert samples format
            samples_b = []
            if "samples" in evt_a and evt_a["samples"]:
                prev_time = evt_a["samples"][0]["timestamp"]
                for sample in evt_a["samples"]:
                    dt = sample["timestamp"] - prev_time
                    samples_b.append({
                        "x": sample["pos"][0],
                        "y": sample["pos"][1],
                        "dt": float(dt)
                    })
                    prev_time = sample["timestamp"]
            
            evt_b = {
                "type": "drag",
                "start": evt_a["start"],
                "end": evt_a["end"],
                "button": "left",
                "timestamp": evt_a["timestamp"],
                "delay": evt_a["delay"],
                "duration": evt_a.get("duration", 0.5),
                "samples": samples_b,
                "template": None
            }
        events_b_list.append(evt_b)
    return events_b_list

def convert_b_to_a_events(events_b_list):
    """Convert Algorithm B events to Algorithm A format"""
    events_a_list = []
    for evt_b in events_b_list:
        # Only convert left button events for Algorithm A
        if evt_b.get("button") != "left":
            continue
            
        if evt_b["type"] == "click":
            evt_a = {
                "type": "click",
                "pos": evt_b["pos"],
                "color": get_pixel_color_a(*evt_b["pos"]),
                "timestamp": evt_b["timestamp"],
                "delay": evt_b["delay"]
            }
            events_a_list.append(evt_a)
        elif evt_b["type"] == "drag":
            # Convert samples format
            samples_a = []
            if "samples" in evt_b and evt_b["samples"]:
                for sample in evt_b["samples"]:
                    samples_a.append({
                        "pos": (sample["x"], sample["y"]),
                        "timestamp": evt_b["timestamp"]  # Approximate
                    })
            
            evt_a = {
                "type": "drag",
                "start": evt_b["start"],
                "end": evt_b["end"],
                "color": get_pixel_color_a(*evt_b["start"]),
                "timestamp": evt_b["timestamp"],
                "delay": evt_b["delay"],
                "duration": evt_b.get("duration", 0.5),
                "samples": samples_a,
                "sample_count": len(samples_a)
            }
            events_a_list.append(evt_a)
    return events_a_list

# ==================== PLAYBACK WORKER ====================
def playback_worker(delay_start, repeat_minutes, status_label, gui_log, algorithm="B"):
    """Unified playback worker for both algorithms"""
    global playing_b  # MUSI BYĆ NA SAMYM POCZĄTKU funkcji!
    
    if delay_start > 0:
        for s in range(delay_start, 0, -1):
            if not getattr(playback_worker, "running", True):
                status_label.config(text="Stopped")
                return
            status_label.config(text=f"Starting in {s}s")
            time.sleep(1)

    while getattr(playback_worker, "running", True):
        status_label.config(text="Playing...")
        
        if algorithm == "A":
            # Use Algorithm A playback
            snapshot = events_a.copy()
            sorted_events = sorted(snapshot, key=lambda x: x.get("timestamp", 0))
            
            start_time = time.time()
            for evt in sorted_events:
                if not getattr(playback_worker, "running", True):
                    break
                
                try:
                    event_time = evt.get("timestamp", 0)
                    delay = evt.get("delay", 0)
                    
                    elapsed = time.time() - start_time
                    target_time = event_time - sorted_events[0].get("timestamp", 0)
                    
                    if elapsed < target_time:
                        time.sleep(target_time - elapsed)
                    
                    if evt["type"] == "click":
                        play_click_a(evt, gui_log=gui_log)
                    elif evt["type"] == "drag":
                        play_drag_a(evt, gui_log=gui_log)
                    
                    time.sleep(0.01)
                    
                except Exception as e:
                    logging.exception(f"ALG A playback error: {e}")
                    
        else:
            # Use Algorithm B playback
            snapshot = events_b.copy()
            for ev in snapshot:
                if not getattr(playback_worker, "running", True):
                    break
                try:
                    d = ev.get("delay", 0.0)
                    if d > 0:
                        time.sleep(d)
                    
                    if ev["type"] == "click":
                        play_click_event_b(ev, gui_log=gui_log)
                    elif ev["type"] == "drag":
                        play_drag_event_b(ev, gui_log=gui_log)
                    elif ev["type"] in ["key_press", "key_release"]:
                        play_key_event_b(ev, gui_log=gui_log)
                        
                except Exception:
                    logging.exception("Error during ALG B playback evt")
        
        if repeat_minutes <= 0:
            break
        wait = repeat_minutes * 60
        for s in range(wait, 0, -1):
            if not getattr(playback_worker, "running", True):
                break
            status_label.config(text=f"Next in {s}s")
            time.sleep(1)
    
    status_label.config(text="Ready")
    playing_b = False  # To przypisanie jest OK, bo jest PO deklaracji global

# ==================== COMPACT MODE WINDOW ====================
class CompactModeWindow:
    def __init__(self, master_app):
        self.master = master_app
        self.window = tk.Toplevel(master_app.root)
        self.window.title("MacroFlow - Compact Mode")
        self.window.geometry("300x150")
        self.window.configure(bg=COLORS["bg"])
        
        self.window.attributes("-topmost", True)
        self.window.overrideredirect(True)
        
        self.window.bind('<Button-1>', self.start_move)
        self.window.bind('<B1-Motion>', self.on_move)
        
        header = tk.Frame(self.window, bg=COLORS["accent"], height=30)
        header.pack(fill=tk.X)
        header.bind('<Button-1>', self.start_move)
        header.bind('<B1-Motion>', self.on_move)
        
        title = tk.Label(header, text="⚡ Compact Mode", 
                        bg=COLORS["accent"], fg="white",
                        font=("Segoe UI", 10, "bold"))
        title.pack(side=tk.LEFT, padx=10)
        title.bind('<Button-1>', self.start_move)
        title.bind('<B1-Motion>', self.on_move)
        
        close_btn = tk.Button(header, text="✕", 
                             bg=COLORS["accent"], fg="white",
                             font=("Segoe UI", 10, "bold"),
                             borderwidth=0, command=self.close_compact)
        close_btn.pack(side=tk.RIGHT, padx=5)
        
        main_area = tk.Frame(self.window, bg=COLORS["bg"])
        main_area.pack(fill=tk.BOTH, expand=True, padx=10, pady=10)
        
        record_frame = tk.Frame(main_area, bg=COLORS["bg"])
        record_frame.pack(fill=tk.X, pady=(0, 10))
        
        tk.Label(record_frame, text="Recording:", 
                bg=COLORS["bg"], fg=COLORS["fg"],
                font=("Segoe UI", 9, "bold")).pack(anchor=tk.W)
        
        btn_frame1 = tk.Frame(record_frame, bg=COLORS["bg"])
        btn_frame1.pack(fill=tk.X, pady=5)
        
        self.compact_record_start = tk.Button(btn_frame1,
            text=f"▶ Rec",
            bg=COLORS["accent"], fg="white",
            font=("Segoe UI", 9), borderwidth=0,
            padx=15, pady=8, command=self.master.start_record)
        self.compact_record_start.pack(side=tk.LEFT, padx=2)
        
        self.compact_record_stop = tk.Button(btn_frame1,
            text=f"⏹ Stop",
            bg=COLORS["error"], fg="white",
            font=("Segoe UI", 9), borderwidth=0,
            padx=15, pady=8, command=self.master.stop_record)
        self.compact_record_stop.pack(side=tk.LEFT, padx=2)
        
        play_frame = tk.Frame(main_area, bg=COLORS["bg"])
        play_frame.pack(fill=tk.X)
        
        tk.Label(play_frame, text="Playback:", 
                bg=COLORS["bg"], fg=COLORS["fg"],
                font=("Segoe UI", 9, "bold")).pack(anchor=tk.W)
        
        btn_frame2 = tk.Frame(play_frame, bg=COLORS["bg"])
        btn_frame2.pack(fill=tk.X, pady=5)
        
        self.compact_play_start = tk.Button(btn_frame2,
            text=f"▶ Play",
            bg=COLORS["success"], fg="white",
            font=("Segoe UI", 9), borderwidth=0,
            padx=15, pady=8, command=self.master.start_play)
        self.compact_play_start.pack(side=tk.LEFT, padx=2)
        
        self.compact_play_stop = tk.Button(btn_frame2,
            text=f"⏹ Stop",
            bg=COLORS["error"], fg="white",
            font=("Segoe UI", 9), borderwidth=0,
            padx=15, pady=8, command=self.master.stop_play)
        self.compact_play_stop.pack(side=tk.LEFT, padx=2)
        
        self.compact_status = tk.Label(main_area,
            text="Status: Ready", bg=COLORS["bg"],
            fg=COLORS["fg"], font=("Segoe UI", 8))
        self.compact_status.pack(pady=(10, 0))
        
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
        global compact_mode
        compact_mode = False
        self.window.destroy()
        self.master.root.deiconify()
        self.master.root.lift()
        self.master.root.focus_force()
        self.master.log("Compact mode closed")
    
    def update_status(self, text):
        self.compact_status.config(text=f"Status: {text}")
    
    def update_hotkeys(self):
        """Update hotkey labels"""
        algorithm = self.master.current_algorithm
        if algorithm == "A":
            hotkeys = self.master.config_a["shortcuts"]
            self.compact_record_start.config(text=f"▶ Rec ({hotkeys['start_recording'].upper()})")
            self.compact_record_stop.config(text=f"⏹ Stop ({hotkeys['stop_recording'].upper()})")
            self.compact_play_start.config(text=f"▶ Play ({hotkeys['start_playback'].upper()})")
            self.compact_play_stop.config(text=f"⏹ Stop ({hotkeys['stop_playback'].upper()})")
        else:
            hotkeys = HOTKEYS_B
            self.compact_record_start.config(text=f"▶ Rec ({hotkeys['start_record']})")
            self.compact_record_stop.config(text=f"⏹ Stop ({hotkeys['stop_record']})")
            self.compact_play_start.config(text=f"▶ Play ({hotkeys['start_play']})")
            self.compact_play_stop.config(text=f"⏹ Stop ({hotkeys['stop_play']})")

# ==================== MAIN APPLICATION ====================
class MacroFlowHybridApp:
    def __init__(self):
        global APP
        APP = self
        
        self.root = tk.Tk()
        self.root.title(f"{APP_NAME} - Hybrid")
        self.root.geometry("600x750")
        self.root.configure(bg=COLORS["bg"])
        
        self.hidden_to_tray = False
        self.compact_window = None
        
        # Algorithm selection
        self.current_algorithm = "B"  # Default to Algorithm B
        self.config_a = load_config_a()
        
        # Keyboard recording listener for Algorithm B
        self.keyboard_listener_b = None
        
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
        
        # Initialize UI
        self.create_main_tab()
        self.create_settings_tab()
        self.create_info_tab()
        
        # Start listeners for Algorithm A
        start_listeners_a()
        
        # Start listeners for Algorithm B
        self.start_listeners_b()
        
        # Keyboard listeners for hotkeys
        self.k_listener = keyboard.Listener(on_press=self._on_key_press)
        self.k_listener.start()
        
        # System tray
        self.setup_system_tray()
        
        # Refresh UI
        self.root.after(400, self._refresh_ui)
        self.play_thread = None
        
        # Load settings
        self.load_settings()
        
        # Handle window close
        self.root.protocol("WM_DELETE_WINDOW", self.hide_to_tray_func)
        
        # Timer for compact mode status
        self.root.after(1000, self._update_compact_status)
        
        # Update UI based on algorithm
        self.update_algorithm_ui()

    def start_listeners_b(self):
        """Start Algorithm B listeners"""
        global _mouse_listener_b
        if _mouse_listener_b is None:
            _mouse_listener_b = mouse.Listener(on_click=_on_click_b, on_move=_on_move_b)
            _mouse_listener_b.start()
            logging.info("Algorithm B: Mouse listener started")

    def create_main_tab(self):
        """Create main tab content"""
        # Header
        header_frame = tk.Frame(self.main_tab, bg=COLORS["bg"], height=40)
        header_frame.pack(fill=tk.X, padx=10, pady=5)
        
        tk.Label(header_frame, 
                text="⚡ MacroFlow Hybrid",
                bg=COLORS["bg"],
                fg=COLORS["accent"],
                font=("Segoe UI", 14, "bold")).pack(side=tk.LEFT)
        
        self.status_label = tk.Label(header_frame,
                                    text="Status: Ready | Algorithm: B",
                                    bg=COLORS["card"],
                                    fg=COLORS["fg"],
                                    font=("Segoe UI", 9),
                                    padx=10,
                                    pady=3)
        self.status_label.pack(side=tk.RIGHT, padx=5)
        
        # Compact mode button
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
        
        # Algorithm info
        algo_info_frame = tk.Frame(self.main_tab, bg=COLORS["card"], bd=1, relief="solid")
        algo_info_frame.pack(fill=tk.X, padx=10, pady=5)
        
        self.algo_info_label = tk.Label(algo_info_frame,
                                       text="Current: Algorithm B (Advanced)",
                                       bg=COLORS["card"],
                                       fg=COLORS["success"],
                                       font=("Segoe UI", 9, "bold"))
        self.algo_info_label.pack(pady=5)
        
        # Recording options (Algorithm B only)
        self.options_frame = tk.Frame(self.main_tab, bg=COLORS["bg"])
        self.options_frame.pack(fill=tk.X, padx=10, pady=5)
        
        tk.Label(self.options_frame,
                text="Record (Algorithm B only):",
                bg=COLORS["bg"],
                fg=COLORS["fg"],
                font=("Segoe UI", 9, "bold")).pack(side=tk.LEFT, padx=(0, 10))
        
        self.record_keys_var = tk.BooleanVar(value=True)
        self.record_keys_check = tk.Checkbutton(self.options_frame,
                                              text="Keyboard",
                                              variable=self.record_keys_var,
                                              bg=COLORS["bg"],
                                              fg=COLORS["fg"],
                                              selectcolor=COLORS["card"],
                                              activebackground=COLORS["bg"],
                                              activeforeground=COLORS["fg"])
        self.record_keys_check.pack(side=tk.LEFT, padx=5)
        
        self.record_mouse_var = tk.BooleanVar(value=True)
        self.record_mouse_check = tk.Checkbutton(self.options_frame,
                                               text="Mouse",
                                               variable=self.record_mouse_var,
                                               bg=COLORS["bg"],
                                               fg=COLORS["fg"],
                                               selectcolor=COLORS["card"],
                                              activebackground=COLORS["bg"],
                                              activeforeground=COLORS["fg"])
        self.record_mouse_check.pack(side=tk.LEFT, padx=5)
        
        self.record_right_click_var = tk.BooleanVar(value=True)
        self.record_right_click_check = tk.Checkbutton(self.options_frame,
                                                      text="Right Click",
                                                      variable=self.record_right_click_var,
                                                      bg=COLORS["bg"],
                                                      fg=COLORS["fg"],
                                                      selectcolor=COLORS["card"],
                                                      activebackground=COLORS["bg"],
                                                      activeforeground=COLORS["fg"])
        self.record_right_click_check.pack(side=tk.LEFT, padx=5)
        
        # Controls
        controls_frame = tk.Frame(self.main_tab, bg=COLORS["bg"])
        controls_frame.pack(fill=tk.X, padx=10, pady=5)
        
        # Left control buttons
        left_controls = tk.Frame(controls_frame, bg=COLORS["bg"])
        left_controls.pack(side=tk.LEFT, fill=tk.Y, padx=(0, 20))
        
        # Recording
        record_label = tk.Label(left_controls,
                               text="Recording:",
                               bg=COLORS["bg"],
                               fg=COLORS["fg"],
                               font=("Segoe UI", 9, "bold"))
        record_label.pack(anchor=tk.W, pady=(0, 5))
        
        record_buttons = tk.Frame(left_controls, bg=COLORS["bg"])
        record_buttons.pack(fill=tk.X)
        
        self.record_start_btn = tk.Button(record_buttons,
                 text=f"▶ Start Rec",
                 bg=COLORS["accent"],
                 fg="white",
                 font=("Segoe UI", 9),
                 borderwidth=0,
                 padx=12,
                 pady=6,
                 command=self.start_record)
        self.record_start_btn.pack(side=tk.LEFT, padx=2)
        
        self.record_stop_btn = tk.Button(record_buttons,
                 text=f"⏹ Stop Rec",
                 bg=COLORS["error"],
                 fg="white",
                 font=("Segoe UI", 9),
                 borderwidth=0,
                 padx=12,
                 pady=6,
                 command=self.stop_record)
        self.record_stop_btn.pack(side=tk.LEFT, padx=2)
        
        # Playback
        playback_label = tk.Label(left_controls,
                                 text="Playback:",
                                 bg=COLORS["bg"],
                                 fg=COLORS["fg"],
                                 font=("Segoe UI", 9, "bold"))
        playback_label.pack(anchor=tk.W, pady=(10, 5))
        
        playback_buttons = tk.Frame(left_controls, bg=COLORS["bg"])
        playback_buttons.pack(fill=tk.X)
        
        self.play_start_btn = tk.Button(playback_buttons,
                 text=f"▶ Play",
                 bg=COLORS["success"],
                 fg="white",
                 font=("Segoe UI", 9),
                 borderwidth=0,
                 padx=12,
                 pady=6,
                 command=self.start_play)
        self.play_start_btn.pack(side=tk.LEFT, padx=2)
        
        self.play_stop_btn = tk.Button(playback_buttons,
                 text=f"⏹ Stop",
                 bg=COLORS["error"],
                 fg="white",
                 font=("Segoe UI", 9),
                 borderwidth=0,
                 padx=12,
                 pady=6,
                 command=self.stop_play)
        self.play_stop_btn.pack(side=tk.LEFT, padx=2)
        
        # Settings
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
        self.delay_entry.insert(0, "5")
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
        
        # Events list
        main_area = tk.Frame(self.main_tab, bg=COLORS["bg"])
        main_area.pack(fill=tk.BOTH, expand=True, padx=10, pady=5)
        
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
        
        # Log area
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
        
        # Minimize to tray button
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

    def create_settings_tab(self):
        """Create settings tab content"""
        settings_header = tk.Frame(self.settings_tab, bg=COLORS["bg"])
        settings_header.pack(fill=tk.X, padx=10, pady=10)
        
        tk.Label(settings_header,
                text="⚙️ Settings",
                bg=COLORS["bg"],
                fg=COLORS["accent"],
                font=("Segoe UI", 16, "bold")).pack(side=tk.LEFT)
        
        # Algorithm Selection Section
        algorithm_section = tk.Frame(self.settings_tab, bg=COLORS["card"], bd=1, relief="solid")
        algorithm_section.pack(fill=tk.X, padx=20, pady=10)
        
        tk.Label(algorithm_section,
                text="🔄 Algorithm Selection",
                bg=COLORS["card"],
                fg=COLORS["accent"],
                font=("Segoe UI", 12, "bold"),
                pady=10).pack(fill=tk.X)
        
        # Algorithm description
        algo_desc = tk.Label(algorithm_section,
                           text="Choose recording algorithm:",
                           bg=COLORS["card"],
                           fg=COLORS["fg"],
                           font=("Segoe UI", 10))
        algo_desc.pack(anchor=tk.W, padx=20, pady=(0, 10))
        
        # Radio buttons for algorithm selection
        self.algorithm_var = tk.StringVar(value=self.current_algorithm)
        
        algo_frame = tk.Frame(algorithm_section, bg=COLORS["card"])
        algo_frame.pack(fill=tk.X, padx=20, pady=5)
        
        tk.Radiobutton(algo_frame,
                      text="Algorithm A: Simple mouse recording with GLOBAL hotkeys",
                      variable=self.algorithm_var,
                      value="A",
                      bg=COLORS["card"],
                      fg=COLORS["fg"],
                      selectcolor=COLORS["card"],
                      activebackground=COLORS["card"],
                      activeforeground=COLORS["fg"],
                      command=lambda: self.switch_algorithm("A")).pack(anchor=tk.W, pady=2)
        
        tk.Radiobutton(algo_frame,
                      text="Algorithm B: Advanced mouse+keyboard with image matching",
                      variable=self.algorithm_var,
                      value="B",
                      bg=COLORS["card"],
                      fg=COLORS["fg"],
                      selectcolor=COLORS["card"],
                      activebackground=COLORS["card"],
                      activeforeground=COLORS["fg"],
                      command=lambda: self.switch_algorithm("B")).pack(anchor=tk.W, pady=2)
        
        # Algorithm info
        algo_info_text = """
Algorithm A:
• Records mouse movements only (left button)
• Global hotkeys work even when window is minimized
• Simple color-based position correction
• Best for simple mouse automation

Algorithm B:
• Records mouse AND keyboard
• Template matching for precise position finding
• Right/left/middle mouse buttons supported
• Requires window focus for hotkeys
• Best for complex automations
"""
        
        algo_info = tk.Label(algorithm_section,
                           text=algo_info_text,
                           bg=COLORS["card"],
                           fg=COLORS["secondary"],
                           font=("Consolas", 8),
                           justify=tk.LEFT)
        algo_info.pack(anchor=tk.W, padx=20, pady=(10, 15))
        
        # Algorithm A Settings
        self.algo_a_settings = tk.Frame(self.settings_tab, bg=COLORS["card"], bd=1, relief="solid")
        self.algo_a_settings.pack(fill=tk.X, padx=20, pady=10)
        
        tk.Label(self.algo_a_settings,
                text="Algorithm A Settings",
                bg=COLORS["card"],
                fg=COLORS["accent"],
                font=("Segoe UI", 12, "bold"),
                pady=10).pack(fill=tk.X)
        
        # Algorithm A hotkey grid
        algo_a_grid = tk.Frame(self.algo_a_settings, bg=COLORS["card"])
        algo_a_grid.pack(fill=tk.BOTH, expand=True, padx=20, pady=10)
        
        # Start Recording A
        row1 = tk.Frame(algo_a_grid, bg=COLORS["card"])
        row1.pack(fill=tk.X, pady=5)
        tk.Label(row1, text="Start Recording:", bg=COLORS["card"], fg=COLORS["fg"], 
                font=("Segoe UI", 10), width=20, anchor=tk.W).pack(side=tk.LEFT)
        self.start_record_a_var = tk.StringVar(value=self.config_a["shortcuts"].get("start_recording", "f2"))
        self.start_record_a_entry = tk.Entry(row1, textvariable=self.start_record_a_var,
                                           bg=COLORS["input_bg"], fg=COLORS["fg"],
                                           font=("Segoe UI", 10), width=15)
        self.start_record_a_entry.pack(side=tk.LEFT, padx=10)
        
        # Stop Recording A
        row2 = tk.Frame(algo_a_grid, bg=COLORS["card"])
        row2.pack(fill=tk.X, pady=5)
        tk.Label(row2, text="Stop Recording:", bg=COLORS["card"], fg=COLORS["fg"], 
                font=("Segoe UI", 10), width=20, anchor=tk.W).pack(side=tk.LEFT)
        self.stop_record_a_var = tk.StringVar(value=self.config_a["shortcuts"].get("stop_recording", "f4"))
        self.stop_record_a_entry = tk.Entry(row2, textvariable=self.stop_record_a_var,
                                          bg=COLORS["input_bg"], fg=COLORS["fg"],
                                          font=("Segoe UI", 10), width=15)
        self.stop_record_a_entry.pack(side=tk.LEFT, padx=10)
        
        # Start Playback A
        row3 = tk.Frame(algo_a_grid, bg=COLORS["card"])
        row3.pack(fill=tk.X, pady=5)
        tk.Label(row3, text="Start Playback:", bg=COLORS["card"], fg=COLORS["fg"], 
                font=("Segoe UI", 10), width=20, anchor=tk.W).pack(side=tk.LEFT)
        self.start_play_a_var = tk.StringVar(value=self.config_a["shortcuts"].get("start_playback", "f8"))
        self.start_play_a_entry = tk.Entry(row3, textvariable=self.start_play_a_var,
                                         bg=COLORS["input_bg"], fg=COLORS["fg"],
                                         font=("Segoe UI", 10), width=15)
        self.start_play_a_entry.pack(side=tk.LEFT, padx=10)
        
        # Stop Playback A
        row4 = tk.Frame(algo_a_grid, bg=COLORS["card"])
        row4.pack(fill=tk.X, pady=5)
        tk.Label(row4, text="Stop Playback:", bg=COLORS["card"], fg=COLORS["fg"], 
                font=("Segoe UI", 10), width=20, anchor=tk.W).pack(side=tk.LEFT)
        self.stop_play_a_var = tk.StringVar(value=self.config_a["shortcuts"].get("stop_playback", "f9"))
        self.stop_play_a_entry = tk.Entry(row4, textvariable=self.stop_play_a_var,
                                        bg=COLORS["input_bg"], fg=COLORS["fg"],
                                        font=("Segoe UI", 10), width=15)
        self.stop_play_a_entry.pack(side=tk.LEFT, padx=10)
        
        # Algorithm B Settings
        self.algo_b_settings = tk.Frame(self.settings_tab, bg=COLORS["card"], bd=1, relief="solid")
        self.algo_b_settings.pack(fill=tk.X, padx=20, pady=10)
        
        tk.Label(self.algo_b_settings,
                text="Algorithm B Settings",
                bg=COLORS["card"],
                fg=COLORS["accent"],
                font=("Segoe UI", 12, "bold"),
                pady=10).pack(fill=tk.X)
        
        # Algorithm B hotkey grid
        algo_b_grid = tk.Frame(self.algo_b_settings, bg=COLORS["card"])
        algo_b_grid.pack(fill=tk.BOTH, expand=True, padx=20, pady=10)
        
        # Start Recording B
        row5 = tk.Frame(algo_b_grid, bg=COLORS["card"])
        row5.pack(fill=tk.X, pady=5)
        tk.Label(row5, text="Start Recording:", bg=COLORS["card"], fg=COLORS["fg"], 
                font=("Segoe UI", 10), width=20, anchor=tk.W).pack(side=tk.LEFT)
        self.start_record_b_var = tk.StringVar(value=HOTKEYS_B.get("start_record", "F2"))
        self.start_record_b_entry = tk.Entry(row5, textvariable=self.start_record_b_var,
                                           bg=COLORS["input_bg"], fg=COLORS["fg"],
                                           font=("Segoe UI", 10), width=15)
        self.start_record_b_entry.pack(side=tk.LEFT, padx=10)
        
        # Stop Recording B
        row6 = tk.Frame(algo_b_grid, bg=COLORS["card"])
        row6.pack(fill=tk.X, pady=5)
        tk.Label(row6, text="Stop Recording:", bg=COLORS["card"], fg=COLORS["fg"], 
                font=("Segoe UI", 10), width=20, anchor=tk.W).pack(side=tk.LEFT)
        self.stop_record_b_var = tk.StringVar(value=HOTKEYS_B.get("stop_record", "F4"))
        self.stop_record_b_entry = tk.Entry(row6, textvariable=self.stop_record_b_var,
                                          bg=COLORS["input_bg"], fg=COLORS["fg"],
                                          font=("Segoe UI", 10), width=15)
        self.stop_record_b_entry.pack(side=tk.LEFT, padx=10)
        
        # Start Playback B
        row7 = tk.Frame(algo_b_grid, bg=COLORS["card"])
        row7.pack(fill=tk.X, pady=5)
        tk.Label(row7, text="Start Playback:", bg=COLORS["card"], fg=COLORS["fg"], 
                font=("Segoe UI", 10), width=20, anchor=tk.W).pack(side=tk.LEFT)
        self.start_play_b_var = tk.StringVar(value=HOTKEYS_B.get("start_play", "F8"))
        self.start_play_b_entry = tk.Entry(row7, textvariable=self.start_play_b_var,
                                         bg=COLORS["input_bg"], fg=COLORS["fg"],
                                         font=("Segoe UI", 10), width=15)
        self.start_play_b_entry.pack(side=tk.LEFT, padx=10)
        
        # Stop Playback B
        row8 = tk.Frame(algo_b_grid, bg=COLORS["card"])
        row8.pack(fill=tk.X, pady=5)
        tk.Label(row8, text="Stop Playback:", bg=COLORS["card"], fg=COLORS["fg"], 
                font=("Segoe UI", 10), width=20, anchor=tk.W).pack(side=tk.LEFT)
        self.stop_play_b_var = tk.StringVar(value=HOTKEYS_B.get("stop_play", "F10"))
        self.stop_play_b_entry = tk.Entry(row8, textvariable=self.stop_play_b_var,
                                        bg=COLORS["input_bg"], fg=COLORS["fg"],
                                        font=("Segoe UI", 10), width=15)
        self.stop_play_b_entry.pack(side=tk.LEFT, padx=10)
        
        # Save Settings Button
        button_frame = tk.Frame(self.settings_tab, bg=COLORS["bg"])
        button_frame.pack(fill=tk.X, pady=20, padx=20)
        
        tk.Button(button_frame,
                 text="💾 Save All Settings",
                 bg=COLORS["accent"],
                 fg="white",
                 font=("Segoe UI", 10),
                 borderwidth=0,
                 padx=20,
                 pady=8,
                 command=self.save_all_settings).pack(pady=5)
        
        tk.Button(button_frame,
                 text="🔄 Reset to Defaults",
                 bg=COLORS["secondary"],
                 fg="white",
                 font=("Segoe UI", 10),
                 borderwidth=0,
                 padx=20,
                 pady=8,
                 command=self.reset_all_settings).pack(pady=5)

    def create_info_tab(self):
        """Create info tab content"""
        info_header = tk.Frame(self.info_tab, bg=COLORS["bg"])
        info_header.pack(fill=tk.X, padx=10, pady=10)
        
        tk.Label(info_header,
                text="📖 MacroFlow Hybrid - User Manual",
                bg=COLORS["bg"],
                fg=COLORS["accent"],
                font=("Segoe UI", 16, "bold")).pack(side=tk.LEFT)
        
        # Main info container
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
━━━━━━━━━━━━━━━━━━━━━━━━━━━
|       MACROFLOW HYBRID - USER MANUAL                    |
━━━━━━━━━━━━━━━━━━━━━━━━━━━

🎯 INTRODUCTION
MacroFlow Hybrid combines two powerful algorithms for automation:
• Algorithm A: Simple mouse recording with GLOBAL hotkeys
• Algorithm B: Advanced mouse+keyboard with image matching

Switch between algorithms in the Settings tab!

━━━━━━━━━━━━━━━━━━━━━━━━━━━

🔄 ALGORITHM SELECTION

ALGORITHM A (Simple):
• ✅ Global hotkeys work even when window is minimized
• ✅ Records left mouse clicks and drags only
• ✅ Simple color-based position correction
• ❌ No keyboard recording
• ❌ No right/middle mouse button support
• Best for: Simple mouse automations, background operation

ALGORITHM B (Advanced):
• ✅ Records mouse AND keyboard
• ✅ Right/left/middle mouse buttons supported
• ✅ Template matching for precise position finding
• ❌ Hotkeys require window focus
• ❌ More resource intensive
• Best for: Complex automations, keyboard input, right-click menus

━━━━━━━━━━━━━━━━━━━━━━━━

🎮 QUICK START

1. SELECT ALGORITHM in Settings tab
2. For Algorithm B: Choose what to record (Keyboard, Mouse, Right Click)
3. Click "▶ Start Rec" or use hotkey (F2)
4. Perform your actions
5. Click "⏹ Stop Rec" or use hotkey (F4)
6. Click "▶ Play" or use hotkey (F8) to replay

━━━━━━━━━━━━━━━━━━━━━━━━

⌨️ KEYBOARD SHORTCUTS

ALGORITHM A (Global - work when minimized):
• F2 - Start Recording
• F4 - Stop Recording
• F8 - Start Playback
• F9 - Stop Playback

ALGORITHM B (Requires window focus):
• F2 - Start Recording
• F4 - Stop Recording
• F8 - Start Playback
• F10 - Stop Playback

Customize shortcuts in Settings tab.

━━━━━━━━━━━━━━━━━━━━━━━━

📱 COMPACT MODE
• Click "📱 Compact Mode" for minimal interface
• Small floating window with 4 main buttons
• Always on top of other windows
• Draggable - move it anywhere on screen
• Close with ✕ to return to normal mode

━━━━━━━━━━━━━━━━━━━━━━━━

💾 FILE MANAGEMENT
• "💾 Save" - Save recorded macro as JSON
• "📂 Load" - Load previously saved macro
• Macros can be shared between algorithms (with conversion)
• Data saved to: """ + APP_DATA_DIR + """

━━━━━━━━━━━━━━━━━━━━━━━━

🔄 EVENT CONVERSION
• When switching algorithms, events are automatically converted
• Algorithm B → A: Keyboard events and right-clicks are removed
• Algorithm A → B: All mouse events are preserved
• Conversion happens automatically when loading/saving

━━━━━━━━━━━━━━━━━━━━━━━━

⚙️ PLAYBACK OPTIONS
• Delay start: Seconds to wait before playback
• Repeat: Minutes between repetitions (0 = play once)
• Both algorithms use the same playback settings

━━━━━━━━━━━━━━━━━━━━━━━━

📊 STATUS INDICATORS
• Status: Shows current state (Ready, Recording, Playing...)
• Algorithm: Shows which algorithm is active
• Events: Shows recorded events count
• Log: Detailed activity log

━━━━━━━━━━━━━━━━━━━━━━━━

⚠️ TIPS

FOR ALGORITHM A:
• Use when you need background operation
• Perfect for simple repetitive mouse tasks
• Global hotkeys work even when doing other work

FOR ALGORITHM B:
• Use for complex automations with keyboard
• Right-click recording for context menus
• More accurate position finding with template matching

GENERAL:
• Test macros immediately after recording
• Save important macros with descriptive names
• Use Compact Mode for quick access
• Check logs if something doesn't work

━━━━━━━━━━━━━━━━━━━━━━━━

🔧 SYSTEM TRAY
• Click "📌 Minimize to Tray" to hide to system tray
• Restore from tray icon
• Exit from tray menu
• Compact mode available from tray

━━━━━━━━━━━━━━━━━━━━━━━━

🎉 GETTING STARTED EXAMPLE

1. FIRST TIME:
   • Open Settings tab
   • Choose Algorithm B for full features
   • Enable Keyboard, Mouse, and Right Click recording
   • Save settings

2. RECORD A MACRO:
   • Click "▶ Start Rec" (F2)
   • Type some text
   • Click somewhere
   • Right-click to open menu
   • Click "⏹ Stop Rec" (F4)

3. TEST PLAYBACK:
   • Click "▶ Play" (F8)
   • Watch automation execute

4. TRY ALGORITHM A:
   • Switch to Algorithm A in Settings
   • Notice global hotkeys now work
   • Record simple mouse macro
   • Minimize window and test hotkeys

━━━━━━━━━━━━━━━━━━━━━━━━━

Enjoy automating with MacroFlow Hybrid! 🚀
"""
        
        info_text.insert(tk.END, instructions)
        info_text.config(state=tk.DISABLED)

    def setup_keyboard_recording_b(self):
        """Setup keyboard listener for Algorithm B recording"""
        if self.keyboard_listener_b:
            self.keyboard_listener_b.stop()
        
        self.keyboard_listener_b = keyboard.Listener(
            on_press=_on_key_press_record_b,
            on_release=_on_key_release_record_b
        )
        self.keyboard_listener_b.start()

    def stop_keyboard_recording_b(self):
        """Stop keyboard recording for Algorithm B"""
        if self.keyboard_listener_b:
            self.keyboard_listener_b.stop()
            self.keyboard_listener_b = None

    def setup_system_tray(self):
        """Create system tray icon"""
        try:
            import pystray
            from PIL import Image, ImageDraw
            
            def create_image():
                image = Image.new('RGB', (64, 64), color=(74, 158, 255))
                draw = ImageDraw.Draw(image)
                draw.ellipse([10, 10, 54, 54], fill=(255, 255, 255))
                return image
            
            menu = pystray.Menu(
                pystray.MenuItem('Show MacroFlow', self.show_from_tray),
                pystray.MenuItem('Compact Mode', self.enter_compact_mode),
                pystray.MenuItem('Exit', self.exit_app)
            )
            
            image = create_image()
            self.tray_icon = pystray.Icon("macroflow", image, "MacroFlow Hybrid", menu)
            
            tray_thread = threading.Thread(target=self.tray_icon.run, daemon=True)
            tray_thread.start()
            
            self.log("System tray icon created")
            
        except ImportError:
            self.log("pystray not installed. Run: pip install pystray")
            self.tray_icon = None
        except Exception as e:
            self.log(f"System tray setup error: {str(e)}")
            self.tray_icon = None

    def hide_to_tray_func(self):
        """Hide window to system tray"""
        if hasattr(self, 'tray_icon') and self.tray_icon:
            self.root.withdraw()
            self.hidden_to_tray = True
            self.log("Minimized to system tray")
        else:
            self.root.iconify()
            self.log("Minimized to taskbar")

    def show_from_tray(self):
        """Show window from system tray"""
        self.root.deiconify()
        self.root.lift()
        self.root.focus_force()
        self.hidden_to_tray = False
        self.log("Restored from system tray")

    def exit_app(self):
        """Exit application completely"""
        if hasattr(self, 'tray_icon') and self.tray_icon:
            self.tray_icon.stop()
        self.on_close()

    def switch_algorithm(self, algorithm):
        """Switch between algorithms"""
        if algorithm == self.current_algorithm:
            return
        
        self.log(f"Switching from Algorithm {self.current_algorithm} to Algorithm {algorithm}")
        
        # Stop any ongoing recording or playback
        if self.current_algorithm == "A":
            if recording_a:
                self.stop_record()
        else:
            if recording_b:
                self.stop_record()
        
        # Check if playback is running (for both algorithms)
        try:
            if playing_b:
                self.stop_play()
        except:
            pass
        
        # Update current algorithm
        self.current_algorithm = algorithm
        
        # Update UI
        self.update_algorithm_ui()
        
        # Update status label
        algo_name = "A (Simple)" if algorithm == "A" else "B (Advanced)"
        self.status_label.config(text=f"Status: Ready | Algorithm: {algo_name}")
        self.algo_info_label.config(
            text=f"Current: Algorithm {algo_name}",
            fg=COLORS["success"] if algorithm == "B" else COLORS["accent"]
        )
        
        # Update hotkey registration
        if algorithm == "A":
            # Register global hotkeys for Algorithm A
            start_global_keyboard_hooks_a(self, self.config_a["shortcuts"])
            self.log("Algorithm A active - Global hotkeys registered")
        else:
            # Stop global hotkeys for Algorithm A
            stop_global_keyboard_hooks_a()
            self.log("Algorithm B active - Using local hotkeys")
        
        # Refresh events display
        self._refresh_ui()

    def update_algorithm_ui(self):
        """Update UI based on selected algorithm"""
        if self.current_algorithm == "A":
            # Disable Algorithm B specific options
            self.record_keys_check.config(state=tk.DISABLED)
            self.record_right_click_check.config(state=tk.DISABLED)
            self.options_frame.pack_forget()  # Hide options frame
            
            # Update button labels with Algorithm A hotkeys
            hotkeys = self.config_a["shortcuts"]
            self.record_start_btn.config(text=f"▶ Start Rec ({hotkeys['start_recording'].upper()})")
            self.record_stop_btn.config(text=f"⏹ Stop Rec ({hotkeys['stop_recording'].upper()})")
            self.play_start_btn.config(text=f"▶ Play ({hotkeys['start_playback'].upper()})")
            self.play_stop_btn.config(text=f"⏹ Stop ({hotkeys['stop_playback'].upper()})")
            
            # Show Algorithm A settings, hide B
            self.algo_a_settings.pack(fill=tk.X, padx=20, pady=10)
            self.algo_b_settings.pack_forget()
            
        else:
            # Enable Algorithm B specific options
            self.record_keys_check.config(state=tk.NORMAL)
            self.record_right_click_check.config(state=tk.NORMAL)
            self.options_frame.pack(fill=tk.X, padx=10, pady=5)  # Show options frame
            
            # Update button labels with Algorithm B hotkeys
            self.record_start_btn.config(text=f"▶ Start Rec ({HOTKEYS_B['start_record']})")
            self.record_stop_btn.config(text=f"⏹ Stop Rec ({HOTKEYS_B['stop_record']})")
            self.play_start_btn.config(text=f"▶ Play ({HOTKEYS_B['start_play']})")
            self.play_stop_btn.config(text=f"⏹ Stop ({HOTKEYS_B['stop_play']})")
            
            # Show Algorithm B settings, hide A
            self.algo_b_settings.pack(fill=tk.X, padx=20, pady=10)
            self.algo_a_settings.pack_forget()
        
        # Update compact mode if active AND window exists
        if self.compact_window:
            try:
                # Check if window still exists
                if self.compact_window.window.winfo_exists():
                    self.compact_window.update_hotkeys()
                else:
                    # Window was closed, clear reference
                    self.compact_window = None
            except Exception as e:
                # Window might have been destroyed
                logging.exception(f"Error updating compact window: {e}")
                self.compact_window = None

    def save_all_settings(self):
        """Save all settings for both algorithms"""
        # Save Algorithm A settings
        self.config_a["shortcuts"]["start_recording"] = self.start_record_a_var.get().strip().lower()
        self.config_a["shortcuts"]["stop_recording"] = self.stop_record_a_var.get().strip().lower()
        self.config_a["shortcuts"]["start_playback"] = self.start_play_a_var.get().strip().lower()
        self.config_a["shortcuts"]["stop_playback"] = self.stop_play_a_var.get().strip().lower()
        
        # Save Algorithm B settings
        global HOTKEYS_B
        HOTKEYS_B["start_record"] = self.start_record_b_var.get().strip().upper()
        HOTKEYS_B["stop_record"] = self.stop_record_b_var.get().strip().upper()
        HOTKEYS_B["start_play"] = self.start_play_b_var.get().strip().upper()
        HOTKEYS_B["stop_play"] = self.stop_play_b_var.get().strip().upper()
        
        # Save to files
        try:
            save_config_a(self.config_a)
            
            settings_file = os.path.join(APP_DATA_DIR, "macroflow_settings_b.json")
            with open(settings_file, "w") as f:
                json.dump(HOTKEYS_B, f, indent=2)
            
            self.log("All settings saved successfully")
            messagebox.showinfo("Success", "Settings saved successfully!")
            
            # Update UI
            self.update_algorithm_ui()
            
            # Re-register hotkeys if Algorithm A is active
            if self.current_algorithm == "A":
                stop_global_keyboard_hooks_a()
                start_global_keyboard_hooks_a(self, self.config_a["shortcuts"])
                
        except Exception as e:
            messagebox.showerror("Error", f"Failed to save settings: {str(e)}")

    def reset_all_settings(self):
        """Reset all settings to defaults"""
        if messagebox.askyesno("Reset Settings", 
                              "Are you sure you want to reset ALL settings to defaults?"):
            # Reset Algorithm A
            self.config_a["shortcuts"] = DEFAULT_SHORTCUTS_A.copy()
            self.start_record_a_var.set("f2")
            self.stop_record_a_var.set("f4")
            self.start_play_a_var.set("f8")
            self.stop_play_a_var.set("f9")
            
            # Reset Algorithm B
            global HOTKEYS_B
            HOTKEYS_B = {
                "start_record": "F2",
                "stop_record": "F4", 
                "start_play": "F8",
                "stop_play": "F10"
            }
            self.start_record_b_var.set("F2")
            self.stop_record_b_var.set("F4")
            self.start_play_b_var.set("F8")
            self.stop_play_b_var.set("F10")
            
            self.log("All settings reset to defaults")
            messagebox.showinfo("Success", "All settings reset to defaults!")

    def load_settings(self):
        """Load settings from files"""
        # Algorithm A settings are loaded in __init__
        
        # Load Algorithm B settings
        try:
            settings_file = os.path.join(APP_DATA_DIR, "macroflow_settings_b.json")
            if os.path.exists(settings_file):
                with open(settings_file, "r") as f:
                    saved_settings = json.load(f)
                    global HOTKEYS_B
                    HOTKEYS_B.update(saved_settings)
                    
                    # Update UI variables
                    self.start_record_b_var.set(HOTKEYS_B.get("start_record", "F2"))
                    self.stop_record_b_var.set(HOTKEYS_B.get("stop_record", "F4"))
                    self.start_play_b_var.set(HOTKEYS_B.get("start_play", "F8"))
                    self.stop_play_b_var.set(HOTKEYS_B.get("stop_play", "F10"))
                    
                self.log(f"Loaded Algorithm B settings from {settings_file}")
        except Exception as e:
            self.log(f"Failed to load Algorithm B settings: {str(e)}")

    def _on_key_press(self, key):
        """Handle hotkey presses"""
        try:
            key_str = None
            try:
                key_str = key.char.upper() if key.char else None
            except AttributeError:
                if hasattr(key, 'name'):
                    key_str = key.name.upper()
                else:
                    key_str = str(key).replace("Key.", "").upper()
            
            if not key_str:
                return
            
            if self.current_algorithm == "A":
                # Algorithm A uses global hotkeys, handled separately
                pass
            else:
                # Algorithm B hotkeys (require window focus)
                if key_str == HOTKEYS_B["start_record"].upper():
                    self.start_record()
                elif key_str == HOTKEYS_B["stop_record"].upper():
                    self.stop_record()
                elif key_str == HOTKEYS_B["start_play"].upper():
                    self.start_play()
                elif key_str == HOTKEYS_B["stop_play"].upper():
                    self.stop_play()
                    
        except Exception as e:
            logging.exception("Error in _on_key_press")

    def log(self, text):
        """Log message to both file and UI"""
        logging.info(text)
        self.log_box.insert(tk.END, f"{datetime.now().strftime('%H:%M:%S')} - {text}\n")
        self.log_box.see(tk.END)

    def _refresh_ui(self):
        """Refresh UI with current events"""
        try:
            self.events_listbox.delete(0, tk.END)
            
            if self.current_algorithm == "A":
                events_list = events_a
                algo_prefix = "A"
            else:
                events_list = events_b
                algo_prefix = "B"
            
            for i, e in enumerate(events_list):
                if e["type"] == "click":
                    if self.current_algorithm == "A":
                        self.events_listbox.insert(tk.END, f"{algo_prefix}:{i}: CLICK pos={e['pos']}")
                    else:
                        button = e.get("button", "left")
                        self.events_listbox.insert(tk.END, f"{algo_prefix}:{i}: {button.upper()}_CLICK pos={e['pos']}")
                elif e["type"] == "drag":
                    if self.current_algorithm == "A":
                        self.events_listbox.insert(tk.END, f"{algo_prefix}:{i}: DRAG {e['start']}->{e['end']}")
                    else:
                        button = e.get("button", "left")
                        self.events_listbox.insert(tk.END, f"{algo_prefix}:{i}: {button.upper()}_DRAG {e['start']}->{e['end']}")
                elif e["type"] == "key_press":
                    self.events_listbox.insert(tk.END, f"{algo_prefix}:{i}: KEY_PRESS: {e['key']}")
                elif e["type"] == "key_release":
                    self.events_listbox.insert(tk.END, f"{algo_prefix}:{i}: KEY_RELEASE: {e['key']}")
                    
            # Update status with event count
            event_count = len(events_list)
            algo_name = "A" if self.current_algorithm == "A" else "B"
            self.status_label.config(text=f"Status: Ready | Algorithm: {algo_name} | Events: {event_count}")
            
        except Exception as e:
            logging.exception("Error in _refresh_ui")
        
        self.root.after(400, self._refresh_ui)

    def start_record(self):
        """Start recording with current algorithm"""
        if self.current_algorithm == "A":
            global recording_a, events_a, last_event_time_a
            events_a.clear()
            recording_a = True
            last_event_time_a = None
            
            self.status_label.config(text="Status: Recording (Algorithm A)")
            if self.compact_window:
                self.compact_window.update_status("Recording (A)")
            
            self.log(f"Algorithm A: Recording started (Hotkey: {self.config_a['shortcuts']['start_recording']})")
            
        else:
            global recording_b, events_b, last_event_time_b
            
            # Check if at least one recording option is selected
            if not self.record_keys_var.get() and not self.record_mouse_var.get():
                messagebox.showwarning("Warning", "Please select at least one recording option (Keyboard or Mouse)")
                return
            
            events_b.clear()
            recording_b = True
            last_event_time_b = None
            
            # Setup keyboard recording if enabled
            if self.record_keys_var.get():
                self.setup_keyboard_recording_b()
                self.log("Algorithm B: Keyboard recording enabled")
            else:
                self.stop_keyboard_recording_b()
            
            self.status_label.config(text="Status: Recording (Algorithm B)")
            if self.compact_window:
                self.compact_window.update_status("Recording (B)")
            
            options = []
            if self.record_keys_var.get():
                options.append("Keyboard")
            if self.record_mouse_var.get():
                options.append("Mouse")
            if self.record_right_click_var.get():
                options.append("Right Click")
            
            self.log(f"Algorithm B: Recording started (Hotkey: {HOTKEYS_B['start_record']}) - Recording: {', '.join(options)}")

    def stop_record(self):
        """Stop recording with current algorithm"""
        if self.current_algorithm == "A":
            global recording_a
            recording_a = False
            
            self.status_label.config(text="Status: Ready (Algorithm A)")
            if self.compact_window:
                self.compact_window.update_status("Ready (A)")
            
            self.log(f"Algorithm A: Recording stopped; events={len(events_a)} (Hotkey: {self.config_a['shortcuts']['stop_recording']})")
            
            # Save events to file
            try:
                def convert_for_json(obj):
                    if isinstance(obj, tuple):
                        return list(obj)
                    return obj
                
                save_file = os.path.join(APP_DATA_DIR, "macros_a.json")
                with open(save_file, "w") as f:
                    json_str = json.dumps(events_a, default=convert_for_json, indent=2)
                    f.write(json_str)
                
                self.log(f"Algorithm A: Saved {len(events_a)} events to {save_file}")
                
            except Exception as e:
                logging.exception(f"Algorithm A: Error saving macros_a.json: {e}")
                
        else:
            global recording_b
            
            # Stop keyboard recording listener
            self.stop_keyboard_recording_b()
            
            recording_b = False
            self.status_label.config(text="Status: Ready (Algorithm B)")
            if self.compact_window:
                self.compact_window.update_status("Ready (B)")
            
            self.log(f"Algorithm B: Recording stopped; events={len(events_b)} (Hotkey: {HOTKEYS_B['stop_record']})")

    def start_play(self):
        """Start playback with current algorithm"""
        try:
            delay = int(self.delay_entry.get())
        except Exception:
            delay = 0
            self.delay_entry.delete(0, tk.END)
            self.delay_entry.insert(0, "0")
        
        try:
            repeat = int(self.repeat_entry.get())
        except Exception:
            repeat = 0
            self.repeat_entry.delete(0, tk.END)
            self.repeat_entry.insert(0, "0")
        
        if self.current_algorithm == "A":
            if not events_a:
                self.status_label.config(text="Status: No events! (Algorithm A)")
                self.root.after(2000, lambda: self.status_label.config(
                    text=f"Status: Ready (Algorithm A)"))
                return
            
            self.status_label.config(text="Status: Playing (Algorithm A)")
            if self.compact_window:
                self.compact_window.update_status("Playing (A)")
            
            global playing_b
            playing_b = True
            playback_worker.running = True
            
            self.log(f"Algorithm A: Playback started (Hotkey: {self.config_a['shortcuts']['start_playback']})")
            
            # Start playback thread for Algorithm A
            thread = threading.Thread(
                target=playback_worker,
                args=(delay, repeat, self.status_label, self.log, "A"),
                daemon=True
            )
            thread.start()
            
        else:
            if not events_b:
                self.status_label.config(text="Status: No events! (Algorithm B)")
                self.root.after(2000, lambda: self.status_label.config(
                    text=f"Status: Ready (Algorithm B)"))
                return
            
            self.status_label.config(text="Status: Playing (Algorithm B)")
            if self.compact_window:
                self.compact_window.update_status("Playing (B)")
            
            #global playing_b
            playing_b = True
            playback_worker.running = True
            
            self.log(f"Algorithm B: Playback started (Hotkey: {HOTKEYS_B['start_play']})")
            
            # Start playback thread for Algorithm B
            thread = threading.Thread(
                target=playback_worker,
                args=(delay, repeat, self.status_label, self.log, "B"),
                daemon=True
            )
            thread.start()

    def stop_play(self):
        """Stop playback"""
        global playing_b  # DODAJ global playing_b
        
        playback_worker.running = False
        
        if self.current_algorithm == "A":
            self.status_label.config(text="Status: Ready (Algorithm A)")
            if self.compact_window:
                self.compact_window.update_status("Ready (A)")
            
            self.log(f"Algorithm A: Playback stopped (Hotkey: {self.config_a['shortcuts']['stop_playback']})")
        else:
            playing_b = False
            self.status_label.config(text="Status: Ready (Algorithm B)")
            if self.compact_window:
                self.compact_window.update_status("Ready (B)")
            
            self.log(f"Algorithm B: Playback stopped (Hotkey: {HOTKEYS_B['stop_play']})")

    def save_file(self):
        """Save events to file"""
        default_dir = APP_DATA_DIR
        
        if self.current_algorithm == "A":
            default_file = os.path.join(default_dir, "macros_a.json")
            events_to_save = events_a
            algo_suffix = "_a"
        else:
            default_file = os.path.join(default_dir, "macros_b.json")
            events_to_save = events_b
            algo_suffix = "_b"
        
        fname = filedialog.asksaveasfilename(
            defaultextension=".json", 
            initialfile=os.path.basename(default_file),
            initialdir=default_dir,
            filetypes=[("JSON files", "*.json"), ("All files", "*.*")]
        )
        
        if not fname:
            return
        
        export = []
        for e in events_to_save:
            ee = dict(e)
            # Remove non-serializable data
            if "template" in ee:
                del ee["template"]
            if "color" in ee and isinstance(ee["color"], tuple):
                ee["color"] = list(ee["color"])
            if "samples" in ee:
                for sample in ee["samples"]:
                    if "pos" in sample and isinstance(sample["pos"], tuple):
                        sample["pos"] = list(sample["pos"])
            export.append(ee)
        
        try:
            with open(fname, "w", encoding="utf-8") as fh:
                json.dump(export, fh, indent=2)
            self.log(f"Saved {len(export)} events to {fname}")
            
            # Offer to convert to other algorithm format
            if messagebox.askyesno("Convert Format", 
                                  f"Would you like to also save a version for Algorithm {'A' if self.current_algorithm == 'B' else 'B'}?"):
                self.convert_and_save_events(events_to_save, fname, algo_suffix)
                
        except Exception as e:
            messagebox.showerror("Save error", str(e))

    def convert_and_save_events(self, events_list, original_path, original_suffix):
        """Convert events to other algorithm format and save"""
        if original_suffix == "_a":
            # Convert A to B
            converted = convert_a_to_b_events(events_list)
            new_path = original_path.replace("_a.json", "_converted_to_b.json")
            algo_name = "B"
        else:
            # Convert B to A
            converted = convert_b_to_a_events(events_list)
            new_path = original_path.replace("_b.json", "_converted_to_a.json")
            algo_name = "A"
        
        try:
            # Clean up for serialization
            export = []
            for e in converted:
                ee = dict(e)
                if "template" in ee:
                    del ee["template"]
                if "color" in ee and isinstance(ee["color"], tuple):
                    ee["color"] = list(ee["color"])
                export.append(ee)
            
            with open(new_path, "w", encoding="utf-8") as fh:
                json.dump(export, fh, indent=2)
            
            self.log(f"Converted and saved {len(export)} events for Algorithm {algo_name} to {new_path}")
            messagebox.showinfo("Conversion Complete", 
                              f"Events converted to Algorithm {algo_name} format and saved to:\n{new_path}")
            
        except Exception as e:
            self.log(f"Failed to convert events: {str(e)}")
            messagebox.showerror("Conversion Error", f"Failed to convert events: {str(e)}")

    def load_file(self):
        """Load events from file"""
        global events_a
        global events_b
        initial_dir = APP_DATA_DIR if os.path.exists(APP_DATA_DIR) else "."
        
        fname = filedialog.askopenfilename(
            initialdir=initial_dir,
            filetypes=[("JSON files", "*.json"), ("All files", "*.*")]
        )
        
        if not fname:
            return
        
        try:
            with open(fname, "r", encoding="utf-8") as fh:
                data = json.load(fh)
            
            # Try to determine algorithm from filename or content
            if "_a.json" in fname.lower() or "color" in str(data[0] if data else ""):
                # Looks like Algorithm A format
                if self.current_algorithm == "A":
                    global events_a
                    events_a = data
                    self.log(f"Loaded {len(data)} Algorithm A events from {fname}")
                else:
                    # Convert to Algorithm B
                    converted = convert_a_to_b_events(data)
                    global events_b
                    events_b = converted
                    self.log(f"Loaded and converted {len(data)} events from Algorithm A to B format")
                    messagebox.showinfo("Format Converted", 
                                      f"Loaded {len(data)} events and converted to Algorithm B format")
            else:
                # Looks like Algorithm B format
                if self.current_algorithm == "B":
                    #global events_b
                    events_b = data
                    self.log(f"Loaded {len(data)} Algorithm B events from {fname}")
                else:
                    # Convert to Algorithm A
                    converted = convert_b_to_a_events(data)
                    #global events_a
                    events_a = converted
                    self.log(f"Loaded and converted {len(data)} events from Algorithm B to A format")
                    messagebox.showinfo("Format Converted", 
                                      f"Loaded {len(data)} events and converted to Algorithm A format\n"
                                      f"Note: Keyboard events and right-clicks were removed.")
                    
        except Exception as e:
            messagebox.showerror("Load error", str(e))

    def toggle_compact_mode(self):
        """Toggle compact mode"""
        global compact_mode
        
        if not compact_mode:
            self.enter_compact_mode()
        else:
            self.exit_compact_mode()

    def enter_compact_mode(self):
        """Enter compact mode"""
        global compact_mode
        
        self.root.withdraw()
        self.compact_window = CompactModeWindow(self)
        
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
        """Exit compact mode"""
        global compact_mode
        
        if self.compact_window:
            self.compact_window.close_compact()
            self.compact_window = None
        
        compact_mode = False

    def _update_compact_status(self):
        """Update status in compact mode"""
        if compact_mode and self.compact_window:
            current_status = self.status_label.cget("text").replace("Status: ", "")
            self.compact_window.update_status(current_status)
        
        self.root.after(1000, self._update_compact_status)

    def on_close(self):
        """Clean up and close application"""
        try:
            self.k_listener.stop()
        except Exception:
            pass
        
        try:
            global mouse_listener_a
            if mouse_listener_a:
                mouse_listener_a.stop()
        except Exception:
            pass
        
        try:
            global _mouse_listener_b
            if _mouse_listener_b:
                _mouse_listener_b.stop()
        except Exception:
            pass
        
        # Stop keyboard recording if active
        self.stop_keyboard_recording_b()
        
        # Stop global hotkeys for Algorithm A
        stop_global_keyboard_hooks_a()
        
        playback_worker.running = False
        
        if hasattr(self, 'tray_icon') and self.tray_icon:
            self.tray_icon.stop()
        
        if self.compact_window:
            self.compact_window.window.destroy()
        
        self.root.quit()
        self.root.destroy()

# ==================== MAIN ====================
def main():
    global APP
    try:
        APP = MacroFlowHybridApp()
        APP.root.mainloop()
    except Exception as e:
        logging.exception("Fatal error in main")
        print(f"Fatal error. See log: {LOG_FILE}")
        print(f"Error details: {str(e)}")
        sys.exit(1)

if __name__ == "__main__":
    main()