"""设置窗口：分类、监控目录、整理模式和重复文件策略。"""

from __future__ import annotations

import copy
import os
import threading
from pathlib import Path

import tkinter as tk
from tkinter import filedialog, messagebox

from dlm import __version__
from dlm.autostart import is_autostart, set_autostart
from dlm.classify import ROLE_HINTS, Classifier, extension_owners, extensions_from_rule, parse_extension_text
from dlm.config import save_config
from dlm.notify import open_file_location
from dlm.organize import OrganizeResult, Organizer
from dlm.paths import config_path, log_path
from dlm.runtime import RUNTIME
from dlm.theme import apply_titlebar, font, palette

CURRENT = {"root": None}
MODE_HELP = {
    "copy": "复制到目标分类，原文件留在原地。",
    "move": "逐个移动到目标分类，并保留原来的子目录。",
    "smart": "按文件夹内容整体归类。未识别的散文件、还在下载的文件夹和程序目录会跳过。",
}
DUP_OPTIONS = [
    ("quarantine", "移到「重复文件」（不删除）"),
    ("recycle", "移入回收站"),
    ("ask", "每次询问"),
    ("delete", "彻底删除新的那一份"),
]


def focus_settings() -> bool:
    root = CURRENT.get("root")
    if root is None:
        return False
    try:
        root.after(0, lambda: (root.deiconify(), root.lift(), root.focus_force()))
        return True
    except tk.TclError:
        CURRENT["root"] = None
        return False


def _category_value(old, exts: list[str], name: str) -> dict:
    from dlm.classify import ROLE_BY_NAME

    updated = dict(old) if isinstance(old, dict) else {}
    updated["extensions"] = exts
    if "role" not in updated and name in ROLE_BY_NAME:
        updated["role"] = ROLE_BY_NAME[name]
    return updated


def _enable_dpi() -> None:
    try:
        import ctypes

        ctypes.windll.shcore.SetProcessDpiAwareness(1)
    except Exception:
        try:
            import ctypes

            ctypes.windll.user32.SetProcessDPIAware()
        except Exception:
            pass


