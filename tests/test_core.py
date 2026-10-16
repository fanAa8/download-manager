"""核心规则的轻量测试，不启动界面。"""

from __future__ import annotations

import json
import os
import tempfile
import unittest
from pathlib import Path

import build
import download_manager
from dlm import __version__
from dlm.classify import Classifier
from dlm.config import load_config, normalize, save_config
from dlm.database import Database
from dlm.duplicates import resolve_duplicate
from dlm.files import is_temp_file, remove_empty_dirs, transfer, transfer_into, unique_path
from dlm.fingerprint import smart_fingerprint, usable_fingerprint
from dlm.readiness import ArrivalQueue, Probe, event_action


def categories():
    return {
        "视频": {"role": "video", "extensions": [".mp4"]},
        "音乐": {"role": "music", "extensions": [".mp3"]},
        "图片": {"role": "image", "extensions": [".jpg"]},
        "压缩包": {"role": "archive", "extensions": [".zip"]},
        "可安装exe": {"role": "installer", "extensions": [".exe"]},
        "代码文档相关": {"role": "document", "extensions": [".txt", ".srt"]},
        "其他": {"role": "other", "extensions": []},
    }


def classifier():
    return Classifier(categories(), "其他")


class TempCase(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)

    def tearDown(self):
        self._tmp.cleanup()

    def write(self, relative: str, data: bytes = b"data") -> Path:
        path = self.root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
        return path


class ExtensionTests(unittest.TestCase):
    def test_shipped_rules_have_no_conflicts_and_cover_common_types(self):
        data = json.loads(Path("config.default.json").read_text(encoding="utf-8"))
        clf = Classifier(data["categories"], data["default_category"])
        self.assertEqual(clf.conflicts, [])
        self.assertEqual(data["watch_folders"], [])
        self.assertEqual(data["target_base"], "")
        self.assertEqual(data["duplicate_action"], "quarantine")
        self.assertNotIn("新建分类", data["categories"])
        self.assertEqual(clf.classify("movie.ts"), "视频")
        self.assertEqual(clf.classify("app.tsx"), "代码文档相关")
        self.assertEqual(clf.classify("firmware.bin"), "其他")
        self.assertEqual(clf.classify("book.epub"), "代码文档相关")
        self.assertEqual(clf.classify("song.mp3"), "音乐")
        self.assertEqual(clf.classify("model.stl"), "3D打印相关")

    def test_first_category_keeps_duplicate_extension(self):
        clf = Classifier({"音乐": [".mp3"], "音频": [".mp3"], "其他": []}, "其他")
        self.assertEqual(clf.classify("a.mp3"), "音乐")
        self.assertEqual(clf.conflicts, [(".mp3", "音乐", "音频")])

    def test_legacy_list_and_folder_majority(self):
        clf = Classifier({"音乐": [".mp3"], "其他": []}, "其他")
        self.assertEqual(clf.role_of("音乐"), "music")
        folder = Path(tempfile.mkdtemp())
        try:
            for index in range(4):
                (folder / f"{index}.txt").write_text("x")
            (folder / "one.mp3").write_bytes(b"x")
            self.assertEqual(clf.classify_folder(folder), "其他")
            for index in range(10):
                (folder / f"more{index}.mp3").write_bytes(b"x")
            self.assertEqual(clf.classify_folder(folder), "音乐")
        finally:
            for child in folder.iterdir():
                child.unlink()
            folder.rmdir()

    def test_temp_names(self):
        for name in ("a.crdownload", "a.mp4.part", "b.td.cfg", ".hidden", "~$doc.docx", "c.baiduyun.p.downloading"):
            self.assertTrue(is_temp_file(Path(name)), name)
        self.assertFalse(is_temp_file(Path("song.mp3")))


