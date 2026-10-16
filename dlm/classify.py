"""按扩展名分类，并识别文件夹里哪一类占多数。"""

from __future__ import annotations

from collections import Counter
from pathlib import Path

DEFAULT_CATEGORY = "其他"

ROLE_BY_NAME = {
    "音乐": "music",
    "图片": "image",
    "视频": "video",
    "压缩包": "archive",
    "可安装exe": "installer",
    "代码文档相关": "document",
    "3D打印相关": "model3d",
    "其他": "other",
}

ROLE_HINTS = {
    "music": "文件夹里若同时有封面或歌词，会按音乐一起归档",
    "video": "文件夹里若同时有字幕或封面，会按视频一起归档",
    "archive": "安装程序和压缩包在一起时，整个文件夹归到这里",
    "installer": "和压缩包放在同一文件夹时，整体归到压缩包",
    "model3d": "预览图和说明会跟着模型一起归档",
    "document": "和图片放在一起时，仍按文档归档",
    "image": "经常作为封面，跟着音乐、视频或文档走",
    "other": "没有匹配扩展名的文件会进入这里",
}

# 两类角色同时出现、而且通常是同一份内容的附属文件时，归到值所指的角色。
CORRELATED = {
    frozenset({"music", "image"}): "music",
    frozenset({"music", "document"}): "music",
    frozenset({"video", "document"}): "video",
    frozenset({"video", "image"}): "video",
    frozenset({"model3d", "image"}): "model3d",
    frozenset({"model3d", "document"}): "model3d",
    frozenset({"document", "image"}): "document",
    frozenset({"installer", "archive"}): "archive",
}

INSTALLER_EXTS = {
    ".exe", ".msi", ".appx", ".msix", ".appxbundle", ".msixbundle", ".bat", ".cmd",
    ".apk", ".dmg", ".pkg",
}
ARCHIVE_EXTS = {
    ".zip", ".rar", ".7z", ".tar", ".gz", ".bz2", ".xz", ".iso", ".cab", ".tgz",
}
APP_EXTS = {".exe", ".msi", ".appx", ".msix", ".bat", ".cmd"}
LIB_EXTS = {".dll", ".sys", ".drv", ".ocx", ".ax"}
CFG_EXTS = {".ini", ".cfg", ".conf"}
UNINSTALL_NAMES = {"uninstall.exe", "uninstall.bat", "uninstall", "remove.exe", "unins000.exe"}


def normalize_ext(value: str) -> str:
    ext = value.strip().lower()
    if not ext:
        return ""
    if not ext.startswith("."):
        ext = "." + ext
    if ext == "." or any(ch.isspace() for ch in ext):
        return ""
    return ext


def extensions_from_rule(rule) -> list[str]:
    if isinstance(rule, dict):
        raw = rule.get("extensions", [])
    elif isinstance(rule, list):
        raw = rule
    else:
        raw = []
    result = []
    seen = set()
    for item in raw:
        if not isinstance(item, str):
            continue
        ext = normalize_ext(item)
        if ext and ext not in seen:
            result.append(ext)
            seen.add(ext)
    return result


def parse_extension_text(raw: str) -> list[str]:
    text = raw
    for sep in [",", "，", ";", "；", "\n", "\t"]:
        text = text.replace(sep, " ")
    result = []
    seen = set()
    for item in text.split():
        ext = normalize_ext(item)
        if ext and ext not in seen:
            result.append(ext)
            seen.add(ext)
    return result


def extension_owners(categories: dict) -> dict[str, list[str]]:
    owners: dict[str, list[str]] = {}
    for name, rule in categories.items():
        for ext in extensions_from_rule(rule):
            owners.setdefault(ext, []).append(name)
    return owners


class Classifier:
    def __init__(self, cats_config: dict | None = None, default_cat: str = DEFAULT_CATEGORY):
        self.default_cat = default_cat or DEFAULT_CATEGORY
        self.ext_map: dict[str, str] = {}
        self.conflicts: list[tuple[str, str, str]] = []
        self.categories: dict = {}
        self.reconfigure(cats_config or {}, self.default_cat)

    def reconfigure(self, cats_config: dict, default_cat: str | None = None) -> None:
        if default_cat:
            self.default_cat = default_cat
        self.categories = dict(cats_config or {})
        if self.default_cat not in self.categories:
            self.categories.setdefault(self.default_cat, {"extensions": [], "role": "other"})
        self.ext_map = {}
        self.conflicts = []
        for name, rule in self.categories.items():
            for ext in extensions_from_rule(rule):
                if ext in self.ext_map:
                    self.conflicts.append((ext, self.ext_map[ext], name))
                    continue
                self.ext_map[ext] = name

    def category_names(self) -> set[str]:
        return set(self.categories)

    def role_of(self, category: str) -> str | None:
        rule = self.categories.get(category)
        if isinstance(rule, dict) and rule.get("role"):
            return str(rule["role"])
        return ROLE_BY_NAME.get(category)

    def category_for_role(self, role: str, fallback_name: str) -> str:
        for name in self.categories:
            if self.role_of(name) == role:
                return name
        if fallback_name in self.categories:
            return fallback_name
        return self.default_cat

    def classify(self, filename: str) -> str:
        ext = Path(filename).suffix.lower()
        if not ext:
            return self.default_cat
        return self.ext_map.get(ext, self.default_cat)

    def correlation_winner(self, first: str, second: str) -> str | None:
        roles = {self.role_of(first), self.role_of(second)}
        if None in roles:
            return None
        winner_role = CORRELATED.get(frozenset(roles))
        if not winner_role:
            return None
        for category in (first, second):
            if self.role_of(category) == winner_role:
                return category
        return None

    def organize(self, src, dst, mode: str = "smart", **kwargs):
        """兼容旧调用。实现放在 dlm.organize，避免两个模块顶层互相导入。"""
        from dlm.organize import Organizer

        return Organizer(self).organize(src, dst, mode=mode, **kwargs)

    def classify_folder(self, folder: Path) -> str:
        """多数派达到六成才认定文件夹类别，避免被个别文件带偏。"""
        from dlm.files import is_temp_file, iter_files

        counts: Counter[str] = Counter()
        total = 0
        for path in iter_files(Path(folder), limit=2000):
            if is_temp_file(path):
                continue
            total += 1
            category = self.classify(path.name)
            if category != self.default_cat:
                counts[category] += 1
        if total == 0 or not counts:
            return self.default_cat
        category, count = counts.most_common(1)[0]
        if count / total < 0.6:
            return self.default_cat
        return category


def is_app_folder(folder: Path) -> bool:
    """安装目录（卸载程序、exe+dll）在智能模式下整夹跳过，避免拆散程序。"""
    from dlm.files import iter_files

    has_app = has_lib = has_cfg = False
    total = 0
    uninstaller = False
    for path in iter_files(folder, limit=2000):
        total += 1
        ext = path.suffix.lower()
        name = path.name.lower()
        if ext in APP_EXTS:
            has_app = True
        elif ext in LIB_EXTS:
            has_lib = True
        elif ext in CFG_EXTS:
            has_cfg = True
        if name.startswith("unins") or name in UNINSTALL_NAMES:
            uninstaller = True
    if total < 1:
        return False
    if uninstaller and has_app:
        return True
    if total >= 2 and has_app and (has_lib or has_cfg):
        return True
    return False


def folder_has_extension(folder: Path, extensions: set[str]) -> bool:
    from dlm.files import iter_files, is_temp_file

    for path in iter_files(folder, limit=2000):
        if is_temp_file(path):
            continue
        if path.suffix.lower() in extensions:
            return True
    return False