def show_settings_window(cfg, cfg_path=None, log=None, version=None) -> dict:
    del log
    if focus_settings():
        return {"applied": False, "config": None}
    _enable_dpi()
    colors = palette()
    version = version or __version__
    cfg_path = Path(cfg_path) if cfg_path else config_path()
    new_cfg = copy.deepcopy(cfg if isinstance(cfg, dict) else {})
    new_cfg.setdefault("categories", {})
    if "其他" not in new_cfg["categories"]:
        new_cfg["categories"]["其他"] = {"extensions": [], "role": "other"}
    result = {"applied": False, "config": None}

    root = tk.Tk()
    root.withdraw()
    CURRENT["root"] = root
    root.title(f"下载分类管家 v{version}")
    root.configure(bg=colors.bg)
    root.minsize(720, 640)
    root.geometry("780x680")
    apply_titlebar(root, colors.dark)
    root.update_idletasks()
    pos_x = max(0, (root.winfo_screenwidth() - 780) // 2)
    pos_y = max(0, (root.winfo_screenheight() - 680) // 2)
    root.geometry(f"780x680+{pos_x}+{pos_y}")

    stop_event = threading.Event()
    organize_state = {"running": False}

    def close() -> None:
        stop_event.set()
        CURRENT["root"] = None
        try:
            root.unbind_all("<MouseWheel>")
        except tk.TclError:
            pass
        try:
            root.quit()
            root.destroy()
        except tk.TclError:
            pass

    root.protocol("WM_DELETE_WINDOW", close)

    shell = tk.Frame(root, bg=colors.bg)
    shell.pack(fill="both", expand=True)
    nav = tk.Frame(shell, bg=colors.bg)
    nav.pack(fill="x", padx=18, pady=(12, 0))
    body = tk.Frame(shell, bg=colors.bg)
    body.pack(fill="both", expand=True)
    tab_cat = tk.Frame(body, bg=colors.bg)
    tab_gen = tk.Frame(body, bg=colors.bg)
    tab_buttons = {}

    # —— 分类 ——
    pane = tk.Frame(tab_cat, bg=colors.bg)
    pane.pack(fill="both", expand=True, padx=16, pady=12)
    left = tk.Frame(pane, bg=colors.bg, width=210)
    left.pack(side="left", fill="y", padx=(0, 10))
    left.pack_propagate(False)
    tk.Label(left, text="分类", font=font(9, True), bg=colors.bg, fg=colors.muted).pack(anchor="w")
    cat_list = tk.Listbox(
        left, bg=colors.entry, fg=colors.fg, selectbackground=colors.accent,
        selectforeground=colors.select_fg, font=font(10), relief="flat",
        highlightbackground=colors.border, highlightthickness=1, activestyle="none", bd=0,
    )
    cat_list.pack(fill="both", expand=True, pady=(4, 6))
    left_buttons = tk.Frame(left, bg=colors.bg)
    left_buttons.pack(fill="x")

    right = tk.Frame(pane, bg=colors.surface, highlightbackground=colors.border, highlightthickness=1)
    right.pack(side="left", fill="both", expand=True)
    detail = tk.Frame(right, bg=colors.surface)
    detail.pack(fill="both", expand=True, padx=16, pady=14)
    detail_state = {"name": None, "name_var": None, "text": None}
    suppress = {"on": False}

    def names() -> list[str]:
        return list(new_cfg["categories"].keys())

    def refresh_list(selected: str | None = None) -> None:
        if selected is None:
            picked = cat_list.curselection()
            current = names()
            if picked and picked[0] < len(current):
                selected = current[picked[0]]
        suppress["on"] = True
        try:
            cat_list.delete(0, tk.END)
            for name in names():
                count = len(extensions_from_rule(new_cfg["categories"][name]))
                cat_list.insert(tk.END, f"{name}   ·   {count}")
            if selected in new_cfg["categories"]:
                index = names().index(selected)
                cat_list.selection_set(index)
                cat_list.see(index)
        finally:
            suppress["on"] = False

    def commit_detail() -> bool:
        old = detail_state.get("name")
        name_var = detail_state.get("name_var")
        widget = detail_state.get("text")
        if not old or name_var is None or widget is None or old not in new_cfg["categories"]:
            return True
        new_name = old if old == "其他" else name_var.get().strip()
        if not new_name:
            messagebox.showwarning("提示", "分类名称不能为空", parent=root)
            return False
        if new_name != old and new_name in new_cfg["categories"]:
            messagebox.showwarning("重复", f"「{new_name}」已经存在", parent=root)
            return False
        try:
            exts = parse_extension_text(widget.get("1.0", "end"))
        except tk.TclError:
            return True
        rebuilt = {}
        for name, rule in new_cfg["categories"].items():
            if name == old:
                rebuilt[new_name] = _category_value(rule, exts, new_name)
            else:
                rebuilt[name] = rule
        new_cfg["categories"] = rebuilt
        detail_state["name"] = new_name
        refresh_list(new_name)
        return True

    def show_detail(name: str | None) -> None:
        for child in detail.winfo_children():
            child.destroy()
        if not name or name not in new_cfg["categories"]:
            detail_state.update(name=None, name_var=None, text=None)
            tk.Label(detail, text="选择左侧的分类", font=font(10), bg=colors.surface, fg=colors.muted).pack(expand=True)
            return
        rule = new_cfg["categories"][name]
        locked = name == "其他"
        detail_state["name"] = name
        tk.Label(detail, text="分类名称", font=font(9), bg=colors.surface, fg=colors.muted).pack(anchor="w")
        name_var = tk.StringVar(value=name)
        detail_state["name_var"] = name_var
        entry = tk.Entry(
            detail, textvariable=name_var, font=font(11), bg=colors.entry, fg=colors.fg,
            insertbackground=colors.fg, relief="flat", highlightbackground=colors.border, highlightthickness=1,
        )
        entry.pack(fill="x", ipady=5, pady=(2, 8))
        if locked:
            entry.configure(state="disabled")
        role = rule.get("role") if isinstance(rule, dict) else None
        from dlm.classify import ROLE_BY_NAME
        role = role or ROLE_BY_NAME.get(name)
        hint = ROLE_HINTS.get(role or "", "自定义分类。靠前的分类优先匹配同名扩展名。")
        tk.Label(detail, text=hint, font=font(8), bg=colors.surface, fg=colors.hint, wraplength=420, justify="left").pack(anchor="w", pady=(0, 8))
        tk.Label(detail, text="扩展名", font=font(9), bg=colors.surface, fg=colors.muted).pack(anchor="w")
        editor = tk.Frame(detail, bg=colors.entry, highlightbackground=colors.border, highlightthickness=1)
        editor.pack(fill="both", expand=True, pady=(2, 4))
        text = tk.Text(
            editor, height=8, wrap="word", font=font(10), bg=colors.entry, fg=colors.fg,
            insertbackground=colors.fg, relief="flat", bd=0, padx=8, pady=8, undo=True,
        )
        scroll = tk.Scrollbar(editor, command=text.yview)
        text.configure(yscrollcommand=scroll.set)
        text.pack(side="left", fill="both", expand=True)
        scroll.pack(side="right", fill="y")
        text.insert("1.0", " ".join(extensions_from_rule(rule)))
        detail_state["text"] = text
        meta = tk.StringVar()
        warn = tk.StringVar()

        def refresh_meta(_event=None) -> None:
            exts = parse_extension_text(text.get("1.0", "end"))
            meta.set(f"{len(exts)} 个扩展名，用空格、逗号或换行分隔")
            owners = extension_owners({key: value for key, value in new_cfg["categories"].items() if key != name})
            clashes = [f"{ext} 已在「{owners[ext][0]}」" for ext in exts if ext in owners]
            warn.set("靠前的分类会优先生效：" + "，".join(clashes[:4]) if clashes else "")

        text.bind("<KeyRelease>", refresh_meta)
        tk.Label(detail, textvariable=meta, font=font(8), bg=colors.surface, fg=colors.muted).pack(anchor="w")
        tk.Label(detail, textvariable=warn, font=font(8), bg=colors.surface, fg=colors.danger, wraplength=420, justify="left").pack(anchor="w")
        refresh_meta()

    def on_select(_event=None) -> None:
        if suppress["on"]:
            return
        picked = cat_list.curselection()
        if not picked:
            return
        current = names()
        if picked[0] >= len(current):
            return
        selected = current[picked[0]]
        if selected == detail_state.get("name"):
            return
        previous = detail_state.get("name")
        if not commit_detail():
            refresh_list(previous)
            return
        show_detail(selected)

    cat_list.bind("<<ListboxSelect>>", on_select)

    def add_category() -> None:
        if not commit_detail():
            return
        base = "新建分类"
        name = base
        index = 1
        while name in new_cfg["categories"]:
            index += 1
            name = f"{base}{index}"
        new_cfg["categories"][name] = {"extensions": []}
        refresh_list(name)
        show_detail(name)

    def delete_category() -> None:
        picked = cat_list.curselection()
        current = names()
        if not picked or picked[0] >= len(current):
            return
        name = current[picked[0]]
        if name == "其他":
            messagebox.showinfo("提示", "「其他」用来收纳未匹配的文件，不能删除。", parent=root)
            return
        if not messagebox.askyesno("删除分类", f"删除「{name}」？\n已经归档的文件不会被移动或删除。", parent=root):
            return
        if detail_state.get("name") == name:
            detail_state.update(name=None, name_var=None, text=None)
        else:
            commit_detail()
        new_cfg["categories"].pop(name, None)
        refresh_list()
        remaining = names()
        show_detail(remaining[0] if remaining else None)

    tk.Button(
        left_buttons, text="添加", command=add_category, bg=colors.accent, fg=colors.select_fg,
        relief="flat", font=font(9), padx=8, pady=4, cursor="hand2",
    ).pack(side="left", expand=True, fill="x", padx=(0, 4))
    tk.Button(
        left_buttons, text="删除", command=delete_category, bg=colors.button, fg=colors.danger,
        relief="flat", font=font(9), padx=8, pady=4, cursor="hand2",
    ).pack(side="left", expand=True, fill="x")
    cat_list.bind("<Delete>", lambda _e: delete_category())
    refresh_list()
    if names():
        cat_list.selection_set(0)
        show_detail(names()[0])

    # —— 通用 ——
    canvas = tk.Canvas(tab_gen, bg=colors.bg, highlightthickness=0)
    scroll = tk.Scrollbar(tab_gen, command=canvas.yview)
    general = tk.Frame(canvas, bg=colors.bg)
    window_id = canvas.create_window((0, 0), window=general, anchor="nw")

    def _fit_width(event) -> None:
        canvas.itemconfigure(window_id, width=event.width)

    def _fit_scroll(_event=None) -> None:
        canvas.configure(scrollregion=canvas.bbox("all"))

    general.bind("<Configure>", _fit_scroll)
    canvas.bind("<Configure>", _fit_width)
    canvas.configure(yscrollcommand=scroll.set)
    canvas.pack(side="left", fill="both", expand=True)
    scroll.pack(side="right", fill="y")

    def _wheel(event) -> None:
        canvas.yview_scroll(int(-event.delta / 120) if event.delta else 0, "units")

    canvas.bind("<Enter>", lambda _e: canvas.bind_all("<MouseWheel>", _wheel))
    canvas.bind("<Leave>", lambda _e: canvas.unbind_all("<MouseWheel>"))
    inner = tk.Frame(general, bg=colors.bg)
    inner.pack(fill="both", expand=True, padx=20, pady=14)

    def section(title: str) -> None:
        tk.Label(inner, text=title, font=font(10, True), bg=colors.bg, fg=colors.fg).pack(anchor="w", pady=(10, 4))

    section("监控文件夹")
    tk.Label(inner, text="新下载的文件出现在这些目录时自动整理。", font=font(8), bg=colors.bg, fg=colors.muted).pack(anchor="w")
    wf_list = [item for item in new_cfg.get("watch_folders") or [] if str(item).strip()]
    wf_box = tk.Listbox(
        inner, height=4, bg=colors.entry, fg=colors.fg, font=font(9), relief="flat",
        highlightbackground=colors.border, highlightthickness=1, activestyle="none",
    )
    wf_box.pack(fill="x", pady=(4, 4))

    def refresh_watch() -> None:
        wf_box.delete(0, tk.END)
        for item in wf_list:
            wf_box.insert(tk.END, item)
        if not wf_list:
            wf_box.insert(tk.END, "还没有监控目录")

    def add_watch() -> None:
        selected = filedialog.askdirectory(parent=root, title="选择监控文件夹")
        if selected and selected not in wf_list:
            if wf_list == [] and wf_box.size() == 1 and wf_box.get(0).startswith("还没有"):
                pass
            wf_list.append(selected)
            refresh_watch()

    def remove_watch() -> None:
        picked = wf_box.curselection()
        if not picked or not wf_list or picked[0] >= len(wf_list):
            return
        wf_list.pop(picked[0])
        refresh_watch()

    refresh_watch()
    watch_buttons = tk.Frame(inner, bg=colors.bg)
    watch_buttons.pack(fill="x", pady=(0, 6))
    tk.Button(watch_buttons, text="添加目录", command=add_watch, bg=colors.button, fg=colors.fg, relief="flat", font=font(9), padx=10, pady=3, cursor="hand2").pack(side="left")
    tk.Button(watch_buttons, text="移除", command=remove_watch, bg=colors.button, fg=colors.fg, relief="flat", font=font(9), padx=10, pady=3, cursor="hand2").pack(side="left", padx=6)

    section("整理目标")
    tk.Label(inner, text="分类文件夹会创建在这里。可以和监控目录相同。", font=font(8), bg=colors.bg, fg=colors.muted).pack(anchor="w")
    target_row = tk.Frame(inner, bg=colors.bg)
    target_row.pack(fill="x", pady=(4, 6))
    target_var = tk.StringVar(value=new_cfg.get("target_base") or "")
    tk.Entry(
        target_row, textvariable=target_var, bg=colors.entry, fg=colors.fg, insertbackground=colors.fg,
        font=font(9), relief="flat", highlightbackground=colors.border, highlightthickness=1,
    ).pack(side="left", fill="x", expand=True, ipady=4)
    tk.Button(
        target_row, text="浏览", command=lambda: (picked := filedialog.askdirectory(parent=root, title="选择目标目录")) and target_var.set(picked),
        bg=colors.button, fg=colors.fg, relief="flat", font=font(9), padx=10, cursor="hand2",
    ).pack(side="left", padx=(6, 0))

    section("手动整理")
    mode_var = tk.StringVar(value="smart")
    mode_help = tk.StringVar(value=MODE_HELP["smart"])
    mode_row = tk.Frame(inner, bg=colors.border)
    mode_row.pack(anchor="w", pady=(2, 4))
    mode_buttons = {}

    def refresh_modes() -> None:
        selected = mode_var.get()
        mode_help.set(MODE_HELP.get(selected, ""))
        for mode, button in mode_buttons.items():
            if mode == selected:
                button.configure(bg=colors.accent, fg=colors.select_fg)
            else:
                button.configure(bg=colors.button, fg=colors.fg)

    def set_mode(mode: str) -> None:
        mode_var.set(mode)
        refresh_modes()

    for mode, label in (("copy", "复制"), ("move", "移动"), ("smart", "智能")):
        button = tk.Button(
            mode_row, text=label, command=lambda value=mode: set_mode(value),
            relief="flat", font=font(9), padx=16, pady=5, bd=0, cursor="hand2",
        )
        button.pack(side="left", padx=1, pady=1)
        mode_buttons[mode] = button
    refresh_modes()
    tk.Label(inner, textvariable=mode_help, font=font(8), bg=colors.bg, fg=colors.muted, wraplength=640, justify="left").pack(anchor="w")

    action_row = tk.Frame(inner, bg=colors.bg)
    action_row.pack(fill="x", pady=(8, 4))
    status_var = tk.StringVar(value="整理使用上面的分类，不会自动保存设置。")
    organize_button = tk.Button(
        action_row, text="开始整理", bg=colors.accent, fg=colors.select_fg, relief="flat",
        font=font(9, True), padx=16, pady=5, cursor="hand2",
    )
    organize_button.pack(side="left")
    tk.Label(action_row, textvariable=status_var, font=font(8), bg=colors.bg, fg=colors.muted).pack(side="left", padx=10)

    time_var = tk.BooleanVar(value=bool(new_cfg.get("time_saving", False)))
    tk.Checkbutton(
        inner, text="省时模式：跳过里面还有子文件夹的目录", variable=time_var,
        font=font(10), bg=colors.bg, fg=colors.fg, selectcolor=colors.entry,
        activebackground=colors.bg, activeforeground=colors.fg, highlightthickness=0,
    ).pack(anchor="w", pady=(4, 0))
    auto_var = tk.BooleanVar(value=is_autostart())
    original_autostart = auto_var.get()
    tk.Checkbutton(
        inner, text="开机自动启动（写入当前用户的启动项）", variable=auto_var,
        font=font(10), bg=colors.bg, fg=colors.fg, selectcolor=colors.entry,
        activebackground=colors.bg, activeforeground=colors.fg, highlightthickness=0,
    ).pack(anchor="w")

    section("重复文件")
    tk.Label(
        inner,
        text="只处理新下载的那一份。已经归档的文件不会被删除。回收站不可用时会自动改成移动。",
        font=font(8), bg=colors.bg, fg=colors.muted, wraplength=640, justify="left",
    ).pack(anchor="w", pady=(0, 4))
    dup_var = tk.StringVar(value=new_cfg.get("duplicate_action") or "quarantine")
    for value, label in DUP_OPTIONS:
        tk.Radiobutton(
            inner, text=label, value=value, variable=dup_var, font=font(10),
            bg=colors.bg, fg=colors.danger if value == "delete" else colors.fg,
            selectcolor=colors.entry, activebackground=colors.bg, highlightthickness=0, anchor="w",
        ).pack(anchor="w")
    try:
        import send2trash  # noqa: F401
    except ImportError:
        tk.Label(inner, text="当前没装 send2trash，选回收站时会改为移动到「重复文件」。", font=font(8), bg=colors.bg, fg=colors.hint).pack(anchor="w", pady=(2, 0))

    def run_organize() -> None:
        if organize_state["running"]:
            stop_event.set()
            status_var.set("正在停止，已搬好的文件会保留。")
            return
        if not commit_detail():
            return
        if not wf_list:
            messagebox.showwarning("提示", "请先添加监控文件夹。", parent=root)
            return
        destination = target_var.get().strip()
        if not destination:
            messagebox.showwarning("提示", "请先填写整理目标。", parent=root)
            return
        snapshot = copy.deepcopy(new_cfg["categories"])
        default = new_cfg.get("default_category") or "其他"
        mode = mode_var.get()
        saving = time_var.get()
        folders = list(wf_list)
        stop_event.clear()
        organize_state["running"] = True
        organize_button.configure(text="停止")
        status_var.set("正在整理…")

        def work() -> None:
            app = RUNTIME.app
            if app is not None:
                app.handler.push_manual()
            total = OrganizeResult()
            error = None
            try:
                organizer = Organizer(Classifier(snapshot, default))
                for source in folders:
                    if stop_event.is_set():
                        break
                    if os.path.isdir(source):
                        part = organizer.organize(
                            source, destination, mode=mode, time_saving=saving,
                            is_manual=True, stop_event=stop_event,
                        )
                        total.transferred += part.transferred
                        total.skipped += part.skipped
                        total.failed += part.failed
                        total.errors.extend(part.errors)
            except Exception as exc:
                error = exc
            finally:
                if app is not None:
                    app.handler.pop_manual()

            def finish() -> None:
                organize_state["running"] = False
                try:
                    if not root.winfo_exists():
                        return
                except tk.TclError:
                    return
                organize_button.configure(text="开始整理")
                if error is not None:
                    status_var.set("整理失败")
                    messagebox.showerror("整理失败", str(error), parent=root)
                    return
                noun = {"copy": "复制", "move": "移动", "smart": "智能"}.get(mode, mode)
                stopped = stop_event.is_set()
                status_var.set(f"{'已停止' if stopped else '完成'}：成功 {total.transferred}，跳过 {total.skipped}，失败 {total.failed}")
                extra = ""
                if total.errors:
                    extra = "\n\n" + "\n".join(total.errors[:6])
                messagebox.showinfo(
                    "整理已停止" if stopped else "整理完成",
                    f"模式：{noun}\n成功 {total.transferred}，跳过 {total.skipped}，失败 {total.failed}{extra}",
                    parent=root,
                )

            try:
                root.after(0, finish)
            except tk.TclError:
                pass

        threading.Thread(target=work, name="dlm-organize", daemon=True).start()

    organize_button.configure(command=run_organize)

    def show_tab(name: str) -> None:
        if name != "categories" and not commit_detail():
            return
        tab_cat.pack_forget()
        tab_gen.pack_forget()
        (tab_cat if name == "categories" else tab_gen).pack(fill="both", expand=True)
        if name != "general":
            try:
                canvas.unbind_all("<MouseWheel>")
            except tk.TclError:
                pass
        for key, button in tab_buttons.items():
            selected = key == name
            button.configure(
                bg=colors.surface if selected else colors.bg,
                fg=colors.accent if selected else colors.muted,
            )

    tab_buttons["categories"] = tk.Button(nav, text="分类", command=lambda: show_tab("categories"), relief="flat", font=font(10, True), padx=16, pady=6, bd=0, cursor="hand2")
    tab_buttons["general"] = tk.Button(nav, text="监控和整理", command=lambda: show_tab("general"), relief="flat", font=font(10, True), padx=16, pady=6, bd=0, cursor="hand2")
    tab_buttons["categories"].pack(side="left")
    tab_buttons["general"].pack(side="left")
    show_tab("categories")

    footer = tk.Frame(root, bg=colors.bg)
    footer.pack(fill="x", padx=18, pady=(0, 12))
    tk.Label(footer, text=str(cfg_path), font=font(8), bg=colors.bg, fg=colors.hint).pack(side="left")
    tk.Button(footer, text="日志", command=lambda: open_file_location(log_path()), bg=colors.button, fg=colors.fg, relief="flat", font=font(9), padx=10, cursor="hand2").pack(side="left", padx=8)

    def save() -> None:
        if not commit_detail():
            return
        new_cfg["watch_folders"] = list(wf_list)
        new_cfg["target_base"] = target_var.get().strip()
        new_cfg["time_saving"] = bool(time_var.get())
        new_cfg["duplicate_action"] = dup_var.get()
        if dup_var.get() == "delete" and cfg.get("duplicate_action") != "delete" and not cfg.get("hard_delete_duplicates"):
            if not messagebox.askyesno(
                "确认删除",
                "之后内容相同的新文件会被永久删除。\n已经归档的文件不会动。\n\n确定启用吗？",
                parent=root,
            ):
                return
        missing = [item for item in wf_list if not os.path.isdir(item)]
        if missing and not messagebox.askyesno("目录不存在", "这些监控目录目前不存在，仍要保存吗？\n" + "\n".join(missing), parent=root):
            return
        target = new_cfg["target_base"]
        if target and not os.path.isdir(target):
            if not messagebox.askyesno("创建目录", f"目标目录不存在，现在创建吗？\n{target}", parent=root):
                return
            try:
                Path(target).mkdir(parents=True, exist_ok=True)
            except OSError as exc:
                messagebox.showerror("创建失败", str(exc), parent=root)
                return
        try:
            stored = save_config(new_cfg, cfg_path)
        except OSError as exc:
            messagebox.showerror("保存失败", f"配置没有写进去：{exc}", parent=root)
            return
        if auto_var.get() != original_autostart and not set_autostart(auto_var.get()):
            messagebox.showerror("开机启动失败", "配置已经保存，但启动项没有改成功。请检查安全软件是否拦截。", parent=root)
            result["config"] = stored
            return
        result["applied"] = True
        result["config"] = stored
        close()

    tk.Button(footer, text="保存", command=save, bg=colors.accent, fg=colors.select_fg, relief="flat", font=font(9, True), padx=18, pady=6, cursor="hand2").pack(side="right")
    tk.Button(footer, text="取消", command=close, bg=colors.button, fg=colors.fg, relief="flat", font=font(9), padx=18, pady=6, cursor="hand2").pack(side="right", padx=(0, 8))
    root.bind("<Control-s>", lambda _e: save())
    root.deiconify()
    root.lift()
    try:
        root.focus_force()
    except tk.TclError:
        pass
    root.wait_window()
    return result