class TransferTests(TempCase):
    def test_unique_name_and_refuses_overwrite(self):
        source = self.write("a.txt", b"new")
        existing = self.write("out/a.txt", b"old")
        self.assertFalse(transfer(source, existing, "move"))
        self.assertEqual(existing.read_bytes(), b"old")
        self.assertEqual(source.read_bytes(), b"new")
        placed = transfer_into(source, self.root / "out", "move")
        self.assertEqual(placed.name, "a (2).txt")
        self.assertFalse(source.exists())
        self.assertEqual(unique_path(self.root / "out", "a.txt").name, "a (3).txt")

    def test_failed_move_keeps_source(self):
        source = self.write("song.mp3", b"abc")
        blocker = self.write("blocked", b"x")
        self.assertIsNone(transfer_into(source, blocker / "音乐", "move"))
        self.assertEqual(source.read_bytes(), b"abc")

    def test_remove_empty_dirs_keeps_root_and_files(self):
        kept = self.write("box/keep.txt", b"1")
        empty = self.root / "box" / "empty"
        empty.mkdir()
        remove_empty_dirs(self.root / "box", preserve=self.root)
        self.assertTrue(kept.exists())
        self.assertFalse(empty.exists())
        self.assertTrue(self.root.exists())


class OrganizeTests(TempCase):
    def test_smart_moves_loose_file_and_skips_unknown_and_reserved(self):
        self.write("in/song.mp3", b"1")
        self.write("in/note.xyz", b"2")
        self.write("in/config.json", b"{}")
        result = classifier().organize(self.root / "in", self.root / "out", mode="smart")
        self.assertEqual(int(result), 1)
        self.assertTrue((self.root / "out" / "音乐" / "song.mp3").is_file())
        self.assertTrue((self.root / "in" / "note.xyz").is_file())
        self.assertTrue((self.root / "in" / "config.json").is_file())
        self.assertFalse((self.root / "in" / "song.mp3").exists())

    def test_copy_keeps_source_and_folder_name(self):
        self.write("in/Album/song.mp3", b"1")
        result = classifier().organize(self.root / "in", self.root / "out", mode="copy")
        self.assertEqual(result.transferred, 1)
        self.assertTrue((self.root / "in" / "Album" / "song.mp3").is_file())
        self.assertTrue((self.root / "out" / "音乐" / "Album" / "song.mp3").is_file())

    def test_smart_single_type_folder_moves_together(self):
        self.write("in/Album/a.mp3", b"1")
        self.write("in/Album/b.mp3", b"2")
        result = classifier().organize(self.root / "in", self.root / "out", mode="smart")
        self.assertEqual(result.transferred, 2)
        self.assertTrue((self.root / "out" / "音乐" / "Album" / "a.mp3").is_file())
        self.assertFalse((self.root / "in" / "Album").exists())

    def test_correlated_album_stays_together_below_seventy_percent(self):
        for index in range(6):
            self.write(f"in/Album/{index}.mp3", b"m")
        for index in range(4):
            self.write(f"in/Album/c{index}.jpg", b"j")
        result = classifier().organize(self.root / "in", self.root / "out", mode="smart")
        self.assertEqual(result.transferred, 10)
        self.assertTrue((self.root / "out" / "音乐" / "Album" / "0.mp3").is_file())
        self.assertTrue((self.root / "out" / "音乐" / "Album" / "c0.jpg").is_file())
        self.assertFalse((self.root / "out" / "图片").exists())

    def test_dominant_folder_moves_as_one(self):
        for index in range(8):
            self.write(f"in/Album/{index}.mp3", b"m")
        self.write("in/Album/cover.jpg", b"j")
        self.write("in/Album/cover2.jpg", b"j")
        classifier().organize(self.root / "in", self.root / "out", mode="smart")
        self.assertTrue((self.root / "out" / "音乐" / "Album" / "cover.jpg").is_file())

    def test_three_way_mix_is_split_flat(self):
        for index in range(2):
            self.write(f"in/Mix/a{index}.mp3", b"m")
            self.write(f"in/Mix/b{index}.mp4", b"v")
            self.write(f"in/Mix/c{index}.jpg", b"p")
        result = classifier().organize(self.root / "in", self.root / "out", mode="smart")
        self.assertEqual(result.transferred, 6)
        self.assertTrue((self.root / "out" / "音乐" / "a0.mp3").is_file())
        self.assertTrue((self.root / "out" / "视频" / "b0.mp4").is_file())
        self.assertFalse((self.root / "out" / "音乐" / "Mix").exists())

    def test_app_folder_is_not_touched(self):
        self.write("in/Tool/tool.exe", b"e")
        self.write("in/Tool/tool.dll", b"d")
        result = classifier().organize(self.root / "in", self.root / "out", mode="smart")
        self.assertEqual(result.transferred, 0)
        self.assertIn("Tool", result.skipped_dirs)
        self.assertTrue((self.root / "in" / "Tool" / "tool.dll").is_file())

    def test_installer_bundle_goes_to_archive(self):
        self.write("in/Setup/setup.exe", b"e")
        self.write("in/Setup/data.zip", b"z")
        self.write("in/Setup/readme.txt", b"t")
        result = classifier().organize(self.root / "in", self.root / "out", mode="smart")
        self.assertEqual(result.transferred, 3)
        self.assertTrue((self.root / "out" / "压缩包" / "Setup" / "setup.exe").is_file())
        self.assertTrue((self.root / "out" / "压缩包" / "Setup" / "data.zip").is_file())

    def test_incomplete_folder_is_left_alone(self):
        self.write("in/Album/song.mp3", b"1")
        self.write("in/Album/song.mp3.part", b"partial")
        result = classifier().organize(self.root / "in", self.root / "out", mode="smart")
        self.assertEqual(result.transferred, 0)
        self.assertTrue((self.root / "in" / "Album" / "song.mp3").is_file())

    def test_time_saving_skips_nested_folder_only(self):
        self.write("in/Artist/Album/song.mp3", b"1")
        self.write("in/Single/song.mp3", b"2")
        self.write("in/loose.mp3", b"3")
        result = classifier().organize(self.root / "in", self.root / "out", mode="smart", time_saving=True)
        self.assertTrue((self.root / "in" / "Artist" / "Album" / "song.mp3").is_file())
        self.assertTrue((self.root / "out" / "音乐" / "Single" / "song.mp3").is_file())
        self.assertTrue((self.root / "out" / "音乐" / "loose.mp3").is_file())
        self.assertGreaterEqual(result.transferred, 2)

    def test_inplace_does_not_reprocess_category_folder(self):
        self.write("音乐/keep.mp3", b"old")
        self.write("new.mp3", b"new")
        classifier().organize(self.root, self.root, mode="smart")
        self.assertEqual((self.root / "音乐" / "keep.mp3").read_bytes(), b"old")
        self.assertEqual((self.root / "音乐" / "new.mp3").read_bytes(), b"new")
        self.assertFalse((self.root / "new.mp3").exists())


