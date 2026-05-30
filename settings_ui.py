#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""System tray icon + Settings UI for Download Manager."""

import os, sys, json, threading, time, shutil, subprocess, copy
from pathlib import Path
from tkinter import ttk, messagebox, filedialog
import tkinter as tk

try:
    import pystray
    from PIL import Image, ImageDraw
    HAS_TRAY = True
except ImportError:
    HAS_TRAY = False

_STARTUP_PATH = Path(os.environ.get("APPDATA", ".")) / "Microsoft" / "Windows" / "Start Menu" / "Programs" / "Startup" / "\u4e0b\u8f7d\u5206\u7c7b\u7ba1\u5bb6.lnk"
_settings_win_ref = None
_tray_open_lock = threading.Lock()
_tray_lock_holder = False


def _detect_win_theme():
    try:
        import winreg
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Software\Microsoft\Windows\CurrentVersion\Themes\Personalize") as k:
            val, _ = winreg.QueryValueEx(k, "AppsUseLightTheme")
        return "dark" if val == 0 else "light"
    except Exception:
        return "light"


def _get_accent_color():
    try:
        import winreg
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Software\Microsoft\Windows\DWM") as k:
            val, _ = winreg.QueryValueEx(k, "AccentColor")
            r = val & 0xFF; g = (val >> 8) & 0xFF; b = (val >> 16) & 0xFF
            return f"#{r:02X}{g:02X}{b:02X}"
    except Exception:
        return "#0078D4"


def _set_dark_titlebar(root):
    try:
        import ctypes
        hwnd = root.winfo_id()
        ctypes.windll.dwmapi.DwmSetWindowAttribute(hwnd, 20, ctypes.byref(ctypes.c_int(1)), 4)
        root.update()
    except Exception:
        pass


def _is_autostart():
    return _STARTUP_PATH.exists()


def _set_autostart(enable):
    if enable:
        try:
            exe = sys.executable
            tmp = os.path.join(os.environ.get("TEMP", "."), "_dm_shortcut.ps1")
            sc = str(_STARTUP_PATH)
            with open(tmp, "w", encoding="utf-8") as f2:
                f2.write("$ws = New-Object -ComObject WScript.Shell\n")
                f2.write(f"$sc = $ws.CreateShortcut('{sc}')\n")
                f2.write(f"$sc.TargetPath = '{exe}'\n")
                f2.write(f"$sc.WorkingDirectory = '{str(Path(exe).parent)}'\n")
                f2.write("$sc.Save()\n")
            subprocess.run(["powershell", "-ExecutionPolicy", "Bypass", "-File", tmp], capture_output=True, timeout=10)
            os.unlink(tmp)
        except Exception:
            pass
    else:
        try:
            _STARTUP_PATH.unlink(missing_ok=True)
        except Exception:
            pass


def smart_move(src, dst):
    try:
        if isinstance(src, str): src = Path(src)
        if isinstance(dst, str): dst = Path(dst)
        if src.drive == dst.drive: shutil.move(str(src), str(dst))
        else: shutil.copy2(str(src), str(dst)); src.unlink()
        return True
    except Exception:
        return False


