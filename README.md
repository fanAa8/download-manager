<div align="center">

# 📂 下载分类管家

**扔进去就不用管 — 自动分类整理你的下载目录**

![Platform](https://img.shields.io/badge/platform-Windows-blue?logo=windows)
![Python](https://img.shields.io/badge/python-3.11+-yellow?logo=python)
![License](https://img.shields.io/badge/license-MIT-green)
![Release](https://img.shields.io/github/v/release/你的用户名/download-manager)

</div>

---

## ✨ 这是什么

**下载分类管家** 是一个 Windows 后台监控工具。你指定几个"监控文件夹"，它就一直盯着——有新文件进来就按扩展名自动分类，移到对应的子文件夹。全程在系统托盘安静运行，不需要任何手动操作。

**两种方式：自动监控新文件 + 一键整理已有文件。**

---

## 🚀 功能一览

| 功能 | 说明 |
|------|------|
| 🔄 实时监控 | 文件下载完自动触发整理，不用手动操作 |
| 📁 扩展名分类 | 覆盖 200+ 种格式，按扩展名精准分类 |
| 📦 文件夹归类 | 子目录整体扫描，按多数文件类型判定归宿 |
| ⚡ 多种整理模式 | 复制 / 移动 / 智能（跳过未分类） |
| 🔔 系统托盘 | 后台常驻，左键打开设置，右键退出 |
| 🎨 Win11 风格 | 自适应明暗主题，跟随系统强调色 |
| 💾 便携绿色 | 单个 exe，解压即用，不写注册表 |
| 🚀 开机自启 | 可选开机自动启动 |
| 📂 多目录监控 | 支持同时监控多个文件夹 |
| 🖱️ 主动分类 | 一键整理已有文件，三种模式：复制/移动/智能 |

---

## 📋 默认分类

```
视频      mp4 mkv avi mov wmv flv webm m4v ...
音乐      mp3 wav flac ogg wma m4a opus ape ...
图片      jpg png gif bmp webp svg psd raw ...
压缩包    zip rar 7z tar gz bz2 xz iso cab ...
可安装exe  exe msi appx ...
代码文档  py js html pdf docx xlsx csv sql ...
3D打印    stl obj 3mf gcode amf blend fbx ...
其他      以上都不匹配的统一收集
```

支持在设置界面自定义分类名称和扩展名。

---

## 📦 安装使用

### 方式一：下载 Release（推荐）

1. 去 [Releases](../../releases) 页面下载最新的 zip
2. 解压到任意位置
3. 双击 `下载分类管家.exe`
4. 左键托盘图标 → 设置 → 选你要监控的目录
5. 开始下载文件，观察自动整理

### 方式二：从源码运行

```bash
# 克隆仓库
git clone https://github.com/fanAa8/download-manager.git
cd download-manager

# 安装依赖
pip install pyinstaller watchdog pystray pillow

# 直接运行
python download_manager.py

# 或打包成 exe
python build.py
```

---

## 🎯 使用场景

- **下载党日常** — 浏览器/网盘/微信下载全往一个目录堆，自动分类
- **帮家人朋友** — 塞个 zip 过去，解压双击就能用，零配置
- **云盘批量下载** — 文件夹扔进监控目录，整个归类
- **长期挂着** — 托盘常驻 + 开机自启，目录永远整洁

---

## ⚙️ 配置

配置文件在 exe 同目录下的 `config.json`，也可以在设置界面里修改：

```json
{
  "watch_folders": ["D:\\Users\\Downloads"],
  "target_base": "D:\\Users\\Downloads",
  "download_complete_wait": 5,
  "batch_window": 15,
  "default_category": "其他",
  "categories": {
    "音乐": {
      "extensions": [".mp3", ".flac", ".wav", ".ogg", ".m4a"]
    }
  }
}
```

| 字段 | 说明 |
|------|------|
| `watch_folders` | 要监控的目录（数组，支持多个） |
| `target_base` | 分类子文件夹创建在哪个目录 |
| `download_complete_wait` | 文件多久没变动视为下载完成（秒） |
| `batch_window` | 文件夹下载等待窗口（秒） |
| `categories` | 自定义分类和扩展名 |

---

## ❓ 常见问题

**Q: 会不会误删文件？**
不会。只移动/复制，不删除任何文件。

**Q: 怎么卸载？**
删除程序文件夹即可，绿色软件，无残留。

**Q: 能自定义分类吗？**
能。在设置界面直接编辑，或者改 `config.json`。

**Q: 支持哪些 Windows 版本？**
Windows 10/11，64 位。自动跟随系统明暗主题。

---

## 🛠️ 技术栈

- **Python 3.11+** — 主语言
- **watchdog** — 文件系统监控
- **pystray** — 系统托盘图标
- **PyInstaller** — 打包成单文件 exe
- **Pillow** — 图标绘制
- **tkinter** — 设置界面

---

## 📄 开源协议

[MIT License](LICENSE) — 随便用，随便改，注明出处就行。

---

<div align="center">
如果觉得有用，给个 ⭐ Star 支持一下！
</div>
