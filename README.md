<div align="center">

# 下载分类管家

**监视下载目录，按扩展名把新文件收进对应文件夹。**

![Platform](https://img.shields.io/badge/platform-Windows-blue?logo=windows)
![Python](https://img.shields.io/badge/python-3.11+-yellow?logo=python)
![License](https://img.shields.io/badge/license-MIT-green)
![Release](https://img.shields.io/github/v/release/fanAa8/download-manager)

</div>

---

## 这是什么

Windows 托盘里的绿色工具。指定监控目录之后，下载完成的文件会按扩展名移动到目标目录下的分类文件夹。也可以对已经堆着的文件做一次手动整理。

程序只移动或复制。默认不会删除文件。内容确认相同的新文件会挪到「重复文件」，原来的那一份留在原地。

---

## 能做什么

| 功能 | 说明 |
|------|------|
| 实时监控 | 文件体积稳定、没有临时后缀、没有被占用之后才移动 |
| 扩展名分类 | 默认约 240 种扩展名，设置里可以改 |
| 文件夹归类 | 子目录先整夹判断，避免下载到一半被拆开 |
| 三种整理 | 复制留原件；移动逐个归档；智能按文件夹内容归类 |
| 重复文件 | 默认隔离到「重复文件」，也可改为询问、回收站或彻底删除 |
| 系统托盘 | 左键或菜单打开设置，可以暂停监控 |
| 外观 | 跟随 Windows 明暗主题和强调色 |
| 多目录 | 可以同时监视多个文件夹 |
| 发送到 | 安装脚本可选把程序加进右键「发送到」 |

---

## 默认分类

```
视频        mp4 mkv avi mov ts m3u8 ...
音乐        mp3 flac wav m4a lrc cue ...
图片        jpg png webp heic raw jxl ...
压缩包      zip rar 7z iso img whl ...
可安装exe   exe msi apk dmg ...
代码文档    pdf docx epub py js tsx srt ...
3D打印      stl obj 3mf gcode gltf ...
其他        上面都匹配不上的文件
```

同一个扩展名如果写进了两个分类，列表里靠前的那个生效，设置里会提示。`.ts` 默认当作视频，TypeScript 请用 `.tsx` 或自己调整。`.bin` 太笼统，默认不归到安装包。

---

## 安装

### 下载 Release

发布包不放在 Git 仓库里。请到 [Releases](https://github.com/fanAa8/download-manager/releases) 下载 zip，解压后双击 `下载分类管家.exe`。

仓库里以前附带的 `下载分类管家-v1.1.0.zip` 已经停止跟踪。历史提交里还在，新的包只通过 Releases 分发。

1. 解压到任意目录
2. 双击 `下载分类管家.exe`
3. 左键托盘图标，选择监控目录和整理目标
4. 需要的话再运行 `install.bat`，它只会按提示写入当前用户的开机启动，或添加「发送到」

`install.bat` 不会再注册一个名不副实的右键打开命令。

### 从源码运行

```bash
git clone https://github.com/fanAa8/download-manager.git
cd download-manager
pip install -r requirements.txt
python download_manager.py
```

打包请在 Windows 上执行。其他系统可以先检查参数：

```bash
python build.py --dry-run
python build.py
```

`build.py` 会在 `dist/` 生成 exe，并在 `release/` 打好 zip。把这个 zip 上传到 GitHub Releases，不要提交进仓库。打包机还需要 `pip install pyinstaller`。

---

## 整理方式

| 模式 | 行为 |
|------|------|
| 复制 | 复制到 `目标/分类/原文件夹/…`，源文件保留 |
| 移动 | 移动到上面的位置，源位置只留下搬不走的文件 |
| 智能 | 单一类型或明显成套的文件夹整夹移动；混在一起的按文件拆开；未识别的散文件、还没下完的文件夹、程序目录跳过 |

手动整理在后台进行，窗口不会卡住，可以停止。省时模式会跳过「里面还有子文件夹」的目录，默认关闭。

监控到的散文件直接归类。新建子目录里的文件不会先被拆走，而是等整个文件夹稳定后再按智能模式处理。已经放进分类目录或「重复文件」的内容不会再被搬走。

下面这些情况会把文件留在原地，只写日志：

- 还带着 `.crdownload`、`.part`、迅雷/百度网盘等临时后缀
- 体积还在变化，或 Windows 上文件仍被占用
- 等到超时仍不稳定
- 500MB 以上且当时没有网络：先多等一段时间，避免把中断的大文件当成下完了
- 没有权限，或目标里同名文件已经存在（不会覆盖，失败的源文件保留）

有的下载器会预先占满体积，又不锁文件。把「下载完成等待」调大可以降低误移的可能。

---

## 配置

第一次运行会在程序旁边生成 `config.json`。仓库里提交的是 `config.default.json`，本机的 `config.json` 不进 Git。

```json
{
  "watch_folders": ["D:\\Downloads"],
  "target_base": "D:\\Downloads",
  "download_complete_wait": 5,
  "batch_window": 15,
  "duplicate_action": "quarantine",
  "default_category": "其他",
  "categories": {
    "音乐": {
      "role": "music",
      "extensions": [".mp3", ".flac"]
    }
  }
}
```

| 字段 | 说明 |
|------|------|
| `watch_folders` | 要监视的目录 |
| `target_base` | 分类文件夹创建在这里，可以和监控目录相同 |
| `download_complete_wait` | 散文件需要连续稳定多久（秒，最少 2） |
| `batch_window` | 新文件夹至少观察多久再判断（秒） |
| `duplicate_action` | `quarantine`、`recycle`、`ask`、`delete` |
| `time_saving` | 手动整理时跳过含子目录的文件夹 |
| `categories` | 分类、扩展名，可选 `role` 用来识别封面、字幕这类成套文件 |

旧的 `hard_delete_duplicates: true` 仍会当作 `delete`。没有这项时，默认改为移到「重复文件」，不再因为没装回收站组件就直接删除。

配置损坏时，原文件会留成 `config.json.bad`，程序用默认配置继续启动。

---

## 常见问题

**会不会删掉我的文件？**  
整理本身只会移动或复制。重复文件默认也是移动。只有在设置里选择「彻底删除」时，才会删除新下载的那一份；已经归档的文件不动。

**目标里已经有同名文件怎么办？**  
不覆盖。新文件会变成 `名称 (2).ext`。移动失败时，原文件留在原地。

**怎么卸载？**  
先在设置里关掉开机启动，再删掉「发送到」里的快捷方式，然后删除程序文件夹。开机启动写的是当前用户的 `Run` 项，不关的话会留下这一条。

**支持哪些系统？**  
Windows 10 / 11，64 位。界面跟随系统明暗主题。

---

## 开发

```text
download_manager.py     启动入口
settings_ui.py          兼容旧导入
dlm/                    监控、分类、整理、配置、托盘、设置窗口
config.default.json     默认分类
build.py                Windows 打包
tests/                  不打开界面的规则测试
```

```bash
python -m unittest discover -s tests -v
```

---

## 开源协议

[MIT License](LICENSE)

---

## 致谢

本项目由 [小米 MiMo](https://www.mi.com) AI 协助开发。