class DuplicateTests(TempCase):
    def test_confirmed_duplicate_is_moved_not_deleted(self):
        existing = self.write("library/song.mp3", b"same-bytes")
        incoming = self.write("incoming/song.mp3", b"same-bytes")
        result = resolve_duplicate(
            incoming, existing, policy="quarantine",
            quarantine_dir=self.root / "重复文件", stored_hash="sha256-old-value",
        )
        self.assertEqual(result.action, "skip")
        self.assertEqual(existing.read_bytes(), b"same-bytes")
        self.assertFalse(incoming.exists())
        self.assertEqual(len(list((self.root / "重复文件").iterdir())), 1)

    def test_different_content_is_renamed_and_kept(self):
        existing = self.write("library/song.mp3", b"aaaa")
        incoming = self.write("incoming/song.mp3", b"bbbb")
        result = resolve_duplicate(
            incoming, existing, policy="delete", quarantine_dir=self.root / "重复文件",
        )
        self.assertEqual(result.action, "renamed")
        self.assertEqual(existing.read_bytes(), b"aaaa")
        self.assertTrue(result.path.is_file())
        self.assertEqual(result.path.read_bytes(), b"bbbb")
        self.assertFalse((self.root / "重复文件").exists())

    def test_delete_removes_only_the_new_file(self):
        existing = self.write("library/song.mp3", b"same-bytes")
        incoming = self.write("incoming/song.mp3", b"same-bytes")
        result = resolve_duplicate(
            incoming, existing, policy="delete", quarantine_dir=self.root / "重复文件",
        )
        self.assertEqual(result.action, "skip")
        self.assertFalse(incoming.exists())
        self.assertTrue(existing.is_file())

    def test_recycle_failure_falls_back_to_quarantine(self):
        existing = self.write("library/song.mp3", b"same-bytes")
        incoming = self.write("incoming/song.mp3", b"same-bytes")
        result = resolve_duplicate(
            incoming, existing, policy="recycle", quarantine_dir=self.root / "重复文件",
            recycle=lambda _path: False,
        )
        self.assertEqual(result.action, "skip")
        self.assertTrue(existing.is_file())
        self.assertTrue((self.root / "重复文件").is_dir())


