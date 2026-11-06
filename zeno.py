import subprocess as sp
import ctypes as ct
import atexit
import keyboard
import psutil
import threading
import customtkinter as ctk
import sys
from typing import Optional
import os
import tempfile
import colorsys
from win32gui import GetForegroundWindow, GetWindowRect, SetWindowPos, GetParent, GetWindowLong, SetWindowLong
import win32con as wc
import win32process
import win32api
import pystray
from PIL import Image, ImageDraw

RULE_NAME = "Roblox_Block"
DEFAULT_KEYBIND = "c"
CTK_ICON_PATH = os.path.join(os.path.dirname(ctk.__file__), 'assets', 'icons', 'CustomTkinter_icon_Windows.ico')
BG_COLOR = '#0b0b0b'


def to_red(color):
    
    if isinstance(color, list):
        return [to_red(c) for c in color]
    if isinstance(color, dict):
        return {k: to_red(v) for k, v in color.items()}
    if isinstance(color, str) and color.startswith('#') and len(color) == 7:
        r, g, b = (int(color[i:i + 2], 16) / 255 for i in (1, 3, 5))
        h, s, v = colorsys.rgb_to_hsv(r, g, b)
        if s > 0.25 and 0.5 < h < 0.75:
            r, g, b = colorsys.hsv_to_rgb(0.0, s, v)
            return '#%02x%02x%02x' % (round(r * 255), round(g * 255), round(b * 255))
    return color


def apply_red_theme() -> None:
    theme = ctk.ThemeManager.theme
    for key in list(theme):
        theme[key] = to_red(theme[key])
    for key in ('CTk', 'CTkToplevel'):
        theme[key]['fg_color'] = ['gray92', BG_COLOR]


def red_icon_image() -> Image.Image:
    
    img = Image.open(CTK_ICON_PATH).convert('RGBA')
    alpha = img.getchannel('A')
    _, s, v = img.convert('RGB').convert('HSV').split()
    red = Image.merge('HSV', (Image.new('L', img.size, 0), s, v)).convert('RGB')
    red.putalpha(alpha)
    return red

