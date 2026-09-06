# 🎯 FocusDeck Pro

> 轻量 · 流畅 · **不卡不崩**的 Windows 专注浮窗。番茄钟 + 任务清单 + 跟随鼠标的呼吸光晕 + 周视图日程 + 专注统计，单文件 exe 即开即用。

[![Release](https://img.shields.io/github/v/release/raojiayong-lab/FocusDeck?color=blue)](https://github.com/raojiayong-lab/FocusDeck/releases)
[![License](https://img.shields.io/github/license/raojiayong-lab/FocusDeck)](LICENSE)
[![Stars](https://img.shields.io/github/stars/raojiayong-lab/FocusDeck?style=social)](https://github.com/raojiayong-lab/FocusDeck)
[![Platform](https://img.shields.io/badge/platform-Windows-0078D6)](https://github.com/raojiayong-lab/FocusDeck)
[![Python](https://img.shields.io/badge/python-3.14-3776AB)](https://www.python.org)
[![Downloads](https://img.shields.io/github/downloads/raojiayong-lab/FocusDeck/total)](https://github.com/raojiayong-lab/FocusDeck/releases)

![FocusDeck 预览](screenshot_final.png)

FocusDeck 是一个基于 [pywebview](https://github.com/r0x0r/pywebview) + Edge WebView2 的**无边框浮窗式专注工具**（非 Electron）。为兼容低端显卡、避免 GPU TDR 崩溃，**默认走软件渲染**；动画全部用 `transform` / `opacity` 等低成本合成属性，禁用 `backdrop-filter` 与每帧全窗模糊重绘，因此即使软件渲染下也能流畅运行、不卡顿、不闪退。需要更高画质时可在「设置 → 重置为 GPU」手动开启硬件加速。

---

## ✨ 功能特性

| 模块 | 说明 |
|------|------|
| 🍅 番茄钟 | 预设 + 自定义时长，支持双计时并行，循环规则可配 |
| ✅ 任务清单 | 待办 / 进行中 / 已完成，本地持久化 |
| 🌈 背景光晕 | 跟随鼠标 + **呼吸收放**（吸气胀大 / 呼气缩小），倒计时数字随呼吸轻微起伏；禁模糊重绘，**不卡不闪退** |
| 🍳 厨房计时 | 食材预设 / 自定义 / 分步提醒弹窗 |
| 🎵 专注音乐 | 本地音乐文件夹导入，**关闭重启后自动识别、免重复导入**；白噪音 / 环境音律动联动光晕 |
| 📊 统计 | 日 / 周 / 月专注图表、专注日记、成就体系 |
| 🖥 五页仪表盘 | 专注 / 日程 / 概览 / 任务 / 设置，鼠标悬停左侧页签即自动切换 |
| 📅 周视图日程 | 课程表式 8:00–24:00 周网格，拖拽改时间、拖到已有事件即交换；点击事件弹详情可编辑 |
| 📚 历史课程库 | 左侧可展开抽屉，课程以**移动制**沉淀复用（拖进课表即从库移除，拖回库即从课表移除） |
| 🔳 侧边导航 | 可展开 / 收起的侧边栏，释放横向空间，状态记忆 |
| 🪟 托盘常驻 | 关闭主窗口后缩到系统托盘后台运行，计时 / 音乐不中断；托盘菜单可恢复 / 进迷你 / 退出 |
| 💊 迷你药丸 | 仅显示倒计时的细长小药丸，可拖动、靠近屏幕边缘自动吸附（可关闭），双击退出迷你 |

---

## 🆕 2.0 新特性速览

- **侧边导航栏**：底部 tab 改为可展开 / 收起的左侧栏，宽窗窄窗都好用。
- **历史课程抽屉（移动制）**：常用课程一次入库，拖来拖去总量守恒——同一门课同一时刻只在一处，不复制、不丢。
- **托盘常驻**：大窗口关闭不再退出程序，后台继续专注；托盘图标一键唤回。
- **迷你药丸模式**：极小倒计时胶囊，贴边吸附 / 自由悬停可切换，双击还原完整窗口。
- **概览页重排**：今日目标完成度 + 正在进行任务（可勾选）+ 今日日程时间轴 + 快速统计，一屏掌握当天。
- **设置开关全部生效**：显示帧率、清除日志、呼吸 / 鼠标 / 音频光晕、主题 / 强调色 / 字体、迷你 / 置顶 / 开机启动——每个按钮都有真实效果与持久化。
- **呼吸光晕恢复**：专注开始光晕随呼吸收放、数字随呼吸起伏（低成本 `transform/opacity`，无模糊，不崩）。
- **本地音乐持久化**：导入一次，重启自动恢复播放列表，点歌即播。

---

## 🚀 快速开始

1. 前往 [Releases](https://github.com/raojiayong-lab/FocusDeck/releases) 下载 `FocusDeck.exe`
2. 双击运行（需已安装 Edge / WebView2 运行库，Win10 / 11 通常自带）
3. 若 Windows 提示「SmartScreen 未知发布者」，点「仍要运行」即可（个人开源项目，无代码签名）

> 想直接体验网页版？用浏览器打开仓库里的 `index.html`，核心界面即可运行（音乐 / 导出等依赖本地文件的功能在浏览器中受限）。

## 🌐 在线试用（GitHub Pages · 已同步 2.0）

不用下载，浏览器直接体验完整界面（数据仅保存在你当前浏览器）：

👉 **https://raojiayong-lab.github.io/FocusDeck/**

> 在线版为只读体验：音乐 / 导出等依赖本地文件的功能在浏览器中受限，桌面 `FocusDeck.exe` 拥有全部能力。

---

## 🛠 构建（开发者）

需要 **Python 3.14** + `pywebview` + `PyInstaller` + `pystray` + `Pillow`：

```bash
pip install pywebview PyInstaller pystray Pillow
python -m PyInstaller --noconfirm --onefile --noconsole ^
  --name FocusDeck --icon icon.ico --noupx ^
  --add-data "index.html;." --add-data "icon.ico;." app.py
```

生成的 `dist/FocusDeck.exe` 即为可分发的单文件程序。也可以直接运行仓库里的 `build.bat`（Windows）一键打包。

> 打包说明：`FocusDeck.spec` 已配置 `hiddenimports=['pystray._win32','pystray._util','PIL','six']`（pystray 的 win32 后端为懒加载，静态分析不会自动收集，漏掉会运行时 `ModuleNotFoundError`）；`upx=False` 以避免杀软误报与解压崩溃。

## 📁 项目结构

```
app.py            # pywebview 外壳 + 本地 API（状态保存 / 音乐导入 / 托盘 / 窗口控制 / 崩溃取证）
index.html        # 主界面（CSS + HTML + JS 单文件）
icon.ico          # 程序图标
make_icon.py      # 图标生成脚本
build.bat         # 一键打包（PyInstaller）
FocusDeck.spec    # PyInstaller 配置（相对路径，仓库通用）
```

---

## 💡 为什么流畅、不崩？

传统桌面 Widget 常把光晕做成「渐变中心随鼠标变量变化 + 全窗 `backdrop-filter` 模糊」，鼠标一动就触发**全屏重绘 + 大模糊重算**，低端 GPU 直接卡死。FocusDeck 改用：

- **默认软件渲染**，禁用全窗 `backdrop-filter` 与大模糊，改用不透明界面表面；
- 光晕层放大、渐变中心**固定**，鼠标跟随用 `translate`、呼吸 / 律动用 `scale`——都是合成友好的低成本属性，不触发每帧全窗重排重绘；
- 呼吸收放只用 `transform: scale()` + `opacity`，绝不做 `filter:blur` 每帧全窗重算；
- 软件渲染下对模糊 / 全窗重绘类动画做 `isLite()` 门禁，CPU 平稳不拉满。

结果：即使在软件渲染下，跟随 / 呼吸 / 律动也保持流畅、稳定不崩。

## 🐞 崩溃了怎么办？

数据目录 `%APPDATA%\FocusDeck\` 下有三件套日志，可定位到代码行（不会静默闪退）：

| 日志 | 内容 |
|------|------|
| `crash.log` | Python 层异常（含 JS API 回调错误），带时间戳 |
| `faulthandler.log` | C 层崩溃（SIGSEGV / ctypes 栈错位 / SIGABRT） |
| `logs/<日期>/session-*.log` | 每次启动的阶段轨迹（START / READY / EXIT） |

## 🤝 贡献

欢迎提 Issue / PR！本项目使用 [MIT](LICENSE) 协议。

## 📄 许可证

[MIT](LICENSE) © 2026 raojiayong-lab
