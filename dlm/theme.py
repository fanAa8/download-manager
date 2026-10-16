"""Windows 明暗主题和强调色。其他系统使用浅色。"""

from __future__ import annotations

import sys
from dataclasses import dataclass


@dataclass(frozen=True)
class Palette:
    dark: bool
    bg: str
    surface: str
    fg: str
    muted: str
    button: str
    button_hover: str
    border: str
    accent: str
    accent_hover: str
    danger: str
    warning_bg: str
    warning_border: str
    entry: str
    hint: str
    select_fg: str


def detect_theme() -> str:
    if sys.platform != "win32":
        return "light"
    try:
        import winreg

        with winreg.OpenKey(
            winreg.HKEY_CURRENT_USER,
            r"Software\Microsoft\Windows\CurrentVersion\Themes\Personalize",
        ) as key:
            value, _ = winreg.QueryValueEx(key, "AppsUseLightTheme")
        return "light" if value == 1 else "dark"
    except Exception:
        return "light"


def accent_color() -> str | None:
    if sys.platform != "win32":
        return None
    try:
        import winreg

        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Software\Microsoft\Windows\DWM") as key:
            value, _ = winreg.QueryValueEx(key, "AccentColor")
        red = value & 0xFF
        green = (value >> 8) & 0xFF
        blue = (value >> 16) & 0xFF
        return f"#{red:02X}{green:02X}{blue:02X}"
    except Exception:
        return None


def _darken(hex_color: str) -> str:
    red = max(0, int(hex_color[1:3], 16) - 28)
    green = max(0, int(hex_color[3:5], 16) - 28)
    blue = max(0, int(hex_color[5:7], 16) - 28)
    return f"#{red:02X}{green:02X}{blue:02X}"


def palette() -> Palette:
    dark = detect_theme() == "dark"
    accent = accent_color() or ("#4CC2FF" if dark else "#0067C0")
    if dark:
        return Palette(
            dark=True,
            bg="#202020",
            surface="#2D2D2D",
            fg="#F3F3F3",
            muted="#B4B4B4",
            button="#3B3B3B",
            button_hover="#4A4A4A",
            border="#3D3D3D",
            accent=accent,
            accent_hover=_darken(accent),
            danger="#FF99A4",
            warning_bg="#3A2424",
            warning_border="#6B3030",
            entry="#1F1F1F",
            hint="#8A8A8A",
            select_fg="#FFFFFF",
        )
    return Palette(
        dark=False,
        bg="#F3F3F3",
        surface="#FFFFFF",
        fg="#1A1A1A",
        muted="#5C5C5C",
        button="#E5E5E5",
        button_hover="#D6D6D6",
        border="#E0E0E0",
        accent=accent,
        accent_hover=_darken(accent),
        danger="#C42B1C",
        warning_bg="#FFF4F4",
        warning_border="#F0B8B8",
        entry="#FFFFFF",
        hint="#6B6B6B",
        select_fg="#FFFFFF",
    )


def apply_titlebar(root, dark: bool) -> None:
    if sys.platform != "win32" or not dark:
        return
    try:
        import ctypes

        root.update_idletasks()
        hwnd = ctypes.windll.user32.GetParent(root.winfo_id()) or root.winfo_id()
        value = ctypes.c_int(1)
        for attribute in (20, 19):
            ctypes.windll.dwmapi.DwmSetWindowAttribute(
                hwnd, attribute, ctypes.byref(value), ctypes.sizeof(value)
            )
    except Exception:
        pass


def font(size: int = 10, bold: bool = False):
    return ("Microsoft YaHei UI", size, "bold" if bold else "normal")