class ConfigAndIndexTests(TempCase):
    def test_corrupt_config_is_backed_up(self):
        template = self.root / "default.json"
        template.write_text('{"target_base":"D:\\\\out","categories":{"其他":[]}}', encoding="utf-8")
        path = self.root / "config.json"
        path.write_text("{", encoding="utf-8")
        cfg = load_config(path, template)
        self.assertEqual(cfg["target_base"], "D:\\out")
        self.assertTrue(list(self.root.glob("config.json*.bad")))
        self.assertTrue(path.is_file())
        json.loads(path.read_text(encoding="utf-8"))

    def test_bom_and_legacy_duplicate_flag(self):
        path = self.root / "config.json"
        path.write_bytes("\ufeff{\"hard_delete_duplicates\": true, \"categories\": {\"其他\": []}}".encode("utf-8"))
        cfg = load_config(path, self.root / "missing-default.json")
        self.assertEqual(cfg["duplicate_action"], "delete")
        fresh = normalize({"watch_folders": "nope", "download_complete_wait": 0})
        self.assertEqual(fresh["watch_folders"], [])
        self.assertEqual(fresh["download_complete_wait"], 2)
        self.assertEqual(fresh["duplicate_action"], "quarantine")

    def test_database_forgets_missing_files(self):
        db = Database(self.root / "index.db")
        try:
            db.add_file("", "song.mp3", 4, str(self.root / "gone.mp3"), "音乐")
            self.assertIsNone(db.find_live("song.mp3", 4))
            self.assertEqual(db.find_by_name_and_size("song.mp3", 4), [])
        finally:
            db.close()

    def test_save_config_roundtrip(self):
        path = self.root / "nested" / "config.json"
        saved = save_config({"categories": {"音乐": [".mp3"]}, "target_base": "D:\\a"}, path)
        self.assertEqual(saved["duplicate_action"], "quarantine")
        loaded = json.loads(path.read_text(encoding="utf-8"))
        self.assertEqual(loaded["target_base"], "D:\\a")
        self.assertNotIn("watch_path", loaded)


