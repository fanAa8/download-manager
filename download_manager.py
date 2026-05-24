#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
下载分类管家 - Download Classifier Manager
==========================================
自动监控下载目录，基于文件名关键词+扩展名智能分类，哈希去重。

功能:
  - 监控浏览器/迅雷/百度网盘等所有下载工具的下载目录
  - 文件名关键词智能分类到对应文件夹
  - 文件名+大小快速去重 → 下载完哈希确认
  - 重复文件弹窗提醒: [跳过并打开已有] [保留副本]
  - 网盘批量下载文件夹智能识别分类

依赖: pip install watchdog
可选: pip install pystray Pillow

用法:
  python download_manager.py              # 启动监控
  python download_manager.py --init       # 仅初始化扫描
  python download_manager.py --setup      # 配置向导
  python download_manager.py --stats      # 显示统计
"""

import os, sys, json, hashlib, sqlite3, shutil, time, logging, threading, subprocess
from pathlib import Path
from collections import defaultdict
try:
    from settings_ui import setup_tray, smart_move, _show_settings_window
except ImportError:
    setup_tray = None
    _show_settings_window = None
    def smart_move(src, dst):
        try:
            shutil.move(str(src), str(dst))
            return True
        except Exception:
            return False

VERSION = "1.0.0"

try:
    from watchdog.observers import Observer
    from watchdog.events import FileSystemEventHandler
except ImportError:
    print("请安装 watchdog: pip install watchdog")
    sys.exit(1)

# ─── PATHS (PyInstaller-compatible) ───
# When bundled as exe: sys._MEIPASS is the temp extraction dir
_IMPORTANT_PYINSTALLER = hasattr(sys, "_MEIPASS")
if _IMPORTANT_PYINSTALLER:
    _ME = Path(sys._MEIPASS)
    # Config: look next to the exe first (user-editable), fallback to bundled
    _EXE_DIR = Path(sys.executable).parent
    CONFIG_FILE = _EXE_DIR / "config.json" if (_EXE_DIR / "config.json").exists() else _ME / "config.json"
    DB_FILE    = _EXE_DIR / "download_manager.db"
    LOG_FILE    = _EXE_DIR / "download_manager.log"
    BASE_DIR   = _ME
else:
    BASE_DIR   = Path(__file__).parent
    CONFIG_FILE = BASE_DIR / "config.json"
    DB_FILE    = BASE_DIR / "download_manager.db"
    LOG_FILE   = BASE_DIR / "download_manager.log"

# Ensure UTF-8 output on Windows
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
    handlers=[logging.StreamHandler(), logging.FileHandler(LOG_FILE, encoding="utf-8")]
)
log = logging.getLogger("DLM")

# ─── CONSTANTS ───
TEMP_EXTS = {".crdownload", ".td", ".part", ".partial", ".tmp", ".download", ".dl", ".bc!", ".opdownload", ".aria2"}

# On first run as exe: copy bundled config.json to exe dir for user editing
if _IMPORTANT_PYINSTALLER:
    _EXE_DIR = Path(sys.executable).parent
    _target_cfg = _EXE_DIR / "config.json"
    if not _target_cfg.exists():
        try:
            import shutil
            _bundled_cfg = Path(sys._MEIPASS) / "config.json"
            if _bundled_cfg.exists():
                shutil.copy2(_bundled_cfg, _target_cfg)
        except Exception:
            pass

DEFAULT_CONFIG = {
    "watch_folders": [], "target_base": "",
    "download_complete_wait": 5, "batch_window": 15,
    "hash_chunk_size": 8388608, "min_file_size_for_hash": 1024,
    "default_category": "其他", "categories": {}
}


# ════════════════════════════════════
#  DATABASE
# ════════════════════════════════════

class Database:
    def __init__(self, db_path: Path):
        self.db_path = db_path
        self.conn = sqlite3.connect(str(db_path), check_same_thread=False)
        self.conn.execute("PRAGMA journal_mode=WAL")
        self.conn.execute("PRAGMA synchronous=NORMAL")
        self._lock = threading.Lock()
        self._init()

    def _init(self):
        self.conn.executescript("""
            CREATE TABLE IF NOT EXISTS files (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                file_hash TEXT DEFAULT '',
                file_name TEXT NOT NULL,
                file_size INTEGER NOT NULL,
                file_path TEXT NOT NULL,
                category TEXT DEFAULT '',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
            CREATE INDEX IF NOT EXISTS idx_hash ON files(file_hash);
            CREATE INDEX IF NOT EXISTS idx_name ON files(file_name);
            CREATE INDEX IF NOT EXISTS idx_name_size ON files(file_name, file_size);
            CREATE UNIQUE INDEX IF NOT EXISTS idx_path ON files(file_path);
        """)
        self.conn.commit()

    def find_by_name(self, name: str) -> list:
        with self._lock:
            rows = self.conn.execute(
                "SELECT file_hash, file_name, file_size, file_path, category FROM files WHERE file_name=?",
                (name,)
            ).fetchall()
        return [dict(zip(["hash","name","size","path","category"], r)) for r in rows]

    def find_by_name_and_size(self, name: str, size: int) -> list:
        with self._lock:
            rows = self.conn.execute(
                "SELECT file_hash, file_name, file_size, file_path, category FROM files WHERE file_name=? AND file_size=?",
                (name, size)
            ).fetchall()
        return [dict(zip(["hash","name","size","path","category"], r)) for r in rows]

    def find_by_hash(self, h: str) -> list:
        if not h: return []
        with self._lock:
            rows = self.conn.execute(
                "SELECT file_hash, file_name, file_size, file_path, category FROM files WHERE file_hash=?",
                (h,)
            ).fetchall()
        return [dict(zip(["hash","name","size","path","category"], r)) for r in rows]

    def add_file(self, h: str, name: str, size: int, path: str, cat: str):
        with self._lock:
            self.conn.execute(
                "INSERT OR IGNORE INTO files (file_hash,file_name,file_size,file_path,category) VALUES (?,?,?,?,?)",
                (h, name, size, path, cat)
            )
            self.conn.commit()

    def remove_by_path(self, path: str):
        with self._lock:
            self.conn.execute("DELETE FROM files WHERE file_path=?", (path,))
            self.conn.commit()

    def update_path(self, old: str, new: str):
        with self._lock:
            self.conn.execute("UPDATE files SET file_path=? WHERE file_path=?", (new, old))
            self.conn.commit()

    def stats(self) -> dict:
        with self._lock:
            total = self.conn.execute("SELECT COUNT(*) FROM files").fetchone()[0]
            hashed = self.conn.execute("SELECT COUNT(*) FROM files WHERE file_hash!=''").fetchone()[0]
            cats = self.conn.execute(
                "SELECT category, COUNT(*) as c FROM files GROUP BY category ORDER BY c DESC"
            ).fetchall()
        return {"total": total, "hashed": hashed, "by_cat": {r[0] or "未分类": r[1] for r in cats}}

    def close(self):
        self.conn.close()


# ════════════════════════════════════
#  CLASSIFIER
# ════════════════════════════════════

class Classifier:
    def __init__(self, cats_config: dict, default_cat: str = "其他"):
        self.default_cat = default_cat
        self.ext_map = {}
        for cat_name, rules in cats_config.items():
            ext_list = []
            if isinstance(rules, dict):
                ext_list = rules.get("extensions", [])
            elif isinstance(rules, list):
                # Legacy format: could be ["keywords", "extensions"] or actual extensions
                ext_list = [x for x in rules if isinstance(x, str) and x.startswith(".")]
            for ext in ext_list:
                extl = ext.lower()
                if extl not in self.ext_map:
                    self.ext_map[extl] = cat_name

    def classify(self, filename: str, folder_name: str = None) -> str:
        """Classify by file extension only."""
        ext = Path(filename).suffix.lower()
        if ext in self.ext_map:
            return self.ext_map[ext]
        return self.default_cat

    def classify_folder(self, folder_path: Path) -> str:
        """Scan folder contents and determine dominant category by file extension."""
        try:
            files = list(folder_path.rglob("*"))
            if not files:
                return self.default_cat
            from collections import Counter
            cats = Counter()
            for f in files[:200]:
                if f.is_file():
                    cat = self.classify(f.name)
                    if cat and cat != self.default_cat:
                        cats[cat] += 1
            if cats:
                return cats.most_common(1)[0][0]
        except Exception:
            pass
        return self.default_cat

    def organize(self, src: str, dst: str, mode: str = "copy") -> int:
        """Scan src folder recursively, classify files, copy/move to dst/{category}/.

        Smart mode logic:
        - 1 type (>=80%): move entire folder as one unit
        - 2 types with strong correlation (music+cover art, video+subtitle, etc):
          move entire folder, classify by dominant type
        - 2 types without correlation: move files individually
        - 3+ types (likely app install dir): skip, do not touch
        - Loose files: classify individually
        """
        import shutil as _shutil
        src_path, dst_path = Path(src), Path(dst)
        if not src_path.is_dir():
            return 0
        count = 0

        # Strong correlation pairs: (category_a, category_b) -> which one wins
        # If a folder has these two types, we treat it as a single-type folder
        STRONG_CORRELATIONS = {
            ("音乐", "图片"): "音乐",           # album cover art
            ("音乐", "代码文档相关"): "音乐",    # lyrics files
            ("视频", "代码文档相关"): "视频",    # subtitles (.srt/.ass)
            ("视频", "图片"): "视频",            # video thumbnails
            ("3D打印相关", "图片"): "3D打印相关", # 3D previews
            ("3D打印相关", "代码文档相关"): "3D打印相关", # gcode/notes
            ("代码文档相关", "图片"): "代码文档相关", # project with assets
        }

        def _correlation_key(cat1, cat2):
            """Check if two categories have strong correlation. Return winner or None."""
            pair = tuple(sorted([cat1, cat2]))
            if pair in STRONG_CORRELATIONS:
                return STRONG_CORRELATIONS[pair]
            # Check reverse order too
            for (a, b), winner in STRONG_CORRELATIONS.items():
                if set([cat1, cat2]) == set([a, b]):
                    return winner
            return None

        def _is_app_folder(folder):
            """Detect if this looks like an application/program folder by scanning file extensions."""
            APP_EXTS = {".exe", ".msi", ".appx", ".msix", ".bat", ".cmd"}
            LIB_EXTS = {".dll", ".sys", ".drv", ".ocx", ".ax"}
            CFG_EXTS = {".ini", ".cfg", ".conf", ".dat"}
            has_app = False
            has_lib = False
            has_cfg = False
            total = 0
            for f in folder.rglob("*"):
                if f.is_file():
                    total += 1
                    ext = f.suffix.lower()
                    if ext in APP_EXTS:
                        has_app = True
                    elif ext in LIB_EXTS:
                        has_lib = True
                    elif ext in CFG_EXTS:
                        has_cfg = True
            if total < 2:
                return False
            # Check for uninstaller - strongest app folder indicator
            for f in folder.rglob("*"):
                if f.is_file():
                    name_lower = f.name.lower()
                    if name_lower.startswith("uninst") or name_lower.startswith("unins"):
                        return True
                    if name_lower in ("uninstall.exe", "uninstall.bat", "uninstall.sh",
                                      "remove.exe", "uninstall"):
                        return True
            # exe + dll = definitely app folder
            if has_app and has_lib:
                return True
            # exe + config = likely app folder
            if has_app and has_cfg:
                return True
            return False

        def _should_skip(cat):
            return cat == self.default_cat and mode == "smart"

        def _move_file(fpath, dest_dir):
            nonlocal count
            dest_dir.mkdir(parents=True, exist_ok=True)
            target = dest_dir / fpath.name
            if target.exists():
                stem, suffix = fpath.stem, fpath.suffix
                c2 = 1
                while target.exists():
                    c2 += 1
                    target = dest_dir / f"{stem} ({c2}){suffix}"
            try:
                if mode == "move":
                    _shutil.move(str(fpath), str(target))
                else:
                    _shutil.copy2(str(fpath), str(target))
                count += 1
            except Exception:
                pass

        def _scan_folder_stats(folder):
            """Return {category: count} for all files in folder (recursive)."""
            stats = {}
            for f in folder.rglob("*"):
                if f.is_file():
                    cat = self.classify(f.name)
                    stats[cat] = stats.get(cat, 0) + 1
            return stats

        def _move_folder_tree(folder, dest_dir):
            """Recursively move/copy all files from folder to dest_dir."""
            nonlocal count
            for f in folder.rglob("*"):
                if f.is_file():
                    rel = f.relative_to(folder)
                    target_dir = dest_dir / rel.parent
                    target_dir.mkdir(parents=True, exist_ok=True)
                    target = target_dir / f.name
                    if target.exists():
                        stem, suffix = f.stem, f.suffix
                        c2 = 1
                        while target.exists():
                            c2 += 1
                            target = target_dir / f"{stem} ({c2}){suffix}"
                    try:
                        if mode == "move":
                            _shutil.move(str(f), str(target))
                        else:
                            _shutil.copy2(str(f), str(target))
                        count += 1
                    except Exception:
                        pass

        for item in src_path.iterdir():
            if item.is_file():
                cat = self.classify(item.name)
                if _should_skip(cat):
                    continue
                _move_file(item, dst_path / cat)

            elif item.is_dir():
                stats = _scan_folder_stats(item)
                total = sum(stats.values())
                if total == 0:
                    continue

                # Remove "其他" from stats for decision making
                non_default_stats = {k: v for k, v in stats.items() if k != self.default_cat}
                non_default_count = sum(non_default_stats.values())
                types_count = len(non_default_stats)

                if mode == "smart":
                    # 3+ types -> likely app/install folder, skip entirely
                    if _is_app_folder(item):
                        continue

                    # No meaningful content (all "其他")
                    if types_count == 0:
                        continue

                    # 1 type: move entire folder
                    if types_count == 1:
                        dominant = list(non_default_stats.keys())[0]
                        dest = dst_path / dominant / item.name
                        _move_folder_tree(item, dest)
                        continue

                    # 2 types: check if one type dominates (>=70%)
                    if types_count == 2:
                        cats = list(non_default_stats.keys())
                        dominant = max(non_default_stats, key=non_default_stats.get)
                        dominant_ratio = non_default_stats[dominant] / non_default_count
                        if dominant_ratio >= 0.7:
                            # One type clearly dominates, skip correlation logic
                            dest = dst_path / dominant / item.name
                            _move_folder_tree(item, dest)
                            continue
                        winner = _correlation_key(cats[0], cats[1])
                        if winner:
                            # Strong correlation: move entire folder as one unit
                            dest = dst_path / winner / item.name
                            _move_folder_tree(item, dest)
                        else:
                            # No correlation: dominant type inherits folder name, others go flat
                            # If no type >= 50%, everyone goes flat
                            dominant = max(non_default_stats, key=non_default_stats.get)
                            dominant_ratio = non_default_stats[dominant] / non_default_count
                            inherit = dominant_ratio >= 0.5
                            for f in item.rglob("*"):
                                if f.is_file():
                                    cat = self.classify(f.name)
                                    if _should_skip(cat):
                                        continue
                                    if inherit and cat == dominant:
                                        rel = f.relative_to(item)
                                        _move_file(f, dst_path / cat / item.name / rel.parent)
                                    else:
                                        _move_file(f, dst_path / cat)
                        continue

                    # 3+ types but not app folder (mixed content):
                    # Dominant type inherits folder name, others go flat
                    # If no type >= 50%, everyone goes flat
                    dominant = max(non_default_stats, key=non_default_stats.get)
                    dominant_ratio = non_default_stats[dominant] / non_default_count
                    inherit = dominant_ratio >= 0.5
                    for f in item.rglob("*"):
                        if f.is_file():
                            cat = self.classify(f.name)
                            if _should_skip(cat):
                                continue
                            if inherit and cat == dominant:
                                rel = f.relative_to(item)
                                _move_file(f, dst_path / cat / item.name / rel.parent)
                            else:
                                _move_file(f, dst_path / cat)

                else:
                    # copy/move mode: always move individual files, keep structure
                    for f in item.rglob("*"):
                        if f.is_file():
                            cat = self.classify(f.name)
                            rel = f.relative_to(item)
                            _move_file(f, dst_path / cat / rel.parent)

        return count


# ════════════════════════════════════
#  UTILITIES
# ════════════════════════════════════

def calc_hash(filepath: Path, chunk_size: int = 8388608) -> str:
    """Calculate SHA256 hash of a file"""
    h = hashlib.sha256()
    try:
        with open(filepath, "rb") as f:
            while True:
                chunk = f.read(chunk_size)
                if not chunk: break
                h.update(chunk)
    except: return ""
    return h.hexdigest()

def is_temp_file(filepath: Path) -> bool:
    """Check if file is a download temp file"""
    name = filepath.name.lower()
    if filepath.suffix.lower() in TEMP_EXTS: return True
    for pat in (".crdownload", ".td", ".part", ".opdownload", ".download", ".bc!", ".aria2"):
        if name.endswith(pat): return True
    if name.startswith(".") or name.startswith("~"): return True
    return False

def open_file_location(filepath: Path):
    """Open Explorer and select file (fixes jump bug)."""
    fp = str(filepath.resolve())
    try:
        import ctypes
        ctypes.windll.shell32.ShellExecuteW(0, "open", "explorer.exe", f'/select,"{fp}"', None, 1)
    except Exception:
        try:
            import subprocess
            subprocess.run(f'explorer /select,"{fp}"', shell=True, timeout=10)
        except Exception:
            pass

def show_toast(title: str, msg: str):
    """Windows toast notification"""
    try:
        ps = (
            'Add-Type -AssemblyName System.Windows.Forms; '
            '$n = New-Object System.Windows.Forms.NotifyIcon; '
            f'$n.BalloonTipTitle = "{title}"; '
            f'$n.BalloonTipText = "{msg}"; '
            '$n.Icon = [System.Drawing.SystemIcons]::Information; '
            '$n.Visible = $true; '
            '$n.ShowBalloonTip(3000); '
            'Start-Sleep -Seconds 4; '
            '$n.Dispose()'
        )
        subprocess.run(["powershell", "-Command", ps], capture_output=True, timeout=10, check=False, creationflags=subprocess.CREATE_NO_WINDOW)
    except: pass


# ════════════════════════════════════
#  THEME HELPERS (Win11 dark/light detection)
# ════════════════════════════════════

def _detect_win_theme() -> str:
    """Detect Windows light/dark theme via Registry."""
    try:
        import winreg
        key = winreg.OpenKey(
            winreg.HKEY_CURRENT_USER,
            r"Software\Microsoft\Windows\CurrentVersion\Themes\Personalize"
        )
        val, _ = winreg.QueryValueEx(key, "AppsUseLightTheme")
        winreg.CloseKey(key)
        return "light" if val == 1 else "dark"
    except Exception:
        return "light"


def _get_sys_accent() -> tuple:
    """Get Windows accent color as (R,G,B), or None."""
    try:
        import winreg
        key = winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Software\Microsoft\Windows\DWM")
        val, _ = winreg.QueryValueEx(key, "ColorizationColor")
        winreg.CloseKey(key)
        b = (val >> 24) & 0xFF
        g = (val >> 16) & 0xFF
        r = (val >> 8) & 0xFF
        return (r, g, b)
    except Exception:
        return None


def _set_dark_titlebar(root):
    """Enable dark title bar via DwmSetWindowAttribute."""
    try:
        import ctypes
        hwnd = root.winfo_id()
        ctypes.windll.dwmapi.DwmSetWindowAttribute(
            hwnd, 20,
            ctypes.byref(ctypes.c_int(1)),
            ctypes.sizeof(ctypes.c_int())
        )
    except Exception:
        pass


# ════════════════════════════════════
#  DUPLICATE DIALOG (Win11-flavored)
# ════════════════════════════════════

def dup_dialog(new_name: str, new_path: Path, existing: dict, timeout_sec: int = 60) -> str:
    """Win11-styled duplicate file dialog with light/dark theme support."""
    result = {"action": None}
    theme = _detect_win_theme()
    dark = (theme == "dark")
    accent_rgb = _get_sys_accent()

    # Win11 color palette
    if dark:
        BG       = "#1F1F1F"
        SURFACE  = "#2C2C2C"
        FG       = "#F0F0F0"
        FG_SEC   = "#AAAAAA"
        BTN_BG   = "#3B3B3B"
        BTN_HOVER = "#505050"
        DANGER   = "#FF99A4"
        SEP      = "#383838"
        HINT     = "#7A7A7A"
    else:
        BG       = "#F3F3F3"
        SURFACE  = "#FFFFFF"
        FG       = "#1A1A1A"
        FG_SEC   = "#616161"
        BTN_BG   = "#E0E0E0"
        BTN_HOVER = "#D4D4D4"
        DANGER   = "#C42B1C"
        SEP      = "#E8E8E8"
        HINT     = "#8A8A8A"

    if accent_rgb:
        r, g, b = accent_rgb
        ACCENT = f"#{r:02X}{g:02X}{b:02X}"
        ACCENT_HOVER = f"#{max(r-30,0):02X}{max(g-30,0):02X}{max(b-30,0):02X}"
    else:
        ACCENT      = "#0078D4" if not dark else "#60CDFF"
        ACCENT_HOVER = "#005A9E" if not dark else "#3BB5E0"

    def _tk():
        try:
            import tkinter as tk

            root = tk.Tk()
            root.withdraw()  # hide while building UI, prevents flash
            root.title("检测到重复文件")
            root.configure(bg=BG)
            root.attributes("-topmost", True)
            root.resizable(False, False)
            if dark:
                _set_dark_titlebar(root)

            W, H = 540, 330
            root.update_idletasks()
            x = (root.winfo_screenwidth()  - W) // 2
            y = (root.winfo_screenheight() - H) // 2
            root.geometry(f"{W}x{H}+{x}+{y}")

            # Title bar
            title_fr = tk.Frame(root, bg=BG, height=48)
            title_fr.pack(fill="x")
            title_fr.pack_propagate(False)

            tk.Label(title_fr, text="\u26a0", font=("Segoe UI", 20),
                     bg=BG, fg=DANGER).pack(side="left", padx=(24, 10), pady=8)
            tk.Label(title_fr, text="检测到重复文件",
                     font=("Microsoft YaHei UI", 13, "bold"),
                     bg=BG, fg=FG).pack(side="left", pady=8)

            tk.Frame(root, bg=SEP, height=1).pack(fill="x")

            # Content card
            content = tk.Frame(root, bg=SURFACE)
            content.pack(fill="both", expand=True, padx=20, pady=(14, 6))

            size_mb = existing["size"] / 1048576
            ep = existing["path"]
            display = ("\u2026" + ep[-50:]) if len(ep) > 53 else ep

            rows = [
                ("文件名",   new_name),
                ("大小",     f"{size_mb:.1f} MB"),
                ("已有文件", display),
                ("分类",     existing.get("category", "\u2014")),
            ]

            rc = tk.Frame(content, bg=SURFACE)
            rc.pack(fill="x", padx=16, pady=(14, 4))

            for lbl, val in rows:
                rf = tk.Frame(rc, bg=SURFACE)
                rf.pack(fill="x", pady=(0, 10))
                tk.Label(rf, text=lbl, font=("Microsoft YaHei UI", 9),
                         fg=FG_SEC, bg=SURFACE, anchor="w", width=8
                ).pack(side="left")
                vl = tk.Label(rf, text=val, font=("Microsoft YaHei UI", 9),
                              fg=FG, bg=SURFACE, anchor="w")
                vl.pack(side="left", fill="x", expand=True, padx=(6, 0))
                if len(val) > 60:
                    vl.configure(wraplength=380)

            tk.Label(content,
                     text=f"\U0001f4a1  {timeout_sec}秒后自动选择\u300c保留副本\u300d",
                     font=("Microsoft YaHei UI", 8),
                     fg=HINT, bg=SURFACE
            ).pack(anchor="w", padx=16, pady=(2, 12))

            tk.Frame(root, bg=SEP, height=1).pack(fill="x")

            # Button bar
            btn_bar = tk.Frame(root, bg=BG, height=54)
            btn_bar.pack(fill="x", side="bottom")
            btn_bar.pack_propagate(False)
            btn_inner = tk.Frame(btn_bar, bg=BG)
            btn_inner.pack(side="right", padx=20, pady=10)

            def make_btn(parent, text, bg_c, fg_c, hover_c, cmd):
                b = tk.Button(parent, text=text, font=("Microsoft YaHei UI", 9),
                              bg=bg_c, fg=fg_c, activebackground=hover_c,
                              activeforeground=fg_c, relief="flat", bd=0,
                              padx=20, pady=5, cursor="hand2",
                              highlightthickness=0, command=cmd)
                def on_enter(e, b=b, h=hover_c):
                    b.configure(bg=h)
                def on_leave(e, b=b, c=bg_c):
                    b.configure(bg=c)
                b.bind("<Enter>", on_enter)
                b.bind("<Leave>", on_leave)
                return b

            def on_skip():
                result["action"] = "skip"
                root.destroy()

            def on_keep():
                result["action"] = "keep"
                root.destroy()

            make_btn(btn_inner, "  跳过 \u00b7 打开已有文件  ",
                     BTN_BG, FG, BTN_HOVER, on_skip
            ).pack(side="left", padx=(0, 8))

            make_btn(btn_inner, "  保留副本  ",
                     ACCENT, "#FFFFFF", ACCENT_HOVER, on_keep
            ).pack(side="left")

            root.bind("<Escape>", lambda e: on_skip())
            root.bind("<Return>", lambda e: on_keep())
            root.protocol("WM_DELETE_WINDOW", on_keep)
            root.after(timeout_sec * 1000,
                       lambda: (result.setdefault("action", "keep"), root.destroy()))
            root.deiconify()  # show fully-built window
            root.mainloop()

        except Exception as e:
            log.error(f"Dialog error: {e}")
            result.setdefault("action", "keep")

    t = threading.Thread(target=_tk, daemon=True)
    t.start()
    t.join(timeout_sec + 5)
    return result.get("action", "keep")


# ════════════════════════════════════
#  DOWNLOAD HANDLER
# ════════════════════════════════════

class DownloadHandler(FileSystemEventHandler):
    def __init__(self, db: Database, classifier: Classifier, config: dict):
        super().__init__()
        self.db = db
        self.classifier = classifier
        self.config = config
        self.target = Path(config["target_base"])
        self.processing = set()
        self.p_lock = threading.Lock()
        self.dialog_lock = threading.Lock()

    def on_created(self, event):
        if event.is_directory:
            t = threading.Thread(target=self._handle_batch_folder, args=(Path(event.src_path),), daemon=True)
            t.start()
        else:
            fp = Path(event.src_path)
            if not is_temp_file(fp):
                self._handle_file(fp)

    def on_moved(self, event):
        """Temp file renamed = download complete"""
        if event.is_directory: return
        src, dst = Path(event.src_path), Path(event.dest_path)
        if is_temp_file(src) and not is_temp_file(dst):
            self._handle_file(dst)

    def _handle_file(self, fp: Path):
        with self.p_lock:
            if str(fp) in self.processing: return
            self.processing.add(str(fp))

        try:
            rel = fp.relative_to(self.target)
            if rel.parts and rel.parts[0] in self.config.get("categories", {}):
                with self.p_lock: self.processing.discard(str(fp))
                return
        except ValueError: pass

        t = threading.Thread(target=self._process_file, args=(fp,), daemon=True)
        t.start()

    def _handle_batch_folder(self, folder: Path):
        """Detect cloud drive batch folder downloads"""
        time.sleep(self.config.get("batch_window", 15))
        if not folder.exists(): return

        try:
            rel = folder.relative_to(self.target)
            if rel.parts and rel.parts[0] in self.config.get("categories", {}): return
        except ValueError: pass

        cat = self.classifier.classify_folder(folder)
        default_cat = self.config.get("default_category", "其他")

        dest = self.target / cat / folder.name
        if dest.exists():
            c = 1
            while dest.exists():
                c += 1
                dest = self.target / cat / f"{folder.name} ({c})"

        try:
            smart_move(folder, dest)
            if cat == default_cat:
                log.info(f"📂 无法判定: {folder.name} → 其他")
            else:
                log.info(f"📦 文件夹归类: {folder.name} → {cat}/")
            show_toast("批量文件夹已分类", f"{folder.name} → {cat}")
            for f in dest.rglob("*"):
                if f.is_file() and not is_temp_file(f):
                    try:
                        info = f.stat()
                        self.db.add_file("", f.name, info.st_size, str(f), cat)
                    except: pass
        except Exception as e:
            log.error(f"移动文件夹失败: {e}")

    def _process_file(self, fp: Path):
        try:
            if not fp.exists(): return

            name = fp.name
            early_matches = self.db.find_by_name(name)

            if not self._wait_complete(fp):
                log.debug(f"文件未完成或已消失: {name}")
                return

            if not fp.exists(): return
            info = fp.stat()
            size = info.st_size
            if size == 0: return

            dup_action = self._check_duplicate(fp, name, size, early_matches)
            if dup_action == "skip":
                return
            elif dup_action == "rename":
                fp, name = self._do_rename(fp, name)

            cat = self.classifier.classify(name)
            log.info(f"📋 {name} → {cat}")

            dest = self.target / cat
            dest.mkdir(parents=True, exist_ok=True)
            target = dest / name
            if target.exists():
                stem, suffix = Path(name).stem, Path(name).suffix
                c = 1
                while target.exists():
                    c += 1
                    target = dest / f"{stem} ({c}){suffix}"

            try:
                smart_move(fp, target)
                fp2 = str(target)
                log.info(f"✅ 已移动: {name} → {cat}/")
            except Exception as e:
                log.error(f"移动失败: {e}")
                return

            h = ""
            if size >= self.config.get("min_file_size_for_hash", 1024):
                try: h = calc_hash(target, self.config.get("hash_chunk_size", 8388608))
                except: pass
            self.db.add_file(h, name, size, fp2, cat)
            show_toast("文件已分类", f"{name} → {cat}")

        except Exception as e:
            log.error(f"处理出错 {fp}: {e}")
        finally:
            with self.p_lock: self.processing.discard(str(fp))

    def _check_duplicate(self, fp: Path, name: str, size: int, early_matches: list) -> str:
        """Check duplicates. Returns 'skip', 'rename', or '' """
        precise = self.db.find_by_name_and_size(name, size)
        existing = precise[0] if precise else (early_matches[0] if early_matches else None)
        if not existing: return ""

        log.warning(f"📣 疑似重复: {name} ({size/1048576:.1f}MB)")
        log.warning(f"  已有: {existing['path']}")

        h = ""
        min_hash = self.config.get("min_file_size_for_hash", 1024)
        if size >= min_hash:
            try: h = calc_hash(fp, self.config.get("hash_chunk_size", 8388608))
            except: pass

        hash_confirmed = False
        if h and existing.get("hash"):
            hash_confirmed = (h == existing["hash"])
        elif h:
            matches = self.db.find_by_hash(h)
            hash_confirmed = bool(matches)

        status = "✅ 哈希确认重复" if hash_confirmed else "⚠️ 仅文件名大小匹配"
        log.info(f"  {status}")

        with self.dialog_lock:
            action = dup_dialog(name, fp, existing)

        if action == "skip":
            try:
                fp.unlink()
                log.info(f"❌ 已删除重复: {name}")
            except: pass
            open_file_location(Path(existing["path"]))
            show_toast("已跳过重复", existing["path"])
            return "skip"
        else:
            show_toast("保留副本", f"{name} → 自动重命名")
            return "rename"

    def _do_rename(self, fp: Path, name: str) -> tuple:
        stem = Path(name).stem
        suffix = Path(name).suffix
        c = 2
        while True:
            new_name = f"{stem} ({c}){suffix}"
            np = fp.parent / new_name
            if not np.exists():
                try:
                    fp.rename(np)
                    log.info(f"📝 重命名: {name} → {new_name}")
                    return np, new_name
                except: pass
            c += 1

    def _wait_complete(self, fp: Path) -> bool:
        max_wait = 1800
        interval = 2
        stable_needed = max(1, self.config.get("download_complete_wait", 5) // interval)
        stable = 0
        last = -1

        for _ in range(max_wait // interval):
            if not fp.exists(): return False
            try: cur = fp.stat().st_size
            except: time.sleep(interval); continue

            if cur == last and cur > 0:
                stable += 1
                if stable >= stable_needed:
                    try:
                        with open(fp, "rb") as f: f.read(1)
                        return True
                    except (IOError, OSError):
                        stable = 0
            else:
                stable = 0
            last = cur
            time.sleep(interval)
        log.warning(f"等待下载超时: {fp.name}")
        return fp.exists()


# ════════════════════════════════════
#  INITIAL SCANNER
# ════════════════════════════════════

def initial_scan(base: Path, cats: dict, db: Database):
    """Scan existing category folders and index files"""
    log.info("🔍 初始扫描已有分类文件...")
    count = 0
    for cat_name in cats:
        d = base / cat_name
        if not d.exists(): continue
        for f in d.rglob("*"):
            if f.is_file() and not is_temp_file(f):
                try:
                    info = f.stat()
                    db.add_file("", f.name, info.st_size, str(f), cat_name)
                    count += 1
                except: pass
    log.info(f"✅ 初始扫描完成，已索引 {count} 个文件")
    stats = db.stats()
    for cat, cnt in sorted(stats["by_cat"].items(), key=lambda x: x[1], reverse=True)[:12]:
        log.info(f"  {cat}: {cnt}")


# ════════════════════════════════════
#  CONFIG
# ════════════════════════════════════

def load_config() -> dict:
    if CONFIG_FILE.exists():
        with open(CONFIG_FILE, "r", encoding="utf-8") as f:
            cfg = json.load(f)
        for k, v in DEFAULT_CONFIG.items():
            if k not in cfg: cfg[k] = v
        return cfg
    cfg = DEFAULT_CONFIG.copy()
    save_config(cfg)
    return cfg

def save_config(cfg: dict):
    CONFIG_FILE.parent.mkdir(parents=True, exist_ok=True)
    with open(CONFIG_FILE, "w", encoding="utf-8") as f:
        json.dump(cfg, f, ensure_ascii=False, indent=2)


# ════════════════════════════════════
#  SETUP WIZARD
# ════════════════════════════════════

def setup_wizard():
    print("=" * 50)
    print(f"  📥 下载分类管家 v{VERSION} - 配置向导")
    print("=" * 50)
    print()

    cfg = load_config()

    print("请输入要监控的下载目录（多个用逗号分隔）:")
    default = ",".join(cfg.get("watch_folders", ["D:\\Users\\Downloads"]))
    inp = input(f"[{default}]: ").strip()
    cfg["watch_folders"] = [w.strip() for w in (inp or default).split(",") if w.strip()]

    print()
    print("分类文件的存放根目录（新下载的文件会被分类到这里）:")
    default = cfg["watch_folders"][0] if cfg["watch_folders"] else cfg.get("target_base", "")
    inp = input(f"[{default}]: ").strip() or default
    cfg["target_base"] = inp

    save_config(cfg)

    base = Path(cfg["target_base"])
    print("\n创建分类文件夹...")
    for cat in cfg["categories"]:
        d = base / cat
        if not d.exists():
            d.mkdir(parents=True, exist_ok=True)
            print(f"  ✓ {cat}")
        else:
            print(f"  - {cat} (已存在)")

    print(f"\n配置已保存: {CONFIG_FILE}")
    print("运行 python download_manager.py 启动监控\n")


# ════════════════════════════════════
#  MAIN
# ════════════════════════════════════

def main():
    import argparse

    # ── Single-instance lock (Windows mutex) ──
    _already_running = False
    try:
        import ctypes
        h = ctypes.windll.kernel32.CreateMutexW(None, False, "DownloadManager_v1")
        if ctypes.windll.kernel32.GetLastError() == 183:
            _already_running = True
    except Exception:
        pass

    if _already_running:
        try:
            import tkinter as tk
            from tkinter import messagebox
            root = tk.Tk()
            root.withdraw()
            messagebox.showerror("下载分类管家", "程序已经在运行中！\n\n如果看不到窗口，请检查系统托盘。")
            root.destroy()
        except Exception:
            pass
        sys.exit(1)

    p = argparse.ArgumentParser(description="下载分类管家")
    p.add_argument("--setup", action="store_true", help="配置向导")
    p.add_argument("--init", action="store_true", help="仅初始化扫描，不启动监控")
    p.add_argument("--stats", action="store_true", help="显示统计信息")
    p.add_argument("--debug", action="store_true", help="调试模式")
    args = p.parse_args()

    if args.debug:
        log.setLevel(logging.DEBUG)

    if args.setup:
        setup_wizard()
        return

    cfg = load_config()
    if not cfg.get("watch_folders") or not cfg.get("target_base"):
        log.info("首次运行，打开设置…")
        _show_settings_window(cfg, cfg_path=CONFIG_FILE)
        cfg = load_config()

    db = Database(DB_FILE)
    base = Path(cfg["target_base"])

    if args.stats:
        stats = db.stats()
        print(f"\n📊 统计: {stats['total']} 文件 ({stats['hashed']} 已哈希)")
        for cat, cnt in stats["by_cat"].items():
            print(f"  {cat}: {cnt}")
        db.close()
        return

    if args.init:
        log.info("📊 初始化扫描中...")
        initial_scan(base, cfg["categories"], db)
        log.info("✅ 初始化扫描完成")
        db.close()
        return

    log.info(f"🚀 下载分类管家 v{VERSION} 启动")

    scanner = threading.Thread(target=initial_scan, args=(base, cfg["categories"], db), daemon=True)
    scanner.start()

    classifier = Classifier(cfg["categories"], cfg.get("default_category", "📂 其他"))
    handler = DownloadHandler(db, classifier, cfg)
    observer = Observer()

    for wf in cfg["watch_folders"]:
        if os.path.exists(wf):
            observer.schedule(handler, wf, recursive=True)
            log.info(f"👀 监控: {wf}")
        else:
            log.warning(f"⚠️ 目录不存在: {wf}")

    observer.start()
    log.info("✅ 运行中，按 Ctrl+C 退出")

    if setup_tray:
        setup_tray(db, classifier, cfg, observer, log, version=VERSION, cfg_path=CONFIG_FILE)
    else:
        log.info("🖥️ 系统托盘不可用，按 Ctrl+C 退出")
        try:
            while True:
                time.sleep(1)
        except KeyboardInterrupt:
            pass
        finally:
            log.info("🚪 正在退出...")
            observer.stop()
            observer.join(timeout=5)
            db.close()
            log.info("👋 已退出")


if __name__ == "__main__":
    main()