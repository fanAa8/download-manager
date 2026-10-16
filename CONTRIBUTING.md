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
pip install -r requirements.txt

# 运行
python download_manager.py

# 规则测试（不打开窗口）
python -m unittest discover -s tests -v

# 在 Windows 上打包；其他系统可先检查参数
python build.py --dry-run
python build.py
```

## 项目结构

```
download-manager/
├── download_manager.py    # 启动入口
├── settings_ui.py         # 兼容旧的导入路径
├── dlm/                   # 监控、分类、整理、配置、托盘、设置
├── config.default.json    # 提交进仓库的默认分类
├── build.py               # PyInstaller 打包
├── tests/                 # 单元测试
└── README.md
```

`config.json`、数据库、日志和 `release/` 里的 zip 都不要提交。发布包上传到 GitHub Releases。

## Bug 报告

请使用 [Issues](../../issues) 提交，包含：
- Windows 版本
- 复现步骤
- 错误日志（`download_manager.log`）

## 功能建议

欢迎在 Issues 中提出，或者直接提交 PR。