class ReadinessTests(unittest.TestCase):
    def test_stable_file_becomes_ready_and_growth_does_not(self):
        queue = ArrivalQueue(settle_window=0, file_hits=2, file_max_wait=30, max_attempts=0)
        path = Path("/tmp/download/song.mp3")
        queue.watch("file", path, 0)

        def probe(item, size, settled=True):
            return Probe(True, size, settled)

        ready, abandoned = queue.poll(0, lambda item: probe(item, 10))
        self.assertEqual(ready, [])
        ready, abandoned = queue.poll(2, lambda item: probe(item, 10))
        self.assertEqual(ready, [])
        ready, abandoned = queue.poll(4, lambda item: probe(item, 10))
        self.assertEqual(len(ready), 1)
        self.assertEqual(abandoned, [])

        queue.watch("file", path, 0)
        queue.poll(0, lambda item: probe(item, 10))
        ready, abandoned = queue.poll(100, lambda item: probe(item, 99))
        self.assertEqual(ready, [])
        self.assertEqual(abandoned, [])

    def test_folder_waits_out_initial_delay_and_temp_files(self):
        queue = ArrivalQueue(
            settle_window=0, folder_hits=2, folder_initial_delay=10,
            folder_max_wait=100, max_attempts=0,
        )
        folder = Path("/tmp/download/Album")
        queue.watch("folder", folder, 0)
        ready, _abandoned = queue.poll(5, lambda item: Probe(True, 10, True))
        self.assertEqual(ready, [])
        queue.poll(10, lambda item: Probe(True, 10, False))
        ready, _abandoned = queue.poll(12, lambda item: Probe(True, 10, False))
        self.assertEqual(ready, [])

    def test_offline_hold_delays_large_file_then_releases(self):
        queue = ArrivalQueue(
            settle_window=0, file_hits=1, file_max_wait=1000, max_attempts=0,
            offline_threshold=10, offline_hold=50, net_ok=lambda: False,
        )
        path = Path("/tmp/download/big.mkv")
        queue.watch("file", path, 0)
        queue.poll(0, lambda item: Probe(True, 20, True))
        ready, _abandoned = queue.poll(2, lambda item: Probe(True, 20, True))
        self.assertEqual(ready, [])
        ready, _abandoned = queue.poll(60, lambda item: Probe(True, 20, True))
        self.assertEqual(len(ready), 1)

    def test_event_routing(self):
        root = Path("/tmp/dlm-watch")
        names = {"音乐", "其他"}
        self.assertEqual(event_action(root / "a.mp3", False, [root], names, root)[0], "file")
        self.assertEqual(event_action(root / "a.mp4.part", False, [root], names, root)[0], "ignore")
        self.assertEqual(event_action(root / "config.json", False, [root], names, root)[0], "ignore")
        kind, folder = event_action(root / "Album" / "a.mp3", False, [root], names, root)
        self.assertEqual(kind, "folder")
        self.assertEqual(folder, Path(os.path.abspath(str(root / "Album"))))
        self.assertEqual(event_action(root / "音乐" / "a.mp3", False, [root], names, root)[0], "ignore")
        self.assertEqual(event_action(root / "重复文件" / "a.mp3", False, [root], names, root)[0], "ignore")
        outside = Path("/tmp/other-target")
        self.assertEqual(event_action(root / "音乐" / "a.mp3", False, [root], names, outside)[0], "folder")
        child = root / "sub"
        kind, path = event_action(child / "a.mp3", False, [root, child], names, outside)
        self.assertEqual(kind, "file")
        self.assertEqual(path, Path(os.path.abspath(str(child / "a.mp3"))))


class SmokeTests(unittest.TestCase):
    def test_version_and_build_plan(self):
        self.assertEqual(__version__, "1.2.0")
        self.assertEqual(download_manager.VERSION, "1.2.0")
        self.assertEqual(build.main(["--dry-run"]), 0)
        self.assertIn("dlm.organize", build.module_names())

    def test_fingerprint_prefixes(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "a.bin"
            path.write_bytes(b"hello fingerprint")
            full = smart_fingerprint(path, threshold=1000)
            sampled = smart_fingerprint(path, threshold=4)
            self.assertTrue(full.startswith("md5:"))
            self.assertTrue(sampled.startswith("sample-md5:"))
            self.assertEqual(full, smart_fingerprint(path, threshold=1000))
            self.assertTrue(usable_fingerprint(full))
            self.assertFalse(usable_fingerprint("ab" * 32))


if __name__ == "__main__":
    unittest.main()