class Zeno:
    def __init__(self) -> None:
        self.settings = {
            'Keybind': DEFAULT_KEYBIND,
            'Lagswitch': 'off',
            'AutoTurnOff': False,
            'AutoTurnBackOn': False,
            'Overlay': True
        }
        self.block_flag: bool = False
        self.lagswitch_active: bool = False
        self.manual_override: bool = False
        self.timer_duration: float = 9.8
        self.reactivation_duration: float = 0.2
        self.active_timer: Optional[threading.Timer] = None
        self.timer_lock = threading.Lock()
        self.lagswitch_cycle_event = threading.Event()
        self.auto_cycle_thread: Optional[threading.Thread] = None
        self.keybind_temp_handler: Optional[int] = None
        self.keybind_handler: Optional[int] = None
        self.status_window: Optional[ctk.CTkToplevel] = None
        self.overlay_update_event = threading.Event()
        self.overlay_update_thread: Optional[threading.Thread] = None

        ctk.set_appearance_mode('dark')
        ctk.set_default_color_theme('blue')
        apply_red_theme()
        self.root = ctk.CTk()
        self.root.title('Zeno')
        self.root.resizable(False, False)
        self.root.attributes('-topmost', False)

        self.check_requirements()
        self.setup_ui()
        self.setup_keybind()
        if self.settings['Overlay']:
            self.toggle_status_window()

        self.tray_icon: Optional[pystray.Icon] = None
        self.root.bind('<Unmap>', self.on_unmap)
        self.root.after(150, self.place_bottom_right)

        
        try:
            self.icon_path = os.path.join(tempfile.gettempdir(), 'zeno_red.ico')
            red_icon_image().save(self.icon_path, sizes=[(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (256, 256)])
            self.root.after(300, lambda: self.root.iconbitmap(self.icon_path))
        except Exception:
            pass

    def place_bottom_right(self) -> None:
        
        try:
            self.root.update_idletasks()
            hwnd = GetParent(self.root.winfo_id()) or self.root.winfo_id()
            left, top, right, bottom = GetWindowRect(hwnd)
            work = win32api.GetMonitorInfo(win32api.MonitorFromPoint((0, 0)))['Work']
            x = work[2] - (right - left) - 10
            y = work[3] - (bottom - top) - 14
            SetWindowPos(hwnd, 0, x, y, 0, 0, wc.SWP_NOSIZE | wc.SWP_NOZORDER | wc.SWP_NOACTIVATE)
        except Exception:
            pass

    def on_unmap(self, event) -> None:
        if event.widget is self.root and self.root.state() == 'iconic' and self.tray_icon is None:
            self.root.after(0, self.hide_to_tray)

    def make_tray_image(self) -> Image.Image:
        
        try:
            return red_icon_image()
        except Exception:
            img = Image.new('RGBA', (64, 64), (0, 0, 0, 0))
            ImageDraw.Draw(img).rounded_rectangle((4, 4, 60, 60), radius=12, fill=(165, 31, 31))
            return img

    def hide_to_tray(self) -> None:
        self.root.withdraw()
        menu = pystray.Menu(
            pystray.MenuItem('Show', self.on_tray_show, default=True),
            pystray.MenuItem('Exit', self.on_tray_exit),
        )
        self.tray_icon = pystray.Icon('Zeno', self.make_tray_image(), 'Zeno', menu)
        self.tray_icon.run_detached()

    def on_tray_show(self, icon, item) -> None:
        icon.stop()
        self.tray_icon = None
        self.root.after(0, self.show_from_tray)

    def show_from_tray(self) -> None:
        self.root.deiconify()
        self.root.lift()
        self.root.focus_force()

    def on_tray_exit(self, icon, item) -> None:
        icon.stop()
        self.tray_icon = None
        self.root.after(0, self.root.destroy)

    def setup_ui(self) -> None:
        body = ctk.CTkFrame(self.root, fg_color='transparent')
        body.pack(padx=10, pady=8)
        body.grid_columnconfigure(0, minsize=160)
        body.grid_columnconfigure(1, minsize=180)

        self.status_label = ctk.CTkLabel(body, text='LagSwitch off.', text_color='red',
                                         font=('TkDefaultFont', 15, 'bold'))
        self.status_label.grid(row=0, column=0, sticky='w')
        ctk.CTkLabel(body, text='Made By kx').grid(row=0, column=1, sticky='e')

        self.keybind_label = ctk.CTkButton(body, text=f"Keybind: {self.settings['Keybind'].upper()}",
                                           command=self.change_keybind, width=140)
        self.keybind_label.grid(row=1, column=0, sticky='w', pady=4)

        self.overlay_var = ctk.BooleanVar(value=self.settings['Overlay'])
        self.always_on_top_var = ctk.BooleanVar(value=False)
        self.auto_turnoff_var = ctk.BooleanVar(value=self.settings['AutoTurnOff'])
        self.auto_turnbackon_var = ctk.BooleanVar(value=self.settings['AutoTurnBackOn'])
        ctk.CTkCheckBox(body, text='Overlay', variable=self.overlay_var,
                        command=self.toggle_status_window).grid(row=2, column=0, sticky='w', pady=4)
        ctk.CTkCheckBox(body, text='Always on Top', variable=self.always_on_top_var,
                        command=self.toggle_always_on_top).grid(row=2, column=1, sticky='w', pady=4)
        ctk.CTkCheckBox(body, text='Anti-Timeout', variable=self.auto_turnoff_var,
                        command=self.update_auto_turnoff).grid(row=3, column=0, sticky='w', pady=4)
        ctk.CTkCheckBox(body, text='Reactivate', variable=self.auto_turnbackon_var,
                        command=self.update_auto_turnbackon).grid(row=4, column=0, sticky='w', pady=4)

        t1 = ctk.CTkFrame(body, fg_color='transparent')
        t1.grid(row=3, column=1, sticky='w', pady=4)
        self.timer_slider = ctk.CTkSlider(t1, from_=0, to=10, number_of_steps=100,
                                          width=140, command=self.update_timer_duration)
        self.timer_slider.set(self.timer_duration)
        self.timer_slider.pack(side='left')
        self.timer_label = ctk.CTkLabel(t1, text=f"{self.timer_duration:.1f}s", width=36)
        self.timer_label.pack(side='left', padx=(4, 0))

        t2 = ctk.CTkFrame(body, fg_color='transparent')
        t2.grid(row=4, column=1, sticky='w', pady=4)
        self.reactivation_slider = ctk.CTkSlider(t2, from_=0, to=1, number_of_steps=10,
                                                 width=140, command=self.update_reactivation_duration)
        self.reactivation_slider.set(self.reactivation_duration)
        self.reactivation_slider.pack(side='left')
        self.reactivation_label = ctk.CTkLabel(t2, text=f"{self.reactivation_duration:.1f}s", width=36)
        self.reactivation_label.pack(side='left', padx=(4, 0))

    def toggle_status_window(self) -> None:
        if self.overlay_var.get():
            self.open_status_window()
            self.start_overlay_update()
        else:
            self.close_status_window()
            self.stop_overlay_update()

    def open_status_window(self) -> None:
        if self.status_window is None or not self.status_window.winfo_exists():
            self.status_window = ctk.CTkToplevel(self.root)
            self.status_window.overrideredirect(True)
            self.status_window.attributes('-topmost', True)
            self.status_window.attributes('-transparentcolor', self.status_window['bg'])
            self.status_window_label = ctk.CTkLabel(
                self.status_window, text='LagSwitch off.', text_color='red',
                font=('TkDefaultFont', 15, 'bold')
            )
            self.status_window_label.place(relx=0.5, rely=0.0, anchor='n', y=40)
            self.update_status_window()
            self.status_window.after(50, self.hide_overlay_from_taskbar)

    def hide_overlay_from_taskbar(self) -> None:
        
        try:
            hwnd = self.status_window.winfo_id()
            hwnd = GetParent(hwnd) or hwnd
            style = GetWindowLong(hwnd, wc.GWL_EXSTYLE)
            style = (style | wc.WS_EX_TOOLWINDOW) & ~wc.WS_EX_APPWINDOW
            SetWindowLong(hwnd, wc.GWL_EXSTYLE, style)
        except Exception:
            pass

    def close_status_window(self) -> None:
        if self.status_window and self.status_window.winfo_exists():
            self.status_window.destroy()
            self.status_window = None

    def start_overlay_update(self) -> None:
        if not self.overlay_update_thread or not self.overlay_update_thread.is_alive():
            self.overlay_update_event.clear()
            self.overlay_update_thread = threading.Thread(target=self.overlay_update_loop, daemon=True)
            self.overlay_update_thread.start()

    def stop_overlay_update(self) -> None:
        self.overlay_update_event.set()

    def overlay_update_loop(self) -> None:
        previous_rect = None
        previous_active = None
        while not self.overlay_update_event.is_set():
            self.overlay_update_event.wait(0.05)
            try:
                if self.overlay_var.get() and self.status_window and self.status_window.winfo_exists():
                    current_window = GetForegroundWindow()
                    rect = GetWindowRect(current_window)
                    _, pid = win32process.GetWindowThreadProcessId(current_window)
                    current_process = psutil.Process(pid)
                    is_roblox = current_process.name().lower() == 'robloxplayerbeta.exe'
                    if is_roblox and (previous_rect != rect or previous_active != is_roblox):
                        self.status_window.deiconify()
                        width, height = rect[2] - rect[0], rect[3] - rect[1]
                        self.status_window.geometry(f"{width}x{height}+{rect[0]}+{rect[1]}")
                        SetWindowPos(
                            self.status_window.winfo_id(), wc.HWND_TOPMOST,
                            rect[0], rect[1], width, height, wc.SWP_NOACTIVATE
                        )
                    elif not is_roblox and previous_active != is_roblox:
                        self.status_window.withdraw()
                    previous_rect = rect
                    previous_active = is_roblox
            except Exception:
                pass

    def update_status_window(self) -> None:
        status_text = 'LagSwitch on.' if self.block_flag else 'LagSwitch off.'
        status_color = 'green' if self.block_flag else 'red'
        try:
            if self.status_window and hasattr(self, "status_window_label"):
                self.status_window_label.configure(text=status_text, text_color=status_color)
        except Exception:
            pass

    def update_status_label(self) -> None:
        status_text = 'LagSwitch on.' if self.block_flag else 'LagSwitch off.'
        status_color = 'green' if self.block_flag else 'red'
        self.status_label.configure(text=status_text, text_color=status_color)
        self.update_status_window()

    def update_auto_turnoff(self) -> None:
        self.settings['AutoTurnOff'] = self.auto_turnoff_var.get()

    def update_auto_turnbackon(self) -> None:
        self.settings['AutoTurnBackOn'] = self.auto_turnbackon_var.get()

    def update_timer_duration(self, value: float) -> None:
        self.timer_duration = float(value)
        self.timer_label.configure(text=f"{self.timer_duration:.1f}s")

    def update_reactivation_duration(self, value: float) -> None:
        self.reactivation_duration = float(value)
        self.reactivation_label.configure(text=f"{self.reactivation_duration:.1f}s")

    def toggle_always_on_top(self) -> None:
        self.root.attributes('-topmost', self.always_on_top_var.get())

    def change_keybind(self) -> None:
        self.keybind_label.configure(text='Press a key...')
        self.keybind_temp_handler = keyboard.on_press(self.set_keybind)

    def set_keybind(self, event) -> None:
        new_key = event.name
        self.settings['Keybind'] = new_key
        self.keybind_label.configure(text=f"Keybind: {new_key.upper()}")
        if self.keybind_temp_handler is not None:
            keyboard.unhook(self.keybind_temp_handler)
            self.keybind_temp_handler = None
        if self.keybind_handler is not None:
            keyboard.unhook(self.keybind_handler)
            self.keybind_handler = None
        self.keybind_handler = keyboard.on_press_key(new_key, self.toggle_block)

    def activate_lagswitch(self) -> None:
        self.lagswitch_active = True
        self.manual_override = False
        self.turn_on_lag_switch()
        if self.settings['AutoTurnOff']:
            self.lagswitch_cycle_event.clear()
            self.auto_cycle_thread = threading.Thread(target=self.lagswitch_cycle_loop, daemon=True)
            self.auto_cycle_thread.start()

    def deactivate_lagswitch(self) -> None:
        self.lagswitch_active = False
        self.lagswitch_cycle_event.set()
        if self.active_timer:
            self.active_timer.cancel()
            self.active_timer = None
        self.turn_off_lag_switch()

    def lagswitch_cycle_loop(self) -> None:
        while self.lagswitch_active and not self.lagswitch_cycle_event.is_set():
            if self.lagswitch_cycle_event.wait(self.timer_duration):
                break
            self.turn_off_lag_switch()
            if self.lagswitch_cycle_event.wait(self.reactivation_duration):
                break
            if self.lagswitch_active:
                if self.settings['AutoTurnBackOn']:
                    self.turn_on_lag_switch()
                else:
                    self.lagswitch_active = False
                    self.update_status_label()
                    break

    def turn_on_lag_switch(self) -> None:
        self.block_flag = True
        self.update_firewall_rules('block')
        self.update_status_label()

    def turn_off_lag_switch(self) -> None:
        self.block_flag = False
        self.update_firewall_rules('delete')
        self.update_status_label()

    def toggle_block(self, event) -> None:
        if event.name != self.settings['Keybind']:
            return
        if self.lagswitch_active:
            self.deactivate_lagswitch()
        else:
            self.activate_lagswitch()

    def update_firewall_rules(self, action: str) -> None:
        try:
            roblox_process = next(
                (proc for proc in psutil.process_iter(['pid', 'name', 'exe'])
                 if proc.info['name'] == 'RobloxPlayerBeta.exe' and
                    proc.info.get('exe', '').lower().find('roblox') != -1),
                None
            )
            if not roblox_process:
                self.disable_lag_switch()
                return
            exe_path = roblox_process.exe()
            if action == 'block':
                cmd = ['netsh', 'advfirewall', 'firewall', 'add', 'rule',
                       f'name={RULE_NAME}', 'dir=out', 'action=block', f'program={exe_path}']
            else:
                cmd = ['netsh', 'advfirewall', 'firewall', 'delete', 'rule', f'name={RULE_NAME}']
            sp.run(cmd, creationflags=sp.CREATE_NO_WINDOW)
        except psutil.NoSuchProcess:
            self.disable_lag_switch()
        except Exception:
            pass

    def check_requirements(self) -> None:
        if not self.is_admin():
            self.show_message('Zeno requires administrator privileges to run.')
            sys.exit(1)
        if not any(proc.info['name'] == 'RobloxPlayerBeta.exe' for proc in psutil.process_iter(['name'])):
            self.show_message('Roblox is not running. Please start Roblox and try again.')
            sys.exit(1)

    def is_admin(self) -> bool:
        try:
            return bool(ct.windll.shell32.IsUserAnAdmin())
        except Exception:
            return False

    def show_message(self, message: str) -> None:
        ct.windll.user32.MessageBoxW(0, message, 'Zeno', 0)

    def disable_lag_switch(self) -> None:
        try:
            result = sp.run(['netsh', 'advfirewall', 'firewall', 'show', 'rule', 'name=all'],
                            capture_output=True, text=True)
            rules = [line.split(':')[1].strip() for line in result.stdout.splitlines() if 'Rule Name:' in line]
            for rule in rules:
                if RULE_NAME in rule:
                    sp.run(['netsh', 'advfirewall', 'firewall', 'delete', 'rule', f"name={rule}"])
        except Exception:
            pass
        if self.keybind_handler is not None:
            keyboard.unhook(self.keybind_handler)
        self.root.destroy()
        sys.exit(1)

    def setup_keybind(self) -> None:
        key = self.settings.get('Keybind', DEFAULT_KEYBIND)
        self.settings['Keybind'] = key
        self.keybind_label.configure(text=f"Keybind: {key.upper()}")
        self.keybind_handler = keyboard.on_press_key(key, self.toggle_block)

    def run(self) -> None:
        atexit.register(self.exit_handler)
        self.root.mainloop()

    def exit_handler(self) -> None:
        self.lagswitch_cycle_event.set()
        self.update_firewall_rules('delete')
        self.overlay_update_event.set()

if __name__ == '__main__':
    try:
        app = Zeno()
        app.run()
    except Exception:
        pass