def _show_settings_window(cfg, cfg_path=None, log=None, version=None):
    global _settings_win_ref, _tray_open_lock, _tray_lock_holder
    if _settings_win_ref is not None:
        try:
            if _settings_win_ref.winfo_exists():
                _settings_win_ref.deiconify(); _settings_win_ref.lift(); _settings_win_ref.focus_force()
                return {"applied": False, "config": None}
        except Exception: pass

    if cfg_path is None:
        cfg_path = (Path(sys.executable).parent if hasattr(sys, "_MEIPASS") else Path(__file__).parent) / "config.json"
    cfg_path = Path(cfg_path)
    result = {"applied": False, "config": None}
    new_cfg = copy.deepcopy(cfg)
    if "categories" not in new_cfg: new_cfg["categories"] = {}
    if "\u5176\u4ed6" not in new_cfg["categories"]: new_cfg["categories"]["\u5176\u4ed6"] = []

    if "watch_path" in new_cfg and new_cfg["watch_path"]:
        wf = new_cfg["watch_path"]
        if wf not in new_cfg.get("watch_folders", []):
            new_cfg.setdefault("watch_folders", []).append(wf)
        del new_cfg["watch_path"]

    theme = _detect_win_theme()
    dark = (theme == "dark")
    BG = "#1E1E1E" if dark else "#F3F3F3"
    FG = "#E8E8E8" if dark else "#1A1A1A"
    BTN_BG = "#3B3B3B" if dark else "#E0E0E0"
    ACCENT = _get_accent_color()
    ENTRY_BG = "#2D2D2D" if dark else "#FFFFFF"
    CARD_BG = "#2A2A2A" if dark else "#EBEBEB"
    TAG_BG = "#3A3A3A" if dark else "#D6D6D6"
    TAG_FG = "#C0C0C0" if dark else "#444444"
    MUTED = "#8A8A8A" if dark else "#707070"
    BORDER = "#3A3A3A" if dark else "#D0D0D0"
    WARNING_BG = "#2B1B1B" if dark else "#FFF4F4"
    WARNING_BORDER = "#663030" if dark else "#F0B8B8"
    DEL_BTN = "#E53935"
    SAVE_BTN = "#2E7D32"
    LIST_SEL_BG = ACCENT
    LIST_SEL_FG = "white"

    root = tk.Tk()
    root.withdraw()  # Hide immediately to prevent flash
    _settings_win_ref = root
    root.title("\u4e0b\u8f7d\u5206\u7c7b\u7ba1\u5bb6 - \u8bbe\u7f6e")
    root.configure(bg=BG); root.resizable(True, True); root.overrideredirect(False)
    _set_dark_titlebar(root)
    root.update_idletasks()
    sw, sh = root.winfo_screenwidth(), root.winfo_screenheight()
    w, h = 700, 580
    root.geometry(f"{w}x{h}+{(sw-w)//2}+{(sh-h)//2}")
    root.minsize(640, 560)

    def _on_close():
        global _settings_win_ref, _tray_open_lock, _tray_lock_holder
        try:
            if _tray_lock_holder:
                _tray_open_lock.release(); _tray_lock_holder = False
        except Exception: pass
        root.quit(); root.destroy(); _settings_win_ref = None
    root.protocol("WM_DELETE_WINDOW", _on_close)

    main = tk.Frame(root, bg=BG)
    main.pack(fill="both", expand=True)
    nav = tk.Frame(main, bg=BG)
    nav.pack(fill="x", padx=20, pady=(12, 0))
    body = tk.Frame(main, bg=BG, highlightbackground=BORDER, highlightthickness=1)
    body.pack(fill="both", expand=True, padx=0, pady=(0, 0))
    tab_buttons = {}

    # ================================================================
    # Tab 1: Categories - left list + right detail
    # ================================================================
    tab_cat = tk.Frame(body, bg=BG)

    # Paned layout
    pane = tk.Frame(tab_cat, bg=BG)
    pane.pack(fill="both", expand=True, padx=12, pady=10)

    # -- Left: category list --
    left = tk.Frame(pane, bg=BG, width=180)
    left.pack(side="left", fill="y", padx=(0, 8))
    left.pack_propagate(False)

    tk.Label(left, text="\u5206\u7c7b\u5217\u8868", font=("Microsoft YaHei UI", 9, "bold"),
             bg=BG, fg=MUTED).pack(anchor="w", pady=(0, 4))

    lb_frame = tk.Frame(left, bg=BG)
    lb_frame.pack(fill="both", expand=True)

    cat_listbox = tk.Listbox(lb_frame, bg=ENTRY_BG, fg=FG, selectbackground=LIST_SEL_BG,
                             selectforeground=LIST_SEL_FG, font=("Microsoft YaHei UI", 10),
                             relief="flat", highlightbackground=BORDER, highlightthickness=1,
                             activestyle="none", bd=0, selectmode="single")
    cat_listbox.pack(fill="both", expand=True)

    # -- Left: add/delete buttons --
    btn_left = tk.Frame(left, bg=BG)
    btn_left.pack(fill="x", pady=(6, 0))

    # -- Right: detail panel --
    right = tk.Frame(pane, bg=BG)
    right.pack(side="left", fill="both", expand=True)

    detail_frame = tk.Frame(right, bg=CARD_BG, highlightbackground=BORDER, highlightthickness=1)
    detail_frame.pack(fill="both", expand=True)

    # Detail inner content (rebuilt on selection)
    detail_inner = tk.Frame(detail_frame, bg=CARD_BG)
    detail_inner.pack(fill="both", expand=True, padx=16, pady=16)
    detail_state = {"cname": None, "name_var": None, "ext_text": None}

    def _category_exts(cname):
        data = new_cfg["categories"].get(cname, [])
        if isinstance(data, dict):
            return list(data.get("extensions", []))
        if isinstance(data, list):
            return list(data)
        return []

    def _parse_exts(raw):
        for sep in [",", "\uff0c", ";", "\uff1b", "\n", "\t"]:
            raw = raw.replace(sep, " ")
        exts, seen = [], set()
        for item in raw.split():
            ext = item.strip().lower()
            if not ext:
                continue
            ext = ext if ext.startswith(".") else "." + ext
            if ext != "." and ext not in seen:
                exts.append(ext)
                seen.add(ext)
        return exts

    def _format_exts(exts):
        return " ".join(exts)

    def _refresh_list(selected_name=None):
        if selected_name is None:
            sel = cat_listbox.curselection()
            if sel:
                idx = sel[0]
                names = list(new_cfg["categories"].keys())
                if 0 <= idx < len(names):
                    selected_name = names[idx]
        cat_listbox.delete(0, tk.END)
        for name in new_cfg["categories"]:
            cat_listbox.insert(tk.END, name)
        cat_listbox.selection_clear(0, tk.END)
        if selected_name:
            names = list(new_cfg["categories"].keys())
            if selected_name in names:
                idx = names.index(selected_name)
                cat_listbox.selection_set(idx)
                cat_listbox.see(idx)

    def _replace_category(old_name, new_name, exts):
        rebuilt = {}
        for name, value in new_cfg["categories"].items():
            if name == old_name:
                rebuilt[new_name] = exts
            else:
                rebuilt[name] = value
        new_cfg["categories"] = rebuilt

    def _commit_detail():
        old_name = detail_state.get("cname")
        name_var = detail_state.get("name_var")
        ext_text = detail_state.get("ext_text")
        if not old_name or not name_var or not ext_text or old_name not in new_cfg["categories"]:
            return True
        locked = (old_name == "\u5176\u4ed6")
        new_name = old_name if locked else name_var.get().strip()
        if not new_name:
            messagebox.showwarning("\u63d0\u793a", "\u5206\u7c7b\u540d\u79f0\u4e0d\u80fd\u4e3a\u7a7a", parent=root)
            return False
        if new_name != old_name and new_name in new_cfg["categories"]:
            messagebox.showwarning("\u91cd\u590d", f"\u300c{new_name}\u300d\u5df2\u5b58\u5728", parent=root)
            return False
        new_exts = _parse_exts(ext_text.get("1.0", "end"))
        if new_name != old_name:
            _replace_category(old_name, new_name, new_exts)
            detail_state["cname"] = new_name
        else:
            new_cfg["categories"][new_name] = new_exts
        _refresh_list(new_name)
        return True

    def _show_detail(cname):
        for w in detail_inner.winfo_children(): w.destroy()
        if cname is None or cname not in new_cfg["categories"]:
            detail_state.update({"cname": None, "name_var": None, "ext_text": None})
            tk.Label(detail_inner, text="\u8bf7\u9009\u62e9\u4e00\u4e2a\u5206\u7c7b",
                     font=("Microsoft YaHei UI", 10), bg=CARD_BG, fg=MUTED).pack(expand=True)
            return

        exts = _category_exts(cname)
        locked = (cname == "\u5176\u4ed6")
        detail_state["cname"] = cname

        # Category name
        tk.Label(detail_inner, text="\u5206\u7c7b\u540d\u79f0",
                 font=("Microsoft YaHei UI", 9), bg=CARD_BG, fg=MUTED).pack(anchor="w", pady=(0, 2))
        name_var = tk.StringVar(value=cname)
        detail_state["name_var"] = name_var
        name_entry = tk.Entry(detail_inner, textvariable=name_var, font=("Microsoft YaHei UI", 10),
                              bg=ENTRY_BG, fg=FG, insertbackground=FG, relief="flat",
                              highlightbackground=BORDER, highlightthickness=1)
        name_entry.pack(fill="x", ipady=4, pady=(0, 12))
        if locked:
            name_entry.configure(state="disabled")

        # Extensions
        tk.Label(detail_inner, text="\u5305\u542b\u6587\u4ef6\u62d3\u5c55\u540d",
                 font=("Microsoft YaHei UI", 9), bg=CARD_BG, fg=MUTED).pack(anchor="w", pady=(0, 2))
        ext_frame = tk.Frame(detail_inner, bg=ENTRY_BG, highlightbackground=BORDER, highlightthickness=1)
        ext_frame.pack(fill="both", expand=True, pady=(0, 6))
        ext_text = tk.Text(ext_frame, height=8, wrap="word", font=("Microsoft YaHei UI", 9),
                           bg=ENTRY_BG, fg=FG, insertbackground=FG, relief="flat",
                           bd=0, padx=8, pady=8, undo=True)
        ext_scroll = tk.Scrollbar(ext_frame, orient="vertical", command=ext_text.yview)
        ext_text.configure(yscrollcommand=ext_scroll.set)
        ext_text.pack(side="left", fill="both", expand=True)
        ext_scroll.pack(side="right", fill="y")
        ext_text.insert("1.0", _format_exts(exts))
        detail_state["ext_text"] = ext_text

        meta_var = tk.StringVar()
        def _update_ext_meta(event=None):
            count = len(_parse_exts(ext_text.get("1.0", "end")))
            meta_var.set(f"{count} \u4e2a\u6269\u5c55\u540d")
        ext_text.bind("<KeyRelease>", _update_ext_meta)
        tk.Label(detail_inner, textvariable=meta_var,
                 font=("Microsoft YaHei UI", 9), bg=CARD_BG, fg=MUTED).pack(anchor="w")
        tk.Label(detail_inner, text="\u53ef\u7528\u7a7a\u683c\u3001\u9017\u53f7\u6216\u6362\u884c\u5206\u9694",
                 font=("Microsoft YaHei UI", 9), bg=CARD_BG, fg=MUTED).pack(anchor="w", pady=(2, 0))
        _update_ext_meta()

    def _on_list_select(event=None):
        sel = cat_listbox.curselection()
        if sel:
            names = list(new_cfg["categories"].keys())
            idx = sel[0]
            if 0 <= idx < len(names):
                selected = names[idx]
                if selected == detail_state.get("cname"):
                    return
                previous = detail_state.get("cname")
                if not _commit_detail():
                    _refresh_list(previous)
                    return
                _refresh_list(selected)
                _show_detail(selected)

    cat_listbox.bind("<<ListboxSelect>>", _on_list_select)

    # Add button
    def _add_cat():
        if not _commit_detail():
            return
        base = "\u65b0\u5efa\u5206\u7c7b"; n = base; i = 1
        while n in new_cfg["categories"]: i += 1; n = f"{base}{i}"
        new_cfg["categories"][n] = []
        _refresh_list()
        names = list(new_cfg["categories"].keys())
        idx = names.index(n)
        cat_listbox.selection_clear(0, tk.END)
        cat_listbox.selection_set(idx)
        cat_listbox.see(idx)
        _show_detail(n)

    # Delete button
    def _del_cat():
        sel = cat_listbox.curselection()
        if not sel: return
        names = list(new_cfg["categories"].keys())
        idx = sel[0]
        if not (0 <= idx < len(names)): return
        name = names[idx]
        if name == "\u5176\u4ed6": return
        if messagebox.askyesno("\u786e\u8ba4\u5220\u9664", f"\u78ee\u5b9a\u5220\u9664\u5206\u7c7b\u300c{name}\u300d\uff1f", parent=root):
            del new_cfg["categories"][name]
            _refresh_list()
            detail_state.update({"cname": None, "name_var": None, "ext_text": None})
            for w in detail_inner.winfo_children(): w.destroy()
            tk.Label(detail_inner, text="\u8bf7\u9009\u62e9\u4e00\u4e2a\u5206\u7c7b",
                     font=("Microsoft YaHei UI", 10), bg=CARD_BG, fg=MUTED).pack(expand=True)

    tk.Button(btn_left, text="\u6dfb\u52a0", command=_add_cat,
              bg=ACCENT, fg="white", relief="flat",
              font=("Microsoft YaHei UI", 8), padx=12, pady=3, cursor="hand2").pack(side="left", expand=True, fill="x", padx=(0, 3))
    tk.Button(btn_left, text="\u5220\u9664", command=_del_cat,
              bg=BTN_BG, fg=DEL_BTN, relief="flat",
              font=("Microsoft YaHei UI", 8), padx=12, pady=3, cursor="hand2").pack(side="left", expand=True, fill="x", padx=(3, 0))

    # Initial populate
    _refresh_list()
    # Show first category
    names = list(new_cfg["categories"].keys())
    if names:
        cat_listbox.selection_set(0)
        _show_detail(names[0])

    # ================================================================
    # Tab 2: General Settings
    # ================================================================
    tab_gen = tk.Frame(body, bg=BG)
    gf = tk.Frame(tab_gen, bg=BG); gf.pack(fill="both", expand=True, padx=20, pady=15)

    # Monitor folders
    tk.Label(gf, text="\u76d1\u63a7\u6587\u4ef6\u5939\uff08\u88ab\u6574\u7406\u7684\u6587\u4ef6\u5939\uff09",
             font=("Microsoft YaHei UI", 10, "bold"), bg=BG, fg=FG).pack(anchor="w", pady=(0, 4))
    tk.Label(gf, text="\u53ef\u6dfb\u52a0\u591a\u4e2a\u76ee\u5f55\uff0c\u65b0\u6587\u4ef6\u81ea\u52a8\u6574\u7406",
             font=("Microsoft YaHei UI", 8), bg=BG, fg=MUTED).pack(anchor="w", pady=(0, 6))
    wf_list = list(new_cfg.get("watch_folders", []))
    wf_canvas = tk.Canvas(gf, bg=ENTRY_BG, highlightbackground=BORDER, highlightthickness=1, height=60)
    wf_inner = tk.Frame(wf_canvas, bg=ENTRY_BG)
    wf_canvas.pack(fill="x")
    wf_canvas.create_window((0, 0), window=wf_inner, anchor="nw")

    def _refresh_wf():
        for w in wf_inner.winfo_children(): w.destroy()
        for i, p in enumerate(wf_list):
            row = tk.Frame(wf_inner, bg=ENTRY_BG); row.pack(fill="x", padx=6, pady=1)
            tk.Label(row, text=p, font=("Microsoft YaHei UI", 9), bg=ENTRY_BG, fg=FG, anchor="w").pack(side="left", fill="x", expand=True)
            tk.Button(row, text="\u2715", command=lambda idx=i: _remove_wf(idx),
                      bg=ENTRY_BG, fg=DEL_BTN, relief="flat", font=("Microsoft YaHei UI", 8), padx=8, cursor="hand2").pack(side="right", anchor="e", padx=(0, 4))
        wf_inner.update_idletasks()
        wf_canvas.configure(scrollregion=wf_canvas.bbox("all"), height=min(80, len(wf_list)*24+8))

    def _remove_wf(idx):
        if 0 <= idx < len(wf_list): wf_list.pop(idx); _refresh_wf()

    def _add_wf():
        p = filedialog.askdirectory(parent=root, title="\u9009\u62e9\u76d1\u63a7\u6587\u4ef6\u5939")
        if p and p not in wf_list: wf_list.append(p); _refresh_wf()

    _refresh_wf()
    tk.Button(gf, text="+ \u6dfb\u52a0\u76d1\u63a7\u6587\u4ef6\u5939", command=_add_wf,
              bg=BTN_BG, fg=FG, relief="flat", font=("Microsoft YaHei UI", 8), padx=10, cursor="hand2").pack(anchor="w", pady=(4, 14))

    # Target directory
    tk.Label(gf, text="\u6574\u7406\u76ee\u6807\u76ee\u5f55\uff08\u6587\u4ef6\u6574\u7406\u5230\u8fd9\u91cc\uff09",
             font=("Microsoft YaHei UI", 10, "bold"), bg=BG, fg=FG).pack(anchor="w", pady=(0, 4))
    tf_row = tk.Frame(gf, bg=BG); tf_row.pack(fill="x", pady=(0, 14))
    tf_var = tk.StringVar(value=new_cfg.get("target_base", ""))
    tk.Entry(tf_row, textvariable=tf_var, bg=ENTRY_BG, fg=FG, insertbackground=FG,
             font=("Microsoft YaHei UI", 9), relief="flat",
             highlightbackground=BORDER, highlightthickness=1).pack(side="left", fill="x", expand=True, ipady=4)
    tk.Button(tf_row, text="\u6d4f\u89c8...",
              command=lambda: (p := filedialog.askdirectory(parent=root, title="\u9009\u62e9\u6574\u7406\u76ee\u6807")) and tf_var.set(p),
              bg=BTN_BG, fg=FG, relief="flat", font=("Microsoft YaHei UI", 8), padx=10, cursor="hand2").pack(side="left", padx=(6, 0))

    # Manual organize
    tk.Label(gf, text="\u624b\u52a8\u6574\u7406", font=("Microsoft YaHei UI", 10, "bold"), bg=BG, fg=FG).pack(anchor="w", pady=(0, 6))
    organize_row = tk.Frame(gf, bg=BG); organize_row.pack(fill="x", pady=(0, 14))
    mode_var = tk.StringVar(value="smart")
    mode_buttons = {}

    mode_group = tk.Frame(organize_row, bg=BORDER)
    mode_group.pack(side="left")

    def _refresh_mode_buttons():
        selected = mode_var.get()
        for mode, btn in mode_buttons.items():
            if mode == selected:
                btn.configure(bg=ACCENT, fg="white", activebackground=ACCENT, activeforeground="white")
            else:
                btn.configure(bg=BTN_BG, fg=FG, activebackground=TAG_BG, activeforeground=FG)

    def _set_mode(mode):
        mode_var.set(mode)
        _refresh_mode_buttons()

    for _mode, _text in [("copy", "\u590d\u5236"), ("move", "\u79fb\u52a8"), ("smart", "\u667a\u80fd")]:
        btn = tk.Button(mode_group, text=_text, command=lambda m=_mode: _set_mode(m),
                        bg=BTN_BG, fg=FG, relief="flat",
                        font=("Microsoft YaHei UI", 9), padx=18, pady=5,
                        bd=0, highlightthickness=0, cursor="hand2")
        btn.pack(side="left", padx=(1, 0), pady=1)
        mode_buttons[_mode] = btn

    def _organize(mode):
        if not _commit_detail():
            return
        if not wf_list: messagebox.showwarning("\u63d0\u793a", "\u8bf7\u5148\u6dfb\u52a0\u76d1\u63a7\u6587\u4ef6\u5939", parent=root); return
        dst = tf_var.get().strip()
        if not dst: messagebox.showwarning("\u63d0\u793a", "\u8bf7\u5148\u8bbe\u7f6e\u6574\u7406\u76ee\u6807\u76ee\u5f55", parent=root); return
        cat_config = {}
        for cname, exts in new_cfg["categories"].items():
            cat_config[cname] = {"extensions": exts} if isinstance(exts, list) else exts
        try:
            from download_manager import Classifier
            clf = Classifier(cat_config)
            total = 0
            for src in wf_list:
                if os.path.isdir(src): total += clf.organize(src, dst, mode=mode, time_saving=time_var.get(), is_manual=True)
            mc = {"copy": "\u590d\u5236", "move": "\u79fb\u52a8", "smart": "\u667a\u80fd"}.get(mode, mode)
            messagebox.showinfo("\u6574\u7406\u5b8c\u6210", f"\u5df2\u5904\u7406 {total} \u4e2a\u6587\u4ef6 - \u6a21\u5f0f: {mc}", parent=root)
        except Exception as e:
            messagebox.showerror("\u9519\u8bef", f"\u6574\u7406\u5931\u8d25: {e}", parent=root)

    _refresh_mode_buttons()
    tk.Button(organize_row, text="\u5f00\u59cb\u6574\u7406", command=lambda: _organize(mode_var.get()),
              bg=ACCENT, fg="white", relief="flat",
              font=("Microsoft YaHei UI", 9, "bold"), padx=20, pady=5, cursor="hand2").pack(side="left", padx=(10, 0))

    tk.Frame(gf, height=1, bg=BORDER).pack(fill="x", pady=(0, 12))

    # Checkboxes
    auto_var = tk.BooleanVar(value=_is_autostart())
    time_var = tk.BooleanVar(value=new_cfg.get("time_saving", False))
    tk.Checkbutton(gf, text="\u5f00\u673a\u81ea\u52a8\u542f\u52a8", variable=auto_var,
                   font=("Microsoft YaHei UI", 10), bg=BG, fg=FG, selectcolor=BG,
                   activebackground=BG, activeforeground=FG,
                   highlightthickness=0, relief="flat", cursor="hand2").pack(anchor="w", pady=2)
    tk.Checkbutton(gf, text="\u6574\u7406\u65f6\u4e0d\u6574\u7406\u5b50\u76ee\u5f55\u4e2d\u7684\u6587\u4ef6", variable=time_var,
                   font=("Microsoft YaHei UI", 10), bg=BG, fg=FG, selectcolor=BG,
                   activebackground=BG, activeforeground=FG,
                   highlightthickness=0, relief="flat", cursor="hand2").pack(anchor="w", pady=2)

    hard_del_var = tk.BooleanVar(value=new_cfg.get("hard_delete_duplicates", False))
    warning = tk.Frame(gf, bg=WARNING_BG, highlightbackground=WARNING_BORDER, highlightthickness=1)
    warning.pack(fill="x", pady=(10, 0))
    tk.Checkbutton(warning, text="\u5f7b\u5e95\u5220\u9664\u91cd\u590d\u6587\u4ef6", variable=hard_del_var,
                   font=("Microsoft YaHei UI", 10, "bold"), bg=WARNING_BG, fg="#E53935", selectcolor=WARNING_BG,
                   activebackground=WARNING_BG, activeforeground="#E53935",
                   highlightthickness=0, relief="flat", cursor="hand2").pack(anchor="w", padx=10, pady=(8, 0))
    tk.Label(warning, text="\u68c0\u6d4b\u5230\u91cd\u590d\u65f6\u76f4\u63a5\u5220\u9664\uff0c\u4e0d\u8fdb\u56de\u6536\u7ad9\u3002",
             font=("Microsoft YaHei UI", 8), bg=WARNING_BG, fg=MUTED).pack(anchor="w", padx=34, pady=(0, 8))

    def _show_tab(tab_name):
        for child in (tab_cat, tab_gen):
            child.pack_forget()
        if tab_name == "categories":
            tab_cat.pack(fill="both", expand=True)
        else:
            tab_gen.pack(fill="both", expand=True)
        for name, btn in tab_buttons.items():
            selected = (name == tab_name)
            btn.configure(bg=CARD_BG if selected else BG,
                          fg=FG if selected else MUTED,
                          activebackground=CARD_BG if selected else BTN_BG,
                          activeforeground=FG)

    tab_buttons["categories"] = tk.Button(nav, text="\u5206\u7c7b\u7ba1\u7406",
                                          command=lambda: _show_tab("categories"),
                                          bg=BG, fg=MUTED, relief="flat",
                                          font=("Microsoft YaHei UI", 9, "bold"),
                                          padx=18, pady=8, bd=0, highlightthickness=0,
                                          cursor="hand2")
    tab_buttons["general"] = tk.Button(nav, text="\u901a\u7528\u8bbe\u7f6e",
                                       command=lambda: _show_tab("general"),
                                       bg=BG, fg=MUTED, relief="flat",
                                       font=("Microsoft YaHei UI", 9, "bold"),
                                       padx=18, pady=8, bd=0, highlightthickness=0,
                                       cursor="hand2")
    tab_buttons["categories"].pack(side="left")
    tab_buttons["general"].pack(side="left", padx=(4, 0))
    _show_tab("categories")

    # Save/Cancel
    btm = tk.Frame(root, bg=BG); btm.pack(fill="x", padx=20, pady=(8, 14))

    def _on_save():
        global _settings_win_ref, _tray_open_lock, _tray_lock_holder
        if not _commit_detail():
            return
        new_cfg["watch_folders"] = wf_list
        new_cfg["target_base"] = tf_var.get().strip()
        new_cfg["time_saving"] = time_var.get()
        if hard_del_var.get() and not cfg.get("hard_delete_duplicates", False):
            if not messagebox.askyesno("\u786e\u8ba4\u98ce\u9669\u64cd\u4f5c",
                                       "\u542f\u7528\u540e\uff0c\u91cd\u590d\u6587\u4ef6\u5c06\u76f4\u63a5\u5220\u9664\uff0c\u4e0d\u8fdb\u56de\u6536\u7ad9\u3002\n\n\u786e\u5b9a\u542f\u7528\u5417\uff1f",
                                       parent=root):
                return
        new_cfg["hard_delete_duplicates"] = hard_del_var.get()
        if "watch_path" in new_cfg: del new_cfg["watch_path"]
        try:
            with open(cfg_path, "w", encoding="utf-8") as cf:
                json.dump(new_cfg, cf, ensure_ascii=False, indent=2)
        except Exception: pass
        _set_autostart(auto_var.get())
        result["applied"] = True; result["config"] = new_cfg
        _on_close()

    def _on_cancel():
        _on_close()

    tk.Button(btm, text="\u4fdd\u5b58", command=_on_save,
              bg=ACCENT, fg="white", relief="flat",
              font=("Microsoft YaHei UI", 9, "bold"), padx=24, pady=6, cursor="hand2").pack(side="right", padx=(8, 0))
    tk.Button(btm, text="\u53d6\u6d88", command=_on_cancel,
              bg=BTN_BG, fg=FG, relief="flat",
              font=("Microsoft YaHei UI", 9), padx=24, pady=6, cursor="hand2").pack(side="right")

    root.deiconify()  # Show window after all setup
    root.lift()
    root.focus_force()
    root.wait_window()
    return result


