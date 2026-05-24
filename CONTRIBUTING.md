# 贡献指南

感谢你对下载分类管家感兴趣！

## 如何贡献

1. Fork 本仓库
2. 创建功能分支 (`git checkout -b feature/xxx`)
3. 提交更改 (`git commit -m 'Add xxx'`)
4. 推送到分支 (`git push origin feature/xxx`)
5. 创建 Pull Request

## 开发环境

```bash
# Python 3.11+
pip install pyinstaller watchdog pystray pillow

# 运行
python download_manager.py

# 打包
python build.py
```

## 项目结构

```
download-manager/
├── download_manager.py   # 核心逻辑：监控、分类、移动
├── settings_ui.py        # 托盘 + 设置界面
├── build.py              # PyInstaller 打包脚本
├── config.json           # 配置文件（运行时生成）
└── README.md
```

## Bug 报告

请使用 [Issues](../../issues) 提交，包含：
- Windows 版本
- 复现步骤
- 错误日志（`download_manager.log`）

## 功能建议

欢迎在 Issues 中提出，或者直接提交 PR。
