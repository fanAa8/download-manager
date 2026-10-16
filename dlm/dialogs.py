"""重复文件确认窗。只在策略设为「询问」时使用。"""

from __future__ import annotations

import logging
import threading

log = logging.getLogger("DLM")


def dup_dialog(new_name: str, new_path, existing: dict, timeout_sec: int = 60) -> str:
    """返回 keep（保留两份）或 skip（把新文件移到「重复文件」，不删除已有文件）。"""
    result = {"action": "keep"}

    def _run() -> None:
        try:
            import tkinter as tk

            from dlm.theme import apply_titlebar, font, palette
        except Exception as exc:
            log.warning("无法打开重复确认窗口 (%s)", exc)
            return
        colors = palette()
        root = tk.Tk()
        root.withdraw()
        root.title("检测到重复文件")
        root.configure(bg=colors.bg)
        root.attributes("-topmost", True)
        root.resizable(False, False)
        apply_titlebar(root, colors.dark)
        width, height = 520, 280
        root.update_idletasks()
        pos_x = (root.winfo_screenwidth() - width) // 2
        pos_y = (root.winfo_screenheight() - height) // 2
        root.geometry(f"{width}x{height}+{pos_x}+{pos_y}")

        header = tk.Frame(root, bg=colors.bg)
        header.pack(fill="x", padx=20, pady=(16, 8))
        tk.Label(header, text="检测到内容相同的文件", font=font(13, True), bg=colors.bg, fg=colors.fg).pack(anchor="w")
        tk.Label(
            header,
            text="已有文件会保留。选择跳过时，新文件移动到「重复文件」，不会被删除。",
            font=font(9),
            bg=colors.bg,
            fg=colors.muted,
            wraplength=470,
            justify="left",
        ).pack(anchor="w", pady=(4, 0))

        card = tk.Frame(root, bg=colors.surface, highlightbackground=colors.border, highlightthickness=1)
        card.pack(fill="both", expand=True, padx=20, pady=8)
        stored = existing.get("path", "")
        shown = stored if len(stored) <= 64 else "…" + stored[-60:]
        rows = [
            ("新文件", new_name),
            ("已有位置", shown),
            ("大小", f"{existing.get('size', 0) / 1048576:.1f} MB"),
        ]
        for label, value in rows:
            line = tk.Frame(card, bg=colors.surface)
            line.pack(fill="x", padx=12, pady=4)
            tk.Label(line, text=label, width=10, anchor="w", font=font(9), bg=colors.surface, fg=colors.muted).pack(side="left")
            tk.Label(line, text=value, anchor="w", font=font(9), bg=colors.surface, fg=colors.fg).pack(side="left")

        buttons = tk.Frame(root, bg=colors.bg)
        buttons.pack(fill="x", padx=20, pady=(4, 16))

        closed = {"value": False}

        def choose(action: str) -> None:
            if closed["value"]:
                return
            closed["value"] = True
            result["action"] = action
            try:
                root.destroy()
            except tk.TclError:
                pass

        skip = tk.Button(
            buttons, text="跳过，留下已有文件", command=lambda: choose("skip"),
            bg=colors.button, fg=colors.fg, activebackground=colors.button_hover,
            relief="flat", bd=0, padx=14, pady=6, cursor="hand2", font=font(9),
        )
        skip.pack(side="right", padx=(8, 0))
        keep = tk.Button(
            buttons, text="保留两份", command=lambda: choose("keep"),
            bg=colors.accent, fg=colors.select_fg, activebackground=colors.accent_hover,
            relief="flat", bd=0, padx=14, pady=6, cursor="hand2", font=font(9, True),
        )
        keep.pack(side="right")
        root.bind("<Escape>", lambda _e: choose("skip"))
        root.bind("<Return>", lambda _e: choose("keep"))
        root.protocol("WM_DELETE_WINDOW", lambda: choose("keep"))
        root.after(timeout_sec * 1000, lambda: choose(result.get("action") or "keep"))
        root.deiconify()
        root.mainloop()

    worker = threading.Thread(target=_run, daemon=True)
    worker.start()
    worker.join(timeout_sec + 5)
    return result.get("action") or "keep"
