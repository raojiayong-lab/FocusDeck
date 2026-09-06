# Changelog

所有重要变更记录于此。格式参考 [Keep a Changelog](https://keepachangelog.com/)，版本号遵循 [SemVer](https://semver.org/)。

---

## [2.0.0] - 2026-09-06

### ✨ 新增（New Features）

- **侧边导航栏**：底部 tab 改为可展开 / 收起的左侧栏，状态持久化 `S.ui.sidebarOpen`。
- **历史课程抽屉（移动制）**：日程页「周一」左侧新增可收起抽屉，课程以移动制沉淀复用——拖入课表即从库移除、拖回库即从课表移除，同一门课同刻只在一处，总量守恒。容量设计容纳 40+ 条。
- **系统托盘常驻**：大窗口「关闭」改为 `window.hide()` 缩到托盘后台运行，计时 / 音乐不中断；托盘菜单支持「打开 / 隐藏」「迷你模式」「退出」。基于 `pystray` + `Pillow`。
- **迷你药丸模式**：极小倒计时胶囊（仅 `mm:ss` + 状态点），可拖动、靠近屏幕边缘（左 / 右 / 上）自动吸附、拖离恢复自由浮动、双击退出迷你；吸附开关 `S.ui.pillDock` 默认开启。
- **概览页重排**：今日目标完成度环 + 正在进行任务（可勾选，同步任务页）+ 今日日程时间轴（按开始时间排序、可标记完成）+ 快速统计，一屏掌握当天。
- **本地音乐持久化**：`api('importMusic')` 弹系统文件夹框导入，复制到 `%APPDATA%\FocusDeck\music\`，元数据写入 `S.music` 双写；重启自动恢复播放列表，免重复导入。
- **设置页开关全面生效**：新增 / 修复「显示帧率」（从 `isLite()` 门禁豁免，软件渲染下也显示实时 FPS）、「清除日志」（真删 `%APPDATA%\FocusDeck` 下 logs / crash.log / faulthandler.log）、呼吸 / 鼠标 / 音频光晕、主题 / 强调色 / 字体、迷你 / 置顶 / 开机启动。

### 🐞 修复（Fixes）

- 恢复专注开始时的**呼吸光晕收放**与**倒计时数字互动呼吸**（此前为防 CPU 拉满被过度关闭；现改为禁 `filter:blur`、改用低成本 `transform/opacity`，从 `isLite()` 门禁豁免）。
- 修复日程事件编辑弹窗「备注」`textarea` 无法聚焦 / 输入的问题（遮罩层级 / `pointer-events` / 误加 `readonly` 等排查方向）。
- 修复「显示帧率」开关无效（被 `isLite()` 门禁掐死，已改为只更新角落小数字、无模糊重绘，强制豁免）。
- 内联确认弹窗统一关闭机制（按钮 / ESC / 点击遮罩 / 超时自动消失兜底），避免「点不动、卡死」的无效弹窗。

### ⚙️ 稳定性 & 工程

- 默认**软件渲染**（`WEBVIEW2_ADDITIONAL_BROWSER_ARGUMENTS=--disable-gpu --disable-gpu-compositing --disable-gpu-rasterization`），防低端 GPU 的 TDR 崩溃；`running.flag` 看门狗侦测意外崩溃后自动回退软件渲染。
- `isLite()` 门禁只禁模糊 / 全窗重绘类动画，不禁用低成本 `transform/opacity` 轻动画（呼吸 / 帧率数字）。
- 崩溃取证三件套常驻：`sys.excepthook` + `threading.excepthook`（写 `crash.log`）+ `faulthandler.enable(file=faulthandler.log)`。
- 打包：`FocusDeck.spec` 补 `hiddenimports=['pystray._win32','pystray._util','PIL','six']`，`upx=False`，路径改为相对（仓库通用）。

### ⚠️ 已知限制

- 窗口手感、TDR、托盘交互等**只能真机验证**；沙箱无 GPU / 无真实显示会话，无法复现。
- 「AI 拆分任务 / 自习室 / 团队 / 环境监测」等依赖后端或密钥的能力仍为占位，沙箱无外网未实现。

---

## [1.x] - 早期稳定基线

- 无边框浮窗 + 五页仪表盘 + 番茄钟 + 任务 + 周视图日程 + 专注统计。
- 窗口缩放 / 拖动 / 最大化通过 Win32 ctypes（`EnumWindows` + PID 取句柄、`start_drag()`、`SendMessage(WM_NCLBUTTONDOWN)`）实现，解决「窗口调不动 / 闪退」。
- 默认软件渲染 + `isLite()` 门禁，解决「点就卡、卡了就崩」。