# ================================================================
# System Tray
# ================================================================
def setup_tray(db, classifier, cfg, observer, log, version=None, cfg_path=None):
    global _tray_open_lock, _tray_lock_holder
    if not HAS_TRAY: print("[DM] pystray not installed, tray disabled"); return

    def _open_settings():
        def _run():
            global _tray_open_lock, _tray_lock_holder
            # Reload config from disk to show current state
            try:
                import json as _json
                _cfg_path = Path(cfg_path) if cfg_path else None
                if _cfg_path and _cfg_path.exists():
                    with open(_cfg_path, "r", encoding="utf-8") as _f:
                        fresh_cfg = _json.load(_f)
                else:
                    fresh_cfg = cfg
            except Exception:
                fresh_cfg = cfg
            try: _show_settings_window(fresh_cfg, cfg_path, log, version)
            except Exception: pass
            finally:
                try: _tray_open_lock.release(); _tray_lock_holder = False
                except Exception: pass
        threading.Thread(target=_run, daemon=True).start()

    def _about(icon):
        threading.Thread(target=lambda: messagebox.showinfo("\u5173\u4e8e", "\u4e0b\u8f7d\u5206\u7c7b\u7ba1\u5bb6\n\u81ea\u52a8\u6574\u7406\u4e0b\u8f7d\u6587\u4ef6\u5939\n\nPowered by OpenClaw"), daemon=True).start()

    def _do_exit(icon):
        try: icon.stop()
        except: pass
        try: os._exit(0)
        except: pass

    img = Image.new("RGBA", (64, 64), (0, 120, 212, 255))
    d = ImageDraw.Draw(img)
    d.rectangle([16, 20, 48, 44], fill="white")
    d.rectangle([24, 16, 40, 20], fill="white")

    from pystray import Menu, MenuItem
    menu = Menu(MenuItem("\u5173\u4e8e", _about), Menu.SEPARATOR, MenuItem("\u9000\u51fa", _do_exit))
    icon = pystray.Icon("download_manager", img, "\u4e0b\u8f7d\u5206\u7c7b\u7ba1\u5bb6", menu)

    from pystray._win32 import win32 as _win32
    _wm_notify = _win32.WM_NOTIFY
    _original_notify = icon._message_handlers[_wm_notify]

    def _patched_notify(wparam, lparam):
        if lparam == 0x0202:
            global _tray_open_lock, _tray_lock_holder
            if not _tray_lock_holder:
                _tray_open_lock.acquire(); _tray_lock_holder = True
                _open_settings()
            return True
        return _original_notify(wparam, lparam)

    icon._message_handlers[_wm_notify] = _patched_notify
    icon.run()
