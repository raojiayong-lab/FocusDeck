# 🎯 FocusDeck

> 轻量 · 流畅 · **不卡**的 Windows 专注浮窗。番茄钟 + 任务清单 + 跟随鼠标的呼吸光晕，单文件 exe 即开即用。

[![Release](https://img.shields.io/github/v/release/raojiayong-lab/FocusDeck?color=blue)](https://github.com/raojiayong-lab/FocusDeck/releases)
[![License](https://img.shields.io/github/license/raojiayong-lab/FocusDeck)](LICENSE)
[![Stars](https://img.shields.io/github/stars/raojiayong-lab/FocusDeck?style=social)](https://github.com/raojiayong-lab/FocusDeck)
[![Platform](https://img.shields.io/badge/platform-Windows-0078D6)](https://github.com/raojiayong-lab/FocusDeck)
[![Python](https://img.shields.io/badge/python-3.14-3776AB)](https://www.python.org)
[![Downloads](https://img.shields.io/github/downloads/raojiayong-lab/FocusDeck/total)](https://github.com/raojiayong-lab/FocusDeck/releases)

![FocusDeck 预览](screenshot_final.png)

FocusDeck 是一个基于 [pywebview](https://github.com/r0x0r/pywebview) + Edge WebView2 的**无边框浮窗式专注工具**。所有动画（光晕跟随、呼吸律动、音乐律动）全部走 **GPU 合成层**，零全屏重绘——即使在低端显卡上也能稳定 60 FPS，不会卡顿、不会闪退。

## ✨ 功能特性

| 模块 | 说明 |
|------|------|
| 🍅 番茄钟 | 预设 + 自定义时长，支持双计时并行，循环规则可配 |
| ✅ 任务清单 | 待办 / 进行中 / 已完成，本地持久化 |
| 🌈 背景光晕 | 跟随鼠标 + 呼吸律动，**GPU 合成、不卡不闪退** |
| 🍳 厨房计时 | 食材预设 / 自定义 / 分步提醒弹窗 |
| 🎵 专注音乐 | 白噪音 / 环境音本地播放，律动联动光晕 |
| 📊 统计 | 日 / 周 / 月专注图表、专注日记、成就体系 |
| 🪟 极简 / 锁机 | 极简模式、桌面小组件、锁机防分心 |

## 🚀 快速开始

1. 前往 [Releases](https://github.com/raojiayong-lab/FocusDeck/releases) 下载 `FocusDeck.exe`
2. 双击运行（需已安装 Edge / WebView2 运行库，Win10 / 11 通常自带）
3. 若 Windows 提示「SmartScreen 未知发布者」，点「仍要运行」即可（个人开源项目，无代码签名）

> 想直接体验网页版？用浏览器打开仓库里的 `index.html`，核心界面即可运行。

## 🛠 构建（开发者）

需要 **Python 3.14** + `pywebview` + `PyInstaller`：

```bash
pip install pywebview PyInstaller
python -m PyInstaller --noconfirm --onefile --noconsole ^
  --name FocusDeck --icon icon.ico ^
  --add-data "index.html;." --add-data "icon.ico;." app.py
```

生成的 `dist/FocusDeck.exe` 即为可分发的单文件程序。也可以直接运行仓库里的 `build.bat`（Windows）一键打包。

## 📁 项目结构

```
app.py            # pywebview 外壳 + 本地 API（保存状态 / 导出 / 闪屏等）
index.html        # 主界面（CSS + HTML + JS 单文件）
icon.ico          # 程序图标
make_icon.py      # 图标生成脚本
build.bat         # 一键打包（PyInstaller）
FocusDeck.spec    # PyInstaller 配置
```

## 💡 为什么流畅？

传统桌面 Widget 常把光晕做成「渐变中心随鼠标变量变化 + 全窗 `backdrop-filter` 模糊」，鼠标一动就触发**全屏重绘 + 大模糊重算**，低端 GPU 直接卡死。FocusDeck 改用：

- 去掉全窗 `backdrop-filter`，改用不透明界面表面；
- 光晕层放大 200%、渐变中心**固定**，鼠标跟随用 `translate`、呼吸 / 律动用 `scale`——都是 GPU 合成层；
- 模糊从 48 / 56px 降到 18 / 22px，去掉 `screen` 混合。

结果：跟随 / 呼吸 / 律动全部**零重绘**，稳定 60 FPS。

## 🤝 贡献

欢迎提 Issue / PR！本项目使用 [MIT](LICENSE) 协议。

## 📄 许可证

[MIT](LICENSE) © 2026 raojiayong-lab
