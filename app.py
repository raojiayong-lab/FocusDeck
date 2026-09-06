# -*- coding: utf-8 -*-
"""
FocusDeck Pro — 桌面外壳
========================
基于 pywebview (Edge WebView2) 的无边框悬浮窗：
  · 始终置顶 / 可切换
  · Win32 原生拖拽与八向缩放（平滑、带最小尺寸与屏幕边界约束）
  · 界面缩放（CSS zoom 60%~160%）
  · 窗口透明度
  · 几何位置、配置与应用数据持久化到 %APPDATA%\\FocusDeck
"""

import atexit
import ctypes
import datetime
import json
import os
import subprocess
import sys
import threading
import time
import traceback
import winreg
from ctypes import wintypes

# ----------------------------------------------------------------------------
# 稳定性：全局禁用 WebView2 GPU（必须在 WebView2 环境初始化前设置）。
# 该机 GPU 渲染触发 WebView2 合成器崩溃（C 层、无 Python 异常、无转储，
# 表现为启动 1~2 分钟后进程无痕退出 / 卡死）；软渲染回退只降级前端特效，
# 并未关闭 WebView2 自身的 GPU 合成，因此必须显式传 --disable-gpu。
# 若用户已在外部设置此变量（如调试），尊重外部值。
# ----------------------------------------------------------------------------
os.environ.setdefault(
    'WEBVIEW2_ADDITIONAL_BROWSER_ARGUMENTS',
    '--disable-gpu --disable-gpu-compositing',
)


# ----------------------------------------------------------------------------
# 崩溃兜底：任何未捕获异常都写进 %APPDATA%\FocusDeck\crash.log，
# 避免“直接闪退、无任何线索”。（用户把日志发回即可定位）
# ----------------------------------------------------------------------------
def _exit_log(msg):
    try:
        d = os.path.join(os.environ.get('APPDATA') or os.path.expanduser('~'), 'FocusDeck')
        os.makedirs(d, exist_ok=True)
        with open(os.path.join(d, 'exit.log'), 'a', encoding='utf-8') as f:
            f.write('%s  %s\n' % (time.strftime('%Y-%m-%d %H:%M:%S'), msg))
    except Exception:
        pass


# ----------------------------------------------------------------------------
# 系统托盘常驻：大窗口关闭后隐藏到托盘后台继续运行（计时/音乐不中断）。
# pystray 缺失时不至于 import 崩溃：hide_to_tray 返回 False，前端退化为直接退出。
# 托盘回调运行在 pystray 自己的线程，严禁在其中 evaluate_js（原生 SIGSEGV），
# 需要刷新前端一律走 _push_py_cmd 队列 + 前端轮询（见 poll_py_cmd）。
# ----------------------------------------------------------------------------
try:
    import pystray
    from PIL import Image
    _TRAY_OK = True
except Exception as _tray_import_err:
    pystray = None
    Image = None
    _TRAY_OK = False
    _exit_log('TRAY_LIB_MISSING: %r' % (_tray_import_err,))
_TRAY_ICON = None   # 全局托盘图标引用：避免线程中对象被 GC 导致图标消失



def _log_crash(typ, val, tb):
    try:
        try:
            os.makedirs(d, exist_ok=True)
        except OSError:
            d = os.path.dirname(os.path.abspath(sys.executable))
        with open(os.path.join(d, 'crash.log'), 'a', encoding='utf-8') as f:
            f.write(time.strftime('%Y-%m-%d %H:%M:%S') + '  CRASH: %s: %s\n' % (getattr(typ, '__name__', str(typ)), val))
            try:
                f.write(''.join(traceback.format_exception(typ, val, tb)))
            except Exception:
                f.write('(no traceback)\n')
            f.write('---\n')
    except Exception:
        pass


sys.excepthook = _log_crash
# pywebview 的 JS→Python 调用（api 方法）运行在独立线程上，未捕获异常会走
# threading.excepthook 而非 sys.excepthook，必须单独挂上，否则 on_ready/drag
# 等里的异常被静默吞掉，表现为“闪退且无任何日志”。
def _thread_exc(args):
    try:
        _log_crash(args.exc_type, args.exc_value, args.exc_traceback)
    except Exception:
        pass
threading.excepthook = _thread_exc
# faulthandler：捕获 C 层崩溃（ctypes 栈错位 / SIGSEGV / SIGABRT 等）。这类
# 崩溃不抛 Python 异常、sys.excepthook 也收不到，是“闪退无日志”的真凶。
# 在 main() 尽早 enable，把 Python 调用栈 + C 栈写到 faulthandler.log。
import faulthandler

# 渲染策略：稳定优先，默认软件渲染（禁用 GPU）。
# 用户机器上 GPU 合成/光栅化会触发 TDR 崩溃（启动黑屏 3~4 秒、点击最大化即崩）。
# 具体实现见 main() 开头（必须在 import webview 之前设置 WEBVIEW2_ADDITIONAL_BROWSER_ARGUMENTS）：
#   · 默认软件渲染（--disable-gpu ...）
#   · swrender.flag 存在 → 软件（此前崩溃过）
#   · gpu.optin 存在（无 flag）→ 用户主动开启 GPU
#   · running.flag 残留（上次非正常退出）→ 下次启动立即强制软件，不等看门狗
# 用户在「设置→重置为 GPU」可写 gpu.optin 重新尝试 GPU；若再崩则自动回软件。

# ----------------------------------------------------------------------------
# 常量
# ----------------------------------------------------------------------------
APP_NAME = 'FocusDeck'
MIN_W, MIN_H = 360, 400   # 手动缩放最小尺寸：保证标题栏与主面板完整可操作（240x96 太小会挤压错位/找不到按钮）
COMPACT_W, COMPACT_H = 120, 44   # 迷你药丸模式尺寸（倒计时胶囊 120x44，见 _save_geom 中 300/180 防呆阈值）
DOCK_PX = 14             # 药丸贴边吸附阈值（距工作区边缘的物理像素距离）
DRAG_POLL = 0.008

WM_CLOSE = 0x0010
WM_NCLBUTTONDOWN = 0x00A1
VK_LBUTTON = 0x01
VK_ESCAPE = 0x1B
SW_MINIMIZE = 6
SW_MAXIMIZE = 3
SW_RESTORE = 9
SWP_NOZORDER = 0x0004
SWP_NOACTIVATE = 0x0010
HWND_TOPMOST = -1
HWND_NOTOPMOST = -2
MONITOR_DEFAULTTONEAREST = 2
GWL_EXSTYLE = -20
WS_EX_LAYERED = 0x00080000
LWA_ALPHA = 0x00000002

# 窗口命令：统一走 UI 线程的消息（而不是从 API 工作线程直接 ShowWindow/SetWindowPos），
# 彻底消除「Python 线程改 HWND ↔ WebView2 UI 线程改窗口」的竞态——这是
# “最大化没反应 / 点击就卡 / 点一下就崩”的头号根因。
WM_SYSCOMMAND = 0x0112
SC_MOVE = 0xF010
SC_SIZE = 0xF000
SC_MAXIMIZE = 0xF030
SC_MINIMIZE = 0xF020
SC_RESTORE = 0xF120
HTCAPTION = 2
HTLEFT = 10
HTRIGHT = 11
HTTOP = 12
HTTOPLEFT = 13
HTTOPRIGHT = 14
HTBOTTOM = 15
HTBOTTOMLEFT = 16
HTBOTTOMRIGHT = 17

# WM_NCHITTEST 子类化方案已废弃（见交接说明「别再试」），仅保留 SetWindowLongPtrW
# 换 GWL_EXSTYLE 用于透明通道的 _SetWindowLong；此处不再声明废弃常量。

# ----------------------------------------------------------------------------
# Win32
# ----------------------------------------------------------------------------
user32 = ctypes.WinDLL('user32', use_last_error=True)
shcore = ctypes.WinDLL('shcore', use_last_error=True)
kernel32 = ctypes.WinDLL('kernel32', use_last_error=True)

user32.GetCursorPos.argtypes = [ctypes.POINTER(wintypes.POINT)]
user32.GetCursorPos.restype = wintypes.BOOL
user32.SetWindowPos.argtypes = [wintypes.HWND, wintypes.HWND,
                                ctypes.c_int, ctypes.c_int,
                                ctypes.c_int, ctypes.c_int, wintypes.UINT]
user32.SetWindowPos.restype = wintypes.BOOL
user32.GetWindowRect.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.RECT)]
user32.GetWindowRect.restype = wintypes.BOOL
user32.MonitorFromWindow.argtypes = [wintypes.HWND, wintypes.DWORD]
user32.MonitorFromWindow.restype = wintypes.HMONITOR
user32.GetAsyncKeyState.argtypes = [ctypes.c_int]
user32.GetAsyncKeyState.restype = ctypes.c_short
user32.GetDpiForWindow.argtypes = [wintypes.HWND]
user32.GetDpiForWindow.restype = wintypes.UINT
user32.PostMessageW.argtypes = [wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]
user32.SendMessageW.argtypes = [wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]
user32.SendMessageW.restype = wintypes.LPARAM
user32.SetLayeredWindowAttributes.argtypes = [wintypes.HWND, wintypes.COLORREF,
                                              wintypes.BYTE, wintypes.DWORD]
user32.GetSystemMetrics.argtypes = [ctypes.c_int]
user32.GetSystemMetrics.restype = ctypes.c_int
user32.FindWindowW.argtypes = [wintypes.LPCWSTR, wintypes.LPCWSTR]
user32.FindWindowW.restype = wintypes.HWND

try:
    # 64 位下 SetWindowLongPtrW/GetWindowLongPtrW 返回 LONG_PTR（64 位指针宽度）。
    # 不声明 restype 时 ctypes 默认按 32 位 c_int 读取返回值 → 栈错位 → 进程直接崩。
    user32.SetWindowLongPtrW.argtypes = [wintypes.HWND, ctypes.c_int, ctypes.c_void_p]
    user32.SetWindowLongPtrW.restype = ctypes.c_void_p
    user32.GetWindowLongPtrW.argtypes = [wintypes.HWND, ctypes.c_int]
    user32.GetWindowLongPtrW.restype = ctypes.c_void_p
    _SetWindowLong = user32.SetWindowLongPtrW
    _GetWindowLong = user32.GetWindowLongPtrW
except AttributeError:  # 32 位 Python
    user32.SetWindowLongW.argtypes = [wintypes.HWND, ctypes.c_int, ctypes.c_int]
    user32.SetWindowLongW.restype = ctypes.c_int
    user32.GetWindowLongW.argtypes = [wintypes.HWND, ctypes.c_int]
    user32.GetWindowLongW.restype = ctypes.c_int
    _SetWindowLong = user32.SetWindowLongW
    _GetWindowLong = user32.GetWindowLongW


class MONITORINFO(ctypes.Structure):
    _fields_ = [
        ('cbSize', wintypes.DWORD),
        ('rcMonitor', wintypes.RECT),
        ('rcWork', wintypes.RECT),
        ('dwFlags', wintypes.DWORD),
    ]


user32.GetMonitorInfoW.argtypes = [wintypes.HMONITOR, ctypes.POINTER(MONITORINFO)]
user32.GetMonitorInfoW.restype = wintypes.BOOL

# 显示器枚举回调类型（必须在模块级声明，供 EnumDisplayMonitors 的 argtypes 使用）
_MONITORENUMPROC = ctypes.WINFUNCTYPE(
    wintypes.BOOL, wintypes.HMONITOR, wintypes.HDC,
    ctypes.POINTER(wintypes.RECT), wintypes.LPARAM,
)
user32.EnumDisplayMonitors.argtypes = [
    wintypes.HDC, ctypes.POINTER(wintypes.RECT), _MONITORENUMPROC, wintypes.LPARAM,
]
user32.EnumDisplayMonitors.restype = wintypes.BOOL


class FLASHWINFO(ctypes.Structure):
    _fields_ = [
        ('cbSize', wintypes.UINT),
        ('hwnd', wintypes.HWND),
        ('dwFlags', wintypes.DWORD),
        ('uCount', wintypes.UINT),
        ('dwTimeout', wintypes.DWORD),
    ]


user32.FlashWindowEx.argtypes = [ctypes.POINTER(FLASHWINFO)]
user32.FlashWindowEx.restype = wintypes.BOOL

# 窗口句柄有效性校验（hwnd 缓存使用前检查，窗口重建后自动重查，避免命令发给旧句柄）
user32.IsWindow.argtypes = [wintypes.HWND]
user32.IsWindow.restype = wintypes.BOOL

# 系统运行时长（毫秒）：看门狗据此识别“本线程被系统休眠挂起”造成的假超时
kernel32.GetTickCount64.argtypes = []
kernel32.GetTickCount64.restype = ctypes.c_ulonglong

# 以下函数此前未声明 argtypes/restype，64 位下 ctypes 默认压栈会栈错位 → 进程崩溃（闪退）。
user32.IsZoomed.argtypes = [wintypes.HWND]
user32.IsZoomed.restype = wintypes.BOOL
user32.ShowWindow.argtypes = [wintypes.HWND, wintypes.INT]
user32.ShowWindow.restype = wintypes.BOOL
user32.ReleaseCapture.argtypes = []
user32.ReleaseCapture.restype = wintypes.BOOL

# 单实例互斥（避免多开导致 WebView2 user-data-dir 冲突）
kernel32.CreateMutexW.argtypes = [wintypes.LPCWSTR, wintypes.BOOL, wintypes.LPCWSTR]
kernel32.CreateMutexW.restype = wintypes.HANDLE
kernel32.GetLastError.argtypes = []
kernel32.GetLastError.restype = wintypes.DWORD

# 致命错误提示框（必须声明 argtypes/restype，否则 64 位栈错位）
user32.MessageBoxW.argtypes = [wintypes.HWND, wintypes.LPCWSTR, wintypes.LPCWSTR, wintypes.UINT]
user32.MessageBoxW.restype = ctypes.c_int

# 取窗口句柄：用 EnumWindows + 进程 PID 枚举本进程拥有的顶层窗口。
# 这是最可靠的方式——不依赖窗口标题（frameless 下标题可能未生效），
# 也不依赖 pywebview 内部属性（不同版本属性名不一致，取不到就返回 0，
# 导致所有窗口操作静默失败：“窗口拖不动、按钮按了没反应、只有关闭能用”）。
WNDENUMPROC = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
user32.EnumWindows.argtypes = [WNDENUMPROC, wintypes.LPARAM]
user32.EnumWindows.restype = wintypes.BOOL
user32.GetWindowThreadProcessId.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.DWORD)]
user32.GetWindowThreadProcessId.restype = wintypes.DWORD
user32.GetParent.argtypes = [wintypes.HWND]
user32.GetParent.restype = wintypes.HWND
user32.IsWindowVisible.argtypes = [wintypes.HWND]
user32.IsWindowVisible.restype = wintypes.BOOL


def _enum_hwnds_of_pid(pid):
    """返回本进程拥有的、可见的顶层窗口句柄（按面积从大到小，主窗口在前）。"""
    found = []

    def _cb(hwnd, lparam):
        cur = wintypes.DWORD()
        user32.GetWindowThreadProcessId(wintypes.HWND(hwnd), ctypes.byref(cur))
        if cur.value == pid:
            try:
                parent = user32.GetParent(wintypes.HWND(hwnd))
            except Exception:
                parent = 0
            try:
                visible = user32.IsWindowVisible(wintypes.HWND(hwnd))
            except Exception:
                visible = False
            if not parent and visible:
                found.append(int(hwnd))
        return True

    try:
        user32.EnumWindows(WNDENUMPROC(_cb), 0)
    except Exception:
        pass
    best = []
    for h in found:
        r = wintypes.RECT()
        area = 0
        try:
            if user32.GetWindowRect(wintypes.HWND(h), ctypes.byref(r)):
                area = max(0, r.right - r.left) * max(0, r.bottom - r.top)
        except Exception:
            pass
        best.append((area, h))
    best.sort(reverse=True)
    return [h for _, h in best]


# ----------------------------------------------------------------------------
# 路径
# ----------------------------------------------------------------------------
def base_dir():
    """运行目录（兼容 onefile / onedir 两种打包形态）。

    onedir 下 PyInstaller 会把 --add-data 的数据文件收集到 exe 同级的
    `_internal` 目录，而 sys._MEIPASS 也指向该目录；onefile 下 _MEIPASS 是
    临时解压目录。这里做容错搜索，确保 index.html / icon.ico 都能被找到，
    否则 onedir 形态会因找不到 index.html 直接 SystemExit（表现为“启动即退出”）。
    """
    if getattr(sys, 'frozen', False):
        exe_dir = os.path.dirname(os.path.abspath(sys.executable))
        mp = getattr(sys, '_MEIPASS', None)
        for c in (mp, exe_dir, os.path.join(exe_dir, '_internal')):
            if c and os.path.isfile(os.path.join(c, 'index.html')):
                return c
        return mp or exe_dir
    return os.path.dirname(os.path.abspath(__file__))


def data_dir():
    """可写数据目录（%APPDATA%\\FocusDeck）。"""
    root = os.environ.get('APPDATA') or os.path.expanduser('~')
    d = os.path.join(root, APP_NAME)
    try:
        os.makedirs(d, exist_ok=True)
    except OSError:
        d = os.path.dirname(os.path.abspath(sys.executable))
    return d


CONFIG_PATH = os.path.join(data_dir(), 'config.json')
STATE_PATH = os.path.join(data_dir(), 'state.json')

# 本地音乐库：导入的音频统一复制到 %APPDATA%\FocusDeck\music（扁平存储，
# 同名冲突自动加序号），前端只持久化 {name, rel, path} 元数据，重启自动重建列表。
MUSIC_DIR = os.path.join(data_dir(), 'music')
# 与 index.html 前端 musicImport() 的扩展名白名单保持一致
AUDIO_EXTS = {'.mp3', '.flac', '.wav', '.ogg', '.m4a', '.aac', '.wma', '.opus', '.webm'}
# file:// 不可用时 dataURL 兜底播放的 MIME 映射
AUDIO_MIME = {
    '.mp3': 'audio/mpeg', '.flac': 'audio/flac', '.wav': 'audio/wav',
    '.ogg': 'audio/ogg', '.oga': 'audio/ogg', '.m4a': 'audio/mp4',
    '.aac': 'audio/aac', '.wma': 'audio/x-ms-wma', '.opus': 'audio/ogg',
    '.webm': 'audio/webm',
}

# 渲染模式标记（均在 %APPDATA%\FocusDeck 下）：
#   swrender.flag : 存在 → 强制软件渲染（此前 GPU 崩溃过）
#   gpu.optin     : 存在（且 swrender.flag 不存在）→ 用户主动开启 GPU
#   running.flag  : 进程运行期存在；干净退出时删除。若下次启动仍存在 → 上次非正常退出（崩/被杀）
SWRENDER_FLAG = os.path.join(data_dir(), 'swrender.flag')
GPU_OPTIN = os.path.join(data_dir(), 'gpu.optin')
RUNNING_FLAG = os.path.join(data_dir(), 'running.flag')

# 当前会话的渲染模式（'sw' 软件 / 'gpu' GPU 硬件加速）。由 main() 在计算
# _FORCE_SW 后写入；on_ready() 返回给前端，前端据此决定是否摘除轻量模式标记。
_CURRENT_RENDER_MODE = 'sw'


def resource(*parts):
    return os.path.join(base_dir(), *parts)


def read_json(path, default):
    try:
        with open(path, 'r', encoding='utf-8') as f:
            return json.load(f)
    except Exception:
        return default


def write_json(path, obj):
    tmp = path + '.tmp'
    try:
        with open(tmp, 'w', encoding='utf-8') as f:
            json.dump(obj, f, ensure_ascii=False)
        if os.path.exists(path):
            os.remove(path)
        os.rename(tmp, path)
        return True
    except Exception:
        try:
            if os.path.exists(tmp):
                os.remove(tmp)
        except Exception:
            pass
        return False


# ----------------------------------------------------------------------------
# 启动日志 / 运行时探测 / 致命错误提示（生产环境可观测性）
# ----------------------------------------------------------------------------
def _logs_dir():
    r"""日志根目录 %APPDATA%\FocusDeck\logs（不可写则回退 exe 目录）。"""
    d = os.path.join(data_dir(), 'logs')
    try:
        os.makedirs(d, exist_ok=True)
    except OSError:
        d = os.path.dirname(os.path.abspath(sys.executable))
    return d


_SESSION_LOG = None


def _session_log_path():
    global _SESSION_LOG
    if _SESSION_LOG:
        return _SESSION_LOG
    day = datetime.datetime.now().strftime('%Y-%m-%d')
    daydir = os.path.join(_logs_dir(), day)
    try:
        os.makedirs(daydir, exist_ok=True)
    except OSError:
        daydir = _logs_dir()
    ts = datetime.datetime.now().strftime('%H-%M-%S-%f')[:-3]
    _SESSION_LOG = os.path.join(daydir, 'session-%s.log' % ts)
    return _SESSION_LOG


def log(line, stage=False):
    """追加一行启动日志；stage=True 为阶段标记。"""
    try:
        ts = datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S.%f')[:-3]
        with open(_session_log_path(), 'a', encoding='utf-8') as f:
            f.write('%s %s%s\n' % (ts, '[STAGE] ' if stage else '', line))
    except Exception:
        pass


def log_stage(name):
    log(name, stage=True)


def _sysinfo():
    import platform
    try:
        ver = platform.version()
    except Exception:
        ver = '?'
    try:
        arch = platform.machine()
    except Exception:
        arch = '?'
    return 'OS=%s arch=%s py=%s' % (ver, arch, sys.version.split()[0])


def webview2_runtime_version():
    """探测本机 WebView2 运行时版本；缺失返回 None。"""
    # 1) 注册表（Evergreen 安装）
    try:
        for root in (winreg.HKEY_LOCAL_MACHINE, winreg.HKEY_CURRENT_USER):
            for key in (
                r'SOFTWARE\Microsoft\EdgeWebView\Applications',
                r'SOFTWARE\WOW6432Node\Microsoft\EdgeWebView\Applications',
            ):
                try:
                    k = winreg.OpenKey(root, key)
                    try:
                        i = 0
                        while True:
                            sub = winreg.EnumKey(k, i)
                            return sub
                    except OSError:
                        pass
                    finally:
                        winreg.CloseKey(k)
                except OSError:
                    pass
    except Exception:
        pass
    # 2) 文件系统
    for base in (
        os.environ.get('ProgramFiles(x86)'),
        os.environ.get('ProgramFiles'),
        os.path.join(os.environ.get('LOCALAPPDATA', ''), 'Microsoft', 'EdgeWebView'),
    ):
        if not base:
            continue
        p = os.path.join(base, 'Microsoft', 'EdgeWebView', 'Application')
        if os.path.isdir(p):
            try:
                vs = [d for d in os.listdir(p) if os.path.isdir(os.path.join(p, d))]
                if vs:
                    return vs[0]
            except Exception:
                pass
    return None


def _fatal(title, msg):
    """致命错误：弹中文 MessageBox 并写日志，避免“静默闪退”。"""
    try:
        log('FATAL: %s | %s' % (title, msg))
    except Exception:
        pass
    try:
        user32.MessageBoxW(0, str(msg), str(title), 0x10)  # MB_ICONERROR
    except Exception:
        pass


def render_state_path():
    return os.path.join(data_dir(), 'render_state.json')


# ----------------------------------------------------------------------------
# 显示器信息
# ----------------------------------------------------------------------------
def enum_monitors():
    """返回所有显示器的工作区矩形（物理像素）。任何异常都安全降级为单显示器。"""
    try:
        rects = []
        MONITORENUMPROC = _MONITORENUMPROC

        def _cb(hmon, hdc, lprc, lparam):
            try:
                mi = MONITORINFO()
                mi.cbSize = ctypes.sizeof(MONITORINFO)
                if user32.GetMonitorInfoW(hmon, ctypes.byref(mi)):
                    r = mi.rcWork
                    rects.append((r.left, r.top, r.right, r.bottom))
            except Exception:
                pass
            return True

        user32.EnumDisplayMonitors(None, None, MONITORENUMPROC(_cb), 0)
        if rects:
            return rects
    except Exception:
        pass
    w = user32.GetSystemMetrics(0)
    h = user32.GetSystemMetrics(1)
    return [(0, 0, w, h)]


def monitor_of(hwnd):
    mon = user32.MonitorFromWindow(wintypes.HWND(hwnd), MONITOR_DEFAULTTONEAREST)
    mi = MONITORINFO()
    mi.cbSize = ctypes.sizeof(MONITORINFO)
    if user32.GetMonitorInfoW(mon, ctypes.byref(mi)):
        r = mi.rcWork
        return r.left, r.top, r.right - r.left, r.bottom - r.top
    return 0, 0, user32.GetSystemMetrics(0), user32.GetSystemMetrics(1)


def is_on_screen(x, y, w, h):
    cx, cy = x + w // 2, y + h // 2
    for (l, t, r, b) in enum_monitors():
        if l <= cx < r and t <= cy < b:
            return True
    return False


# ----------------------------------------------------------------------------
# JS API
# ----------------------------------------------------------------------------
class Api:
    """暴露给前端的 window.pywebview.api。所有方法在独立线程中执行。"""

    def __init__(self, config):
        self.config = config
        self._window = None
        self._state_lock = threading.Lock()
        self._state_timer = None
        self._last_state_text = None
        self._restored = None        # 最大化前的原始矩形 (x,y,w,h)
        self._maximized = False      # 当前是否处于最大化状态（用自有标记，避免依赖 IsZoomed 样式）
        self._last_beat = 0          # 前端心跳时间戳（看门狗据此判断渲染进程是否存活）
        self._app_state = 'BOOTING'  # BOOTING|LOADING|READY|SHUTTING_DOWN（看门狗据此判定，避免误杀）
        self._closing = False        # 关闭流程进行中：拒绝新窗口操作、看门狗不再销毁窗口
        self._tray_hidden = False    # 窗口是否已隐藏到托盘（隐藏期间看门狗跳过心跳判定）
        self._py_cmds = []           # Python → 前端命令队列（托盘回调等非 JS 线程禁止 evaluate_js）
        self._py_lock = threading.Lock()
        self._ready_at = 0

    # ---- 句柄 -----------------------------------------------------------
    def hwnd(self):
        """取窗口句柄。最可靠的方式是按进程 PID 枚举顶层窗口（不依赖标题/
        pywebview 内部属性）；取不到时回退到 pywebview 原生句柄与 FindWindowW。
        首次取到后缓存；每次使用前用 IsWindow 校验缓存句柄仍有效——窗口被重建
        （渲染进程重启/异常恢复等场景）后旧句柄会失效，若不重查，所有窗口操作
        （拖拽/缩放/置顶/最小化）都会发给无效句柄而静默失败，表现为“按钮没反应”。"""
        cached = getattr(self, '_hwnd_cache', 0)
        if cached:
            try:
                if user32.IsWindow(wintypes.HWND(cached)):
                    return cached
            except Exception:
                pass
            # 缓存句柄已失效：清空缓存，走下方完整枚举流程重新获取
            try:
                self._hwnd_cache = 0
            except Exception:
                pass
        h = 0
        # 1) 进程 PID 枚举（最可靠，frameless 下标题/内部属性都可能取不到）
        try:
            for cand in _enum_hwnds_of_pid(os.getpid()):
                if cand:
                    h = cand
                    break
        except Exception:
            h = 0
        # 2) pywebview 原生句柄（不同版本属性名不同，逐个尝试）
        if not h:
            w = self._window
            if w is not None:
                native = getattr(w, 'native', None)
                if native is not None:
                    for attr in ('Handle', 'hwnd', '_hwnd'):
                        v = getattr(native, attr, None)
                        if v:
                            try:
                                h = int(v) or 0
                                if h:
                                    break
                            except Exception:
                                h = 0
                    if not h:
                        inner = getattr(native, 'native', None)
                        if inner is not None:
                            for attr in ('Handle', 'hwnd', '_hwnd'):
                                v = getattr(inner, attr, None)
                                if v:
                                    try:
                                        h = int(v) or 0
                                        if h:
                                            break
                                    except Exception:
                                        h = 0
        # 3) FindWindow by title（frameless 下可能未生效，仅作兜底）
        if not h:
            try:
                fw = user32.FindWindowW(None, 'FocusDeck Pro')
                if fw:
                    h = int(fw) or 0
            except Exception:
                h = 0
        if h:
            self._hwnd_cache = h
        return h

    # ---- 配置 / 数据 ----------------------------------------------------
    def get_cfg(self):
        return read_json(CONFIG_PATH, {})

    def save_cfg(self, patch):
        try:
            patch = json.loads(patch) if isinstance(patch, str) else (patch or {})
        except Exception:
            return False
        with self._state_lock:
            cfg = read_json(CONFIG_PATH, {})
            cfg.update(patch)
            write_json(CONFIG_PATH, cfg)
        try:
            self.config.update(patch)   # 同步内存态，供 drag/_dock_after_drag 即时读取
        except Exception:
            pass
        if 'topmost' in patch:
            self.set_topmost(bool(patch['topmost']))
        # 稳定性：暂不应用窗口透明度（WS_EX_LAYERED 易致 WebView2 渲染进程崩溃）
        return True

    def load_state(self):
        try:
            with open(STATE_PATH, 'r', encoding='utf-8') as f:
                text = f.read()
        except Exception:
            return None
        # 服务端兜底迁移：老版本 state 可能没有 mouseGlow 键（旧默认 false），
        # 补齐为 true（产品默认开启跟手光晕）；显式 false 表示用户主动关闭，
        # 保持尊重、不强开。
        try:
            import json as _json
            st = _json.loads(text)
            s = st.get('s')
            if isinstance(s, dict) and 'mouseGlow' not in s:
                s['mouseGlow'] = True
                text = _json.dumps(st, ensure_ascii=False)
                try:
                    tmp = STATE_PATH + '.tmp'
                    with open(tmp, 'w', encoding='utf-8') as f:
                        f.write(text)
                    os.remove(STATE_PATH)
                    os.rename(tmp, STATE_PATH)
                except Exception:
                    pass
        except Exception:
            pass
        return text

    def save_state(self, text):
        """防抖写入，避免高频 IO。同时缓存最近一次文本，供退出时同步落盘。"""
        self._last_state_text = text

        def _flush():
            with self._state_lock:
                try:
                    tmp = STATE_PATH + '.tmp'
                    with open(tmp, 'w', encoding='utf-8') as f:
                        f.write(self._last_state_text)
                    if os.path.exists(STATE_PATH):
                        os.remove(STATE_PATH)
                    os.rename(tmp, STATE_PATH)
                except Exception:
                    pass

        if self._state_timer and self._state_timer.is_alive():
            self._state_timer.cancel()
        t = threading.Timer(0.5, _flush)
        t.daemon = True
        self._state_timer = t
        t.start()
        return True

    def _flush_state_now(self):
        """取消待执行的防抖定时器并立即把最近一次状态落盘（退出前调用，避免丢数据）。"""
        if self._state_timer and self._state_timer.is_alive():
            self._state_timer.cancel()
            self._state_timer = None
        if self._last_state_text is None:
            return
        with self._state_lock:
            try:
                tmp = STATE_PATH + '.tmp'
                with open(tmp, 'w', encoding='utf-8') as f:
                    f.write(self._last_state_text)
                if os.path.exists(STATE_PATH):
                    os.remove(STATE_PATH)
                os.rename(tmp, STATE_PATH)
            except Exception:
                pass

    # ---- 本地音乐库（导入持久化）---------------------------------------
    # 说明：这些 api 方法运行在 pywebview 独立工作线程，复制文件/扫描目录
    # 不会阻塞前端 UI 线程；导入完成由前端拿到返回值后自行刷新列表，
    # 严禁在此处 evaluate_js（铁律 8，原生 SIGSEGV 风险）。
    def _music_dir(self):
        """确保音乐库目录存在并返回其绝对路径。"""
        d = MUSIC_DIR
        try:
            os.makedirs(d, exist_ok=True)
        except OSError:
            d = os.path.join(data_dir(), 'music')
            try:
                os.makedirs(d, exist_ok=True)
            except OSError:
                pass
        return d

    def importMusic(self):
        """弹系统文件夹选择框，扫描所选文件夹（含子目录）内的音频，
        复制到音乐库目录（扁平、重名自动加序号），返回新入库清单。
        返回 None=取消/失败；成功返回 {added:[{name,rel,path}], failed:[...], skipped:n}。"""
        try:
            import webview
        except Exception:
            return {'error': 'webview_unavailable'}
        try:
            win = self._window
            if win is None:
                return {'error': 'window_not_ready'}
            folders = win.create_file_dialog(webview.FOLDER_DIALOG, allow_multiple=True)
        except Exception as e:
            _log_crash(RuntimeError, 'import_music.dialog: %r' % (e,), None)
            return {'error': 'dialog_failed'}
        if not folders:
            return {'cancelled': True}
        if isinstance(folders, str):
            folders = [folders]

        base = self._music_dir()
        added, failed, skipped, existing = [], [], 0, []
        seen_src = set()
        src_files = []
        for folder in folders:
            if not folder or not os.path.isdir(folder):
                continue
            for root, _dirs, names in os.walk(folder):
                for fn in names:
                    try:
                        ext = os.path.splitext(fn)[1].lower()
                    except Exception:
                        continue
                    if ext not in AUDIO_EXTS:
                        continue
                    full = os.path.join(root, fn)
                    try:
                        if os.path.getsize(full) <= 0:
                            continue
                    except Exception:
                        continue
                    src_files.append(full)
        src_files.sort(key=lambda p: os.path.basename(p).lower())
        for full in src_files:
            try:
                real = os.path.realpath(full)
                if real in seen_src:
                    continue
                seen_src.add(real)
            except Exception:
                pass
            fname = os.path.basename(full)
            try:
                size = os.path.getsize(full)
            except Exception:
                continue
            # 目标已存在且大小相同：视为该曲目已在音乐库。仍把文件信息返回，
            # 以便前端在「播放列表已丢失/换机后重导同一文件夹」时恢复进列表。
            target = os.path.join(base, fname)
            try:
                if os.path.exists(target) and os.path.getsize(target) == size:
                    skipped += 1
                    rel = fname
                    existing.append({'name': os.path.splitext(fname)[0], 'rel': rel, 'path': os.path.join(base, rel)})
                    continue
            except Exception:
                pass
            dest = self._unique_music_name(fname)
            try:
                import shutil
                shutil.copy2(full, os.path.join(base, dest))
                rel = dest
                name = os.path.splitext(fname)[0]
                added.append({'name': name, 'rel': rel, 'path': os.path.join(base, rel)})
            except Exception as e:
                failed.append({'name': fname, 'reason': str(e) or 'copy_failed'})
        return {'added': added, 'existing': existing, 'failed': failed, 'skipped': skipped}

    def _unique_music_name(self, fname):
        """重名冲突时追加 (2)/(3)... 序号，返回不冲突的目标文件名。"""
        base_name, ext = os.path.splitext(fname)
        base_dir = self._music_dir()
        cand = fname
        n = 2
        while os.path.exists(os.path.join(base_dir, cand)):
            cand = '%s (%d)%s' % (base_name, n, ext)
            n += 1
        return cand

    def music_dir_size(self):
        """音乐库目录占用字节数（用于设置页展示）。"""
        total = 0
        base = self._music_dir()
        try:
            for root, _dirs, names in os.walk(base):
                for fn in names:
                    try:
                        total += os.path.getsize(os.path.join(root, fn))
                    except Exception:
                        pass
        except Exception:
            pass
        return total

    def _safe_rel(self, rel):
        """校验 rel 是音乐库根目录下的扁平文件名（防路径穿越）。非法返回 None。"""
        if not rel or not isinstance(rel, str):
            return None
        if os.path.basename(rel) != rel:
            return None
        if rel.startswith('.'):
            return None
        if '/' in rel or '\\' in rel or ':' in rel:
            return None
        return rel

    def music_remove(self, rels, delete_file):
        """从音乐库删除文件（前端已做二次确认）。

        rels 可为单个文件名或文件名列表，仅允许 music 目录内的扁平文件名；
        delete_file=True 时同时删除磁盘文件，False 仅清理引用（由前端移除元数据）。
        返回 {removed: n, failed: [{name, reason}]}。
        """
        if isinstance(rels, str):
            rels = [rels]
        if not isinstance(rels, (list, tuple)):
            rels = []
        base = self._music_dir()
        removed, failed = 0, []
        for rel in rels:
            safe = self._safe_rel(rel)
            if not safe:
                failed.append({'name': str(rel)[:60], 'reason': 'invalid_rel'})
                continue
            if not delete_file:
                removed += 1
                continue
            try:
                path = os.path.join(base, safe)
                if os.path.exists(path):
                    os.remove(path)
                removed += 1
            except Exception as e:
                failed.append({'name': safe, 'reason': str(e) or 'remove_failed'})
        return {'removed': removed, 'failed': failed}

    def music_cleanup(self, rels):
        """删除音乐库中不在当前播放列表（rels 白名单）内的遗留文件。
        用户主动点击「清理未使用」并二次确认后才调用。返回 {removed: n, failed: [...]}。"""
        keep = set()
        if isinstance(rels, str):
            rels = [rels]
        if isinstance(rels, (list, tuple)):
            for rel in rels:
                safe = self._safe_rel(rel)
                if safe:
                    keep.add(safe)
        base = self._music_dir()
        removed, failed = 0, []
        try:
            for fn in os.listdir(base):
                if not os.path.isfile(os.path.join(base, fn)):
                    continue
                if fn in keep:
                    continue
                try:
                    os.remove(os.path.join(base, fn))
                    removed += 1
                except Exception as e:
                    failed.append({'name': fn, 'reason': str(e) or 'remove_failed'})
        except Exception as e:
            failed.append({'name': '(dir)', 'reason': str(e) or 'scan_failed'})
        return {'removed': removed, 'failed': failed}

    def music_read(self, rel):
        """file:// 播放受限时的兜底：读取单曲文件并以 dataURL 素材返回。
        超过 20MB 拒绝（避免 pywebview 大字符串传输卡顿）。返回 {mime, b64} 或 None。"""
        safe = self._safe_rel(rel)
        if not safe:
            return None
        try:
            path = os.path.join(self._music_dir(), safe)
            if not os.path.isfile(path):
                return None
            size = os.path.getsize(path)
            if size > 20 * 1024 * 1024:
                return None
            ext = os.path.splitext(safe)[1].lower()
            mime = AUDIO_MIME.get(ext, 'audio/mpeg')
            with open(path, 'rb') as f:
                import base64
                b64 = base64.b64encode(f.read()).decode('ascii')
            return {'mime': mime, 'b64': b64}
        except Exception:
            return None

    # ---- 窗口行为 -------------------------------------------------------
    def set_topmost(self, on):
        try:
            hwnd = self.hwnd()
            if not hwnd:
                return False
            flag = HWND_TOPMOST if on else HWND_NOTOPMOST
            user32.SetWindowPos(wintypes.HWND(hwnd), wintypes.HWND(flag),
                                0, 0, 0, 0, SWP_NOACTIVATE | 0x0001 | 0x0002)
            return True
        except Exception:
            return False

    def set_opacity(self, value):
        try:
            hwnd = self.hwnd()
            if not hwnd:
                return False
            try:
                v = float(value)
            except Exception:
                return False
            v = max(0.4, min(1.0, v))
            alpha = int(round(v * 255))
            ex = _GetWindowLong(wintypes.HWND(hwnd), GWL_EXSTYLE)
            if alpha >= 255:
                _SetWindowLong(wintypes.HWND(hwnd), GWL_EXSTYLE,
                               ctypes.c_void_p(int(ex) & ~WS_EX_LAYERED))
                user32.SetLayeredWindowAttributes(wintypes.HWND(hwnd), 0, 255, LWA_ALPHA)
            else:
                _SetWindowLong(wintypes.HWND(hwnd), GWL_EXSTYLE,
                               ctypes.c_void_p(int(ex) | WS_EX_LAYERED))
                user32.SetLayeredWindowAttributes(wintypes.HWND(hwnd), 0, alpha, LWA_ALPHA)
            return True
        except Exception:
            return False

    def minimize(self):
        try:
            hwnd = self.hwnd()
            if hwnd and not self._closing:
                user32.SendMessageW(wintypes.HWND(hwnd), WM_SYSCOMMAND, SC_MINIMIZE, 0)
            return True
        except Exception:
            return False

    def maximize(self):
        """最大化：优先走 UI 线程 WM_SYSCOMMAND(SC_MAXIMIZE)（真最大化，
        任务栏按钮/DPI 由 Windows 正确处理）。

        失效根因与修复：从“最小化/异常状态”出发直接发 SC_MAXIMIZE 时，
        WinForms 内部 WindowState 尚未同步为 Normal，会静默忽略该命令
        （表现为“点最大化没反应”）。故先 ShowWindow(SW_RESTORE) 拉回普通
        状态再发；若 SC_MAXIMIZE 仍 no-op（极少数异常状态），用 SetWindowPos
        铺满显示器工作区兜底（假最大化，靠 _maximized 自标记保持一致）。"""
        hwnd = self.hwnd()
        if not hwnd or self._closing:
            return False
        hw = wintypes.HWND(hwnd)
        try:
            if user32.IsIconic(hw):
                user32.ShowWindow(hw, SW_RESTORE)
                time.sleep(0.05)
        except Exception:
            pass
        # 记录最大化前几何（仅首次进入最大化时更新，保证还原回到原位）
        if not self._maximized:
            cur = self._rect(hw)
            if cur:
                self._restored = cur
        try:
            user32.SendMessageW(hw, WM_SYSCOMMAND, SC_MAXIMIZE, 0)
        except Exception:
            pass
        try:
            if not user32.IsZoomed(hw):
                # 真最大化未生效：兜底铺满显示器工作区
                mx, my, mw, mh = monitor_of(hwnd)
                user32.SetWindowPos(hw, 0, int(mx), int(my), int(mw), int(mh),
                                    SWP_NOZORDER | SWP_NOACTIVATE)
        except Exception:
            pass
        self._maximized = True
        return True

    def restore(self):
        """还原：真实最大化先由 UI 线程 SC_RESTORE 还原；最小化先 ShowWindow
        拉回；随后用记录的 _restored 几何（最大化前位置尺寸）精确归位，无记录
        时回退 lastSize。最终自标记 _maximized=False，保证与窗口实际一致。"""
        hwnd = self.hwnd()
        if not hwnd or self._closing:
            return False
        hw = wintypes.HWND(hwnd)
        try:
            if user32.IsZoomed(hw):
                user32.SendMessageW(hw, WM_SYSCOMMAND, SC_RESTORE, 0)
                time.sleep(0.05)
            elif user32.IsIconic(hw):
                user32.ShowWindow(hw, SW_RESTORE)
                time.sleep(0.05)
        except Exception:
            pass
        r = self._restored
        if r:
            try:
                user32.SetWindowPos(hw, 0, int(r[0]), int(r[1]),
                                    int(r[2]), int(r[3]),
                                    SWP_NOZORDER | SWP_NOACTIVATE)
            except Exception:
                pass
        else:
            size = self.config.get('lastSize') or {}
            w = int(size.get('w') or 420)
            h = int(size.get('h') or 700)
            try:
                self.resize_to(w, h, compact=False)
            except Exception:
                pass
        self._maximized = False
        return True

    def toggle_maximize(self):
        hwnd = self.hwnd()
        if not hwnd or self._closing:
            return False
        # 真实状态优先：已被系统最大化（任务栏/外部操作）→ 直接还原
        try:
            if user32.IsZoomed(wintypes.HWND(hwnd)):
                return self.restore()
        except Exception:
            pass
        if getattr(self, '_maximized', False):
            # 自标记最大化：可能是假最大化（铺满工作区）或任务栏还原后的残留
            # 标记，统一走还原路径，SetWindowPos 归位到 _restored 保证几何正确
            return self.restore()
        return self.maximize()

    def is_maximized(self):
        return bool(getattr(self, '_maximized', False))

    def _sync_max(self, hwnd):
        """以真实窗口状态（IsZoomed）为准，校正 _maximized 标记，避免与实际不一致。"""
        try:
            self._maximized = bool(user32.IsZoomed(wintypes.HWND(int(hwnd))))
        except Exception:
            pass

    # ---- 托盘 / 隐藏常驻 ----------------------------------------------------
    def poll_py_cmd(self):
        """前端轮询 Python 主动命令。托盘/看门狗等非 JS 线程不能直接
        evaluate_js（原生 SIGSEGV），统一由 Python 写入命令队列，前端
        定时 poll 取走执行（最小耦合、跨线程安全）。"""
        try:
            with self._py_lock:
                if not self._py_cmds:
                    return None
                cmds = self._py_cmds
                self._py_cmds = []
                return cmds
        except Exception:
            return None

    def _push_py_cmd(self, cmd):
        try:
            with self._py_lock:
                self._py_cmds.append(cmd)
                if len(self._py_cmds) > 8:   # 限长兜底：命令积压时丢最旧
                    self._py_cmds.pop(0)
        except Exception:
            pass

    def hide_to_tray(self):
        """关闭按钮 / 系统关闭（Alt+F4）→ 隐藏到系统托盘后台常驻。
        计时/音乐依赖前端定时器继续运行；即使 WebView 隐藏被节流，
        倒计时以 endTime 绝对时间恢复，显示后立即校准。返回 False 表示
        托盘库不可用（此时前端应退化为直接退出）。"""
        try:
            self._save_geom()
            self._flush_state_now()
        except Exception:
            pass
        if not _TRAY_OK:
            return False
        try:
            if self._window is not None:
                self._window.hide()
                self._tray_hidden = True
                _exit_log('HIDE_TO_TRAY')
                return True
        except Exception:
            pass
        return False

    def _show_from_tray(self):
        """托盘「打开 / 隐藏」→ 重新显示窗口。窗口隐藏/显示不改变几何，
        显示的是当前形态（完整窗或药丸，均由 DOM 状态决定）。"""
        try:
            self._tray_hidden = False
            if self._window is not None:
                self._window.show()
            return True
        except Exception:
            return False

    def _dock_after_drag(self, hwnd):
        """药丸拖拽松手后的边缘吸附：距工作区左/右/上边缘 <= DOCK_PX 则
        SetWindowPos 贴边并记录 S.ui.dockEdge；否则视为已拖离，清除 dockEdge
        （回到自由浮动）。非迷你态不吸附；pillDock=false（自由悬停）时跳过。
        仅供 drag(move) 结束时调用。"""
        if not self.config.get('compact'):
            return
        if not self.config.get('pillDock', True):
            # 用户关闭「边缘吸附」→ 自由悬停：停在哪就在哪，清除旧的 dockEdge
            if self.config.get('dockEdge'):
                self.config['dockEdge'] = None
                try:
                    write_json(CONFIG_PATH, self.config)
                except Exception:
                    pass
                self._push_py_cmd({'t': 'ui', 'ui': {'dockEdge': None}})
            return
        try:
            r = self._rect(hwnd)
            if not r:
                return
            mx, my, mw, mh = monitor_of(hwnd)
            x, y, w, h = r
            edge = None
            if x - mx <= DOCK_PX:
                edge = 'left'
            elif (mx + mw) - (x + w) <= DOCK_PX:
                edge = 'right'
            elif y - my <= DOCK_PX:
                edge = 'top'
            if edge:
                nx, ny = x, y
                if edge == 'left':
                    nx = mx
                elif edge == 'right':
                    nx = mx + mw - w
                else:
                    ny = my
                nx = max(mx, min(nx, mx + mw - w))
                ny = max(my, min(ny, my + mh - h))
                if (nx, ny) != (x, y):
                    user32.SetWindowPos(wintypes.HWND(hwnd), 0,
                                        int(nx), int(ny), 0, 0,
                                        SWP_NOZORDER | SWP_NOACTIVATE)
            self.config['dockEdge'] = edge
            try:
                write_json(CONFIG_PATH, self.config)
            except Exception:
                pass
            # 同步前端 S.ui.dockEdge（无 evaluate_js，走命令队列）
            self._push_py_cmd({'t': 'ui', 'ui': {'dockEdge': edge}})
        except Exception:
            pass

    def dock_pill(self, edge):
        """将迷你药丸吸附到指定屏幕边缘（left/right/top）。完整窗口或非法
        参数忽略。供前端进入迷你模式后恢复上次吸附边使用。"""
        if not self.config.get('compact'):
            return False
        try:
            hwnd = self.hwnd()
            if not hwnd:
                return False
            r = self._rect(hwnd)
            if not r:
                return False
            mx, my, mw, mh = monitor_of(hwnd)
            x, y, w, h = r
            if edge == 'left':
                x = mx
            elif edge == 'top':
                y = my
            else:
                x = mx + mw - w
            x = max(mx, min(x, mx + mw - w))
            y = max(my, min(y, my + mh - h))
            if (x, y) != (r[0], r[1]):
                user32.SetWindowPos(wintypes.HWND(hwnd), 0, int(x), int(y), 0, 0,
                                    SWP_NOZORDER | SWP_NOACTIVATE)
            edge = edge if edge in ('left', 'right', 'top') else None
            self.config['dockEdge'] = edge
            try:
                write_json(CONFIG_PATH, self.config)
            except Exception:
                pass
            self._push_py_cmd({'t': 'ui', 'ui': {'dockEdge': edge}})
            return True
        except Exception:
            return False

    def clear_logs(self):
        """清除 %APPDATA%\\FocusDeck\\logs 下的旧日志：递归 session-*.log 与
        crash.log / faulthandler.log。保留正在写入的当前会话日志（句柄占用
        无法删除时收集到 skipped）。返回 {'removed': [..], 'skipped': [..]}。"""
        removed, skipped = [], []
        cur = ''
        try:
            cur = os.path.abspath(_session_log_path())
        except Exception:
            pass
        try:
            root = _logs_dir()
            targets = []
            for dirpath, _dirs, files in os.walk(root):
                for fn in files:
                    base = fn.lower()
                    if base.startswith('session-') and base.endswith('.log'):
                        targets.append(os.path.join(dirpath, fn))
                    elif base in ('crash.log', 'faulthandler.log'):
                        targets.append(os.path.join(dirpath, fn))
            for p in targets:
                try:
                    if cur and os.path.abspath(p) == cur:
                        continue          # 当前会话正在写的日志：保留
                    os.remove(p)
                    removed.append(os.path.basename(p))
                except Exception:
                    skipped.append(os.path.basename(p))
        except Exception:
            pass
        return {'removed': removed, 'skipped': skipped}

    def quit(self):
        _exit_log('QUIT_CALLED')
        self._closing = True
        self._app_state = 'SHUTTING_DOWN'
        self._save_geom()
        self._flush_state_now()
        try:
            if os.path.exists(RUNNING_FLAG):
                os.remove(RUNNING_FLAG)
        except Exception:
            pass
        # 优先用 pywebview 官方 destroy()（线程安全地销毁窗口并退出），
        # 否则回退 PostMessage(WM_CLOSE)，最后兜底 os._exit。
        try:
            if self._window is not None:
                self._window.destroy()
                return True
        except Exception:
            pass
        hwnd = self.hwnd()
        if hwnd:
            user32.PostMessageW(wintypes.HWND(hwnd), WM_CLOSE, 0, 0)
        else:
            os._exit(0)
        return True

    def flash(self):
        try:
            hwnd = self.hwnd()
            if not hwnd:
                return False
            fi = FLASHWINFO()
            fi.cbSize = ctypes.sizeof(FLASHWINFO)
            fi.hwnd = wintypes.HWND(hwnd)
            fi.dwFlags = 0x00000003   # FLASHW_CAPTION | FLASHW_TRAY
            fi.uCount = 3
            fi.dwTimeout = 0
            user32.FlashWindowEx(ctypes.byref(fi))
            return True
        except Exception:
            return False

    # ---- 尺寸 -----------------------------------------------------------
    def _scale(self, hwnd):
        try:
            dpi = user32.GetDpiForWindow(wintypes.HWND(hwnd))
            return (dpi or 96) / 96.0
        except Exception:
            return 1.0

    def _rect(self, hwnd):
        r = wintypes.RECT()
        # hwnd 可能是 int 或 wintypes.HWND 实例，GetWindowRect 声明了 argtypes
        # 会自动转换，这里不再重复包装（重复包装 HWND(HWND) 会抛
        # “cannot be converted to pointer”）
        if not user32.GetWindowRect(hwnd, ctypes.byref(r)):
            return None
        return r.left, r.top, r.right - r.left, r.bottom - r.top

    def _cursor(self):
        p = wintypes.POINT()
        if not user32.GetCursorPos(ctypes.byref(p)):
            return None
        return p.x, p.y

    def _geom(self):
        hwnd = self.hwnd()
        if not hwnd:
            return None
        r = self._rect(hwnd)
        if not r:
            return None
        s = self._scale(hwnd)
        return {'x': int(round(r[0] / s)), 'y': int(round(r[1] / s)),
                'w': int(round(r[2] / s)), 'h': int(round(r[3] / s))}

    def _save_geom(self):
        g = self._geom()
        if not g:
            return
        self.config['geom'] = g
        if self.config.get('compact') and (g['w'] > 300 or g['h'] > 180):
            self.config['compact'] = False
        if not self.config.get('compact'):
            self.config['lastSize'] = {'w': g['w'], 'h': g['h']}
        write_json(CONFIG_PATH, self.config)

    def resize_to(self, w, h, compact=False):
        hwnd = self.hwnd()
        if not hwnd:
            return False
        # 必须在保存几何前同步 compact 状态，否则进入迷你模式时 _save_geom 仍按
        # “非 compact” 处理，会把 250x112 误写进 lastSize，导致退出迷你后窗口卡在小尺寸。
        self.config['compact'] = bool(compact)
        s = self._scale(hwnd)
        if compact:
            # 迷你条模式：固定 COMPACT 尺寸，不受手动缩放 MIN 限制（见 MIN_W 注释）
            pw = int(round(max(COMPACT_W, w) * s))
            ph = int(round(max(COMPACT_H, h) * s))
        else:
            pw = max(int(MIN_W * s), int(round(w * s)))
            ph = max(int(MIN_H * s), int(round(h * s)))
        rect = self._rect(hwnd) or (0, 0, pw, ph)
        x, y = rect[0], rect[1]
        mx, my, mw, mh = monitor_of(hwnd)
        pw = min(pw, mw)
        ph = min(ph, mh)
        # 保持窗口完整落在当前显示器内
        x = max(mx, min(x, mx + mw - pw))
        y = max(my, min(y, my + mh - ph))
        user32.SetWindowPos(wintypes.HWND(hwnd), 0, int(x), int(y), pw, ph,
                            SWP_NOZORDER | SWP_NOACTIVATE)
        # 显式设置普通几何（预设尺寸/恢复尺寸/退出迷你）即退出最大化状态，
        # 避免 _maximized 残留导致后续点“还原”把窗口拉回旧位置
        self._maximized = False
        time.sleep(0.05)
        if not compact:
            self.config['lastSize'] = {'w': int(round(pw / s)), 'h': int(round(ph / s))}
        self._save_geom()
        return True

    def restore_size(self):
        hwnd = self.hwnd()
        if not hwnd:
            return False
        size = self.config.get('lastSize') or {}
        w = int(size.get('w') or 420)
        h = int(size.get('h') or 700)
        return self.resize_to(w, h, compact=False)

    # ---- 窗口拖拽 / 缩放 -------------------------------------------------
    # 8 方向缩放对应 grip 的手动缩放模式（见交接说明「别再试」：frameless 窗口
    # 无 WS_THICKFRAME，WM_NCLBUTTONDOWN(HTxxx) 对无边框窗口 no-op；临时注入
    # WS_THICKFRAME 又会让 WinForms 重排 + 客户区缩偏移 7px，不可用）。
    # 因此缩放手动用 SetWindowPos 显式驱动：grip down → api('drag', mode) →
    # 本线程以光标增量计算新几何并逐帧 SetWindowPos，直到左键松开（全局按键
    # 状态判定，鼠标移出窗口也跟手）。与最大化修复同一范式：不依赖系统消息，
    # 全部显式几何，杜绝「缩放没反应」。
    def drag(self, mode):
        """mode: move | n | s | e | w | nw | ne | sw | se。

        全部统一走 SetWindowPos 显式轮询循环（DRAG_POLL 采样光标增量）：
        对 frameless 窗口最可靠，不依赖 HTCAPTION / 系统 NC 拖动（那些路径
        在无边框样式下经常 no-op）。move 移动整窗；缩放按方向改四边几何；
        松开左键结束，ESC 还原起点几何。
        """
        if self._closing:
            return False
        mode = str(mode)
        resize_modes = {'n', 's', 'e', 'w', 'nw', 'ne', 'sw', 'se'}
        is_move = mode not in resize_modes
        # ---- 移动 / 缩放：SetWindowPos 手动驱动 ----
        hwnd = self.hwnd()
        if not hwnd:
            return False
        hw = wintypes.HWND(hwnd)
        try:
            # 最小化/最大化先还原到普通态，再以还原后的几何为拖动起点
            if user32.IsIconic(hw):
                user32.ShowWindow(hw, SW_RESTORE)
                time.sleep(0.05)
            if user32.IsZoomed(hw) or self._maximized:
                self.restore()
                time.sleep(0.1)
        except Exception:
            pass
        start = self._rect(hw)
        if not start:
            return False
        x, y, w, h = start
        cur0 = self._cursor()
        if not cur0:
            return False
        ox, oy = cur0
        s = self._scale(hw)
        min_w = int(MIN_W * s)
        min_h = int(MIN_H * s)
        mx, my, mw, mh = monitor_of(hwnd)
        try:
            user32.ReleaseCapture()
            deadline = time.time() + 120.0
            while not self._closing and time.time() < deadline:
                # 左键松开即结束；ESC 取消并还原起点几何
                if not (user32.GetAsyncKeyState(VK_LBUTTON) & 0x8000):
                    break
                if user32.GetAsyncKeyState(VK_ESCAPE) & 0x8000:
                    user32.SetWindowPos(hw, 0, int(x), int(y), int(w), int(h),
                                        SWP_NOZORDER | SWP_NOACTIVATE)
                    self._save_geom()
                    return True
                cur = self._cursor()
                if not cur:
                    time.sleep(DRAG_POLL)
                    continue
                dx, dy = cur[0] - ox, cur[1] - oy
                if is_move:
                    if self.config.get('compact'):
                        # 药丸模式：整体限制在工作区内（可贴到任意边缘触发吸附）。
                        # 普通大窗允许少量出屏（保留 100px 可抓取），药丸若沿用
                        # 该规则会卡在“距右缘 20px”而永远触不到右吸附条件。
                        L = max(mx, min(x + dx, mx + mw - w))
                        T = max(my, min(y + dy, my + mh - h))
                    else:
                        # 移动：整窗平移，保持尺寸；clamp 至少 100px 留在工作区内
                        L = x + dx
                        T = y + dy
                        L = max(mx - w + 100, min(L, mx + mw - 100))
                        T = max(my, min(T, my + mh - 100))
                    nw2, nh2 = w, h
                else:
                    # 由拖拽方向推出四边（单位：物理像素，光标增量天然物理像素）
                    L = x + (dx if 'w' in mode else 0)
                    T = y + (dy if 'n' in mode else 0)
                    R = x + w + (dx if 'e' in mode else 0)
                    B = y + h + (dy if 's' in mode else 0)
                    # 最小尺寸：回拉拖拽边，保证对侧边不动
                    if R - L < min_w:
                        if 'w' in mode and 'e' not in mode:
                            L = R - min_w
                        else:
                            R = L + min_w
                    if B - T < min_h:
                        if 'n' in mode and 's' not in mode:
                            T = B - min_h
                        else:
                            B = T + min_h
                    # 屏幕边界：拖拽边不越过工作区（对侧边因最小尺寸 clamp 不会越界）
                    if 'e' in mode and R > mx + mw:
                        R = mx + mw
                    if 's' in mode and B > my + mh:
                        B = my + mh
                    if 'w' in mode and L < mx:
                        L = mx
                    if 'n' in mode and T < my:
                        T = my
                    nw2, nh2 = R - L, B - T
                if nw2 >= min_w and nh2 >= min_h:
                    user32.SetWindowPos(hw, 0, int(L), int(T), int(nw2), int(nh2),
                                        SWP_NOZORDER | SWP_NOACTIVATE)
                time.sleep(DRAG_POLL)
        except Exception:
            pass
        self._sync_max(hw)
        if is_move:
            # 药丸拖拽收尾：边缘吸附 / 拖离取消吸附（仅 move；缩放后不吸附）
            self._dock_after_drag(hwnd)
        self._save_geom()
        return True

    # ---- 文件 -----------------------------------------------------------
    def export_file(self, filename, content):
        try:
            import webview
            res = self._window.create_file_dialog(
                webview.SAVE_DIALOG,
                directory=os.path.join(os.path.expanduser('~'), 'Desktop'),
                save_filename=filename,
                file_types=('JSON 文件 (*.json)', '*.json'),
            )
        except Exception:
            res = None
        path = res[0] if isinstance(res, (list, tuple)) and res else (res if isinstance(res, str) else None)
        if not path:
            return None
        try:
            if not path.lower().endswith('.json'):
                path += '.json'
            with open(path, 'w', encoding='utf-8') as f:
                f.write(content)
            return path
        except Exception:
            return None

    def import_file(self):
        try:
            import webview
            res = self._window.create_file_dialog(
                webview.OPEN_DIALOG,
                directory=os.path.join(os.path.expanduser('~'), 'Desktop'),
                file_types=('JSON 文件 (*.json)', '*.json'),
            )
        except Exception:
            res = None
        paths = res if isinstance(res, (list, tuple)) else ([res] if res else [])
        if not paths:
            return None
        try:
            with open(paths[0], 'r', encoding='utf-8') as f:
                return f.read()
        except Exception:
            return None

    # ---- 开机自启动 -----------------------------------------------------
    def get_autostart(self):
        """读取 HKCU\\...\\Run\\FocusDeck 是否存在（即是否已设为开机自启动）。"""
        try:
            key = winreg.OpenKey(
                winreg.HKEY_CURRENT_USER,
                r'Software\Microsoft\Windows\CurrentVersion\Run',
            )
            try:
                winreg.QueryValueEx(key, APP_NAME)
                return True
            except FileNotFoundError:
                return False
            finally:
                winreg.CloseKey(key)
        except Exception:
            return False

    def set_autostart(self, on):
        """写入/删除开机自启动注册表项。on=True 时以最小化方式启动，不打扰用户。"""
        try:
            exe = sys.executable
            if not exe or not os.path.isfile(exe):
                return False
            key = winreg.OpenKey(
                winreg.HKEY_CURRENT_USER,
                r'Software\Microsoft\Windows\CurrentVersion\Run',
                0,
                winreg.KEY_SET_VALUE,
            )
            try:
                if on:
                    val = '"%s" --min' % exe
                    winreg.SetValueEx(key, APP_NAME, 0, winreg.REG_SZ, val)
                else:
                    try:
                        winreg.DeleteValue(key, APP_NAME)
                    except FileNotFoundError:
                        pass
            finally:
                winreg.CloseKey(key)
            ok = True
        except Exception:
            ok = False
        return ok

    # ---- 系统通知（真实 Windows Toast，免第三方库）------------------------
    _AUMID = 'FocusDeck.Pro'
    _notify_script = None

    def _ensure_aumid(self):
        """为未打包的 Win32 程序注册 AppUserModelID，否则 WinRT Toast 会被系统静默丢弃。"""
        try:
            key = winreg.CreateKey(
                winreg.HKEY_CURRENT_USER,
                r'Software\Classes\AppUserModelID' + '\\' + self._AUMID,
            )
            try:
                winreg.SetValueEx(key, 'DisplayName', 0, winreg.REG_SZ, APP_NAME)
            finally:
                winreg.CloseKey(key)
        except Exception:
            pass

    def _ensure_notify_script(self):
        if self._notify_script and os.path.isfile(self._notify_script):
            return self._notify_script
        path = os.path.join(data_dir(), 'notify.ps1')
        if not os.path.isfile(path):
            try:
                with open(path, 'w', encoding='utf-8') as f:
                    f.write(
                        "param([string]$Title='FocusDeck',[string]$Body='')\n"
                        "$ErrorActionPreference='SilentlyContinue'\n"
                        "$null=[Windows.UI.Notifications.ToastNotificationManager,Windows.UI.Notifications,ContentType=WindowsRuntime]\n"
                        "$tn=[Windows.UI.Notifications.ToastNotificationManager]::CreateToastNotifier('" + self._AUMID + "')\n"
                        "$x=New-Object Windows.Data.Xml.Dom.XmlDocument\n"
                        "$t=[System.Security.SecurityElement]::Escape($Title)\n"
                        "$b=[System.Security.SecurityElement]::Escape($Body)\n"
                        "$x.LoadXml(\"<toast><visual><binding template='ToastGeneric'><text>$t</text><text>$b</text></binding></visual></toast>\")\n"
                        "$tn.Show($x)\n"
                    )
            except Exception:
                return None
        self._notify_script = path
        return path

    def notify(self, title, body=''):
        """弹出真实 Windows 通知（Toast）。桌面版专用，后台进程调用，不阻塞 UI。"""
        try:
            self._ensure_aumid()
            ps = self._ensure_notify_script()
            if not ps:
                return False
            subprocess.Popen(
                ['powershell.exe', '-NoProfile', '-NonInteractive',
                 '-WindowStyle', 'Hidden', '-File', ps,
                 '-Title', str(title or APP_NAME), '-Body', str(body or '')],
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            )
            return True
        except Exception:
            return False

    # ---- 崩溃取证（渲染进程崩溃不会走 Python 异常，需主动探测）--------
    def heartbeat(self):
        """前端每 3 秒心跳一次；看门狗据此判断渲染进程是否还活着。"""
        self._last_beat = time.time()
        return True

    def js_error(self, msg):
        """JS 端未捕获异常 / Promise 拒绝 → 写进 crash.log。"""
        try:
            _log_crash(RuntimeError, 'JS_ERROR: ' + str(msg), None)
        except Exception:
            pass
        return True

    def page_gone(self):
        """页面卸载。若正处于关闭流程则忽略（避免误判为崩溃）。"""
        if getattr(self, '_closing', False):
            return True
        try:
            _log_crash(RuntimeError, 'PAGE_UNLOADED(渲染进程疑似崩溃/关闭)', None)
        except Exception:
            pass
        return True

    def on_ready(self):
        """前端就绪回调：由 JS 在 API 可用后调用（比 pywebview 的 loaded 事件更可靠——
        用户机器上 loaded 事件未触发，导致 Python 侧就绪逻辑不执行）。
        负责：标记 READY（看门狗据此判定渲染进程存活）、按渲染模式设置前端轻量模式。"""
        try:
            self._app_state = 'READY'
        except Exception:
            pass
        log_stage('READY')
        # 轻量模式由前端 HTML 默认 data-lite="1" 保证（软件渲染下关掉持续重绘，
        # 防卡顿/防崩）。此处不再用 evaluate_js 设置，避免 API 线程内直接调用
        # WebView2 触发原生崩溃——正是此前“启动黑屏后闪退、且 crash.log 无记录”
        # 的疑似诱因。GPU 模式(opt-in)如需恢复特效，由前端自行读取本返回值移除
        # data-lite（见 index.html 的 bindDesktop on_ready 处理），不走 Python evaluate_js。
        try:
            return 'gpu' if _CURRENT_RENDER_MODE == 'gpu' else 'sw'
        except Exception:
            return 'sw'

    def reset_render(self):
        """手动重置渲染模式：清除软件渲染 flag，写入 gpu.optin，下次启动尝试 GPU。

        仅在用户主动点「设置→重置为 GPU」时调用；若 GPU 再次崩溃，看门狗/
        running.flag 会把 swrender.flag 写回，自动切回软件渲染（不会反复崩）。
        """
        try:
            if os.path.exists(SWRENDER_FLAG):
                os.remove(SWRENDER_FLAG)
            try:
                if os.path.exists(render_state_path()):
                    os.remove(render_state_path())
            except Exception:
                pass
            with open(GPU_OPTIN, 'w', encoding='utf-8') as f:
                f.write(time.strftime('%Y-%m-%d %H:%M:%S') + ' 用户主动开启 GPU\n')
            log('reset_render: 已清除软件渲染标记并写入 gpu.optin，下次启动尝试 GPU')
            return True
        except Exception:
            return False


# ----------------------------------------------------------------------------
# 启动
# ----------------------------------------------------------------------------
def build_config():
    cfg = read_json(CONFIG_PATH, {})
    cfg.setdefault('topmost', True)
    cfg['opacity'] = 1.0   # 稳定性：强制不透明，不挂 WS_EX_LAYERED（分层窗口易致 WebView2 崩溃）
    cfg.setdefault('zoom', 1.0)
    cfg.setdefault('compact', False)
    g = cfg.get('geom') or {}
    w = int(g.get('w') or 420)
    h = int(g.get('h') or 700)
    x = g.get('x')
    y = g.get('y')
    # 防呆：非迷你模式下几何尺寸小于 MIN（标题栏/主面板会被挤压错位、按钮
    # 不可见不可点，用户会误以为“坏了/找不到取消键”）→ 用默认完整面板尺寸。
    if not cfg.get('compact') and (w < MIN_W or h < MIN_H):
        log('geom too small (w=%s h=%s compact=%s) -> reset default' % (w, h, cfg.get('compact')))
        w, h = 520, 760
        cfg['geom'] = {'w': w, 'h': h}
        cfg['lastSize'] = {'w': w, 'h': h}
        try:
            write_json(CONFIG_PATH, cfg)
        except Exception:
            pass
    if x is None or y is None or not is_on_screen(int(x), int(y), w, h):
        x = y = None
    return cfg, w, h, x, y


def main():
    log_stage('START')
    log(_sysinfo())
    # 原生崩溃取证：SIGSEGV/SIGABRT/SIGFPE 等会写 Python 调用栈 + C 栈到文件，
    # 下次真机闪退即可定位确切代码行（普通 Python 异常已走 sys.excepthook）。
    try:
        _fh = open(os.path.join(data_dir(), 'faulthandler.log'), 'wb')
        faulthandler.enable(file=_fh, all_threads=True)
    except Exception:
        try:
            faulthandler.enable(all_threads=True)
        except Exception:
            pass
    # --- 单实例互斥：避免多开争用同一 WebView2 user-data-dir ---
    try:
        _mtx = kernel32.CreateMutexW(None, False, 'FocusDeck_Pro_SingleInstance')
        if kernel32.GetLastError() == 183:  # ERROR_ALREADY_EXISTS
            log('已有实例在运行，本次退出（单实例互斥）')
            _fatal('FocusDeck 已在运行', 'FocusDeck 已经在运行中。\n如需重新打开，请先关闭现有窗口。')
            return
    except Exception:
        pass

    # --- 渲染模式：恒定软件渲染（稳定性优先） ---
    # 实测本机 WebView2 GPU 合成会触发 C 层崩溃：无 Python 异常、无转储，
    # 表现为启动后 13s~20 分钟窗口无痕退出或卡死（含仅禁用光栅化的组合，
    # 多轮复现已证实：GPU 合成器在本机 WebView2 上不可用）。
    # 因此不再提供 gpu.optin 分支——所有档位一律软件合成（--disable-gpu
    # 家族），视觉特效由前端 data-lite 分级控制：软合成可承载跟手光晕
    # （仅鼠标移动时短暂 rAF），持续动画（律动/呼吸/波纹）保持关闭。
    _prev_crashed = os.path.exists(RUNNING_FLAG)
    try:
        if _prev_crashed:
            os.remove(RUNNING_FLAG)   # 旧的运行标记先清掉，稍后本进程会重新创建
    except Exception:
        pass

    _FORCE_SW = True

    if _prev_crashed and not os.path.exists(SWRENDER_FLAG):
        # 上次运行没有干净退出（崩溃/被杀）→ 记录痕迹（供诊断），
        # 渲染档位本身已恒定软件，无需切换。
        try:
            with open(SWRENDER_FLAG, 'w', encoding='utf-8') as f:
                f.write(time.strftime('%Y-%m-%d %H:%M:%S')
                        + ' 上次运行非正常退出（记录痕迹）\n')
        except Exception:
            pass

    # 浏览器附加参数：软合成档完全禁用 WebView2 GPU（本机 GPU 合成必崩），
    # 同时无条件禁用后台定时器节流（窗口被隐藏/最小化/遮挡时 Chromium 会把
    # setInterval 压到约 1 次/分钟，导致前端 3s 心跳中断、看门狗误判渲染进程
    # 崩溃而销毁窗口——正是"窗口无痕退出"的诱因之一）。
    _wv_args = [
        '--disable-gpu', '--disable-gpu-compositing', '--disable-gpu-rasterization',
        '--disable-background-timer-throttling',
        '--disable-backgrounding-occluded-windows',
        '--disable-renderer-backgrounding',
        '--remote-debugging-port=9333',
    ]
    os.environ['WEBVIEW2_ADDITIONAL_BROWSER_ARGUMENTS'] = ' '.join(_wv_args)
    global _CURRENT_RENDER_MODE
    _CURRENT_RENDER_MODE = 'sw'
    log('render_mode=SOFTWARE (gpu-compositing disabled; prev_crashed=%s)'
        % _prev_crashed)

    try:
        import webview
    except Exception as e:
        _log_crash(type(e), e, e.__traceback__)
        _fatal('FocusDeck 无法启动', '内部模块加载失败（webview）：\n%s' % e)
        return
    log_stage('INIT_RUNTIME')
    log('webview imported; WebView2 runtime=%s' % (webview2_runtime_version() or 'MISSING'))

    # WebView2 运行时缺失 → 友好提示（避免“双击无界面/秒退”且无任何说明）
    if webview2_runtime_version() is None:
        _fatal(
            'FocusDeck 无法启动',
            '未检测到 Microsoft Edge WebView2 运行时。\n'
            'FocusDeck 依赖该组件才能显示界面，请先安装：\n'
            'https://go.microsoft.com/fwlink/p/?LinkId=2124703\n\n'
            '（安装完成后重新双击 FocusDeck.exe 即可）',
        )
        return

    start_minimized = '--min' in sys.argv
    try:
        log_stage('INIT_CONFIG')
        cfg, w, h, x, y = build_config()
    except Exception as e:
        _log_crash(type(e), e, e.__traceback__)
        cfg = {'topmost': True, 'opacity': 1.0, 'zoom': 1.0, 'compact': False}
        w, h, x, y = 420, 700, None, None
    api = Api(cfg)

    html_path = resource('index.html')
    if not os.path.isfile(html_path):
        _fatal('FocusDeck 无法启动', '找不到界面文件 index.html：\n%s' % html_path)
        return

    log_stage('CREATE_WINDOW')
    window = webview.create_window(
        title='FocusDeck Pro',
        url=html_path,
        js_api=api,
        width=w,
        height=h,
        x=(int(x) if x is not None else None),
        y=(int(y) if y is not None else None),
        resizable=True,
        frameless=True,
        easy_drag=False,          # 使用自定义 Win32 拖拽，避免与把手冲突
        shadow=True,
        on_top=bool(cfg.get('topmost', True)),
        min_size=(MIN_W, MIN_H),
        background_color='#0B0D14',
        text_select=True,
        confirm_close=False,
    )
    api._window = window

    # 运行标记：本进程正活运行中；干净退出（atexit / quit）时删除。
    # 下次启动若仍存在 → 上次非正常退出（崩/被杀）→ 强制软件渲染（见上方逻辑）。
    try:
        with open(RUNNING_FLAG, 'w', encoding='utf-8') as f:
            f.write('%s %s' % (os.getpid(), time.strftime('%Y-%m-%d %H:%M:%S')))
    except Exception:
        pass

    def _clear_running():
        try:
            _exit_log('EXIT(atexit)')
            if os.path.exists(RUNNING_FLAG):
                os.remove(RUNNING_FLAG)
        except Exception:
            pass

    atexit.register(_clear_running)

    # 看门狗：若前端心跳停止 >12 秒，说明渲染进程已崩溃（白屏/闪退）。
    # 自动写入 swrender.flag，下次启动即切换为软件渲染（不再反复崩）；
    # 并主动销毁窗口让进程干净退出，避免用户面对一个白屏卡死的窗体。
    # 看门狗线程上次醒来的系统 tick（秒）。time.sleep(3) 在系统休眠/睡眠期间
    # 同样会被挂起，恢复后 GetTickCount64 会出现远超 3s 的跳变——据此识别
    # “是系统休眠导致心跳暂停”，而不是渲染进程崩溃，避免合盖/睡眠回来窗口被误销毁。
    _wd_tick_prev = [0.0]

    def _watchdog():
        while True:
            time.sleep(3)
            try:
                # 关闭中：直接退出看门狗，绝不再触碰窗口
                if getattr(api, '_closing', False):
                    break
                # 本线程刚被系统休眠/深度睡眠挂起过：恢复后给前端一个心跳窗口，
                # 本轮跳过判定并重置心跳基线，避免把“休眠暂停”误判为“渲染进程崩溃”。
                try:
                    now_tick = kernel32.GetTickCount64() / 1000.0
                    if _wd_tick_prev[0] and (now_tick - _wd_tick_prev[0]) > 10:
                        api._last_beat = time.time()
                        _wd_tick_prev[0] = now_tick
                        continue
                    _wd_tick_prev[0] = now_tick
                except Exception:
                    pass
                # 仅当应用已进入 READY 才开始判定；启动/加载阶段不误杀，
                # 也避免休眠/后台节流时心跳暂停被误判为“渲染进程崩溃”。
                if getattr(api, '_app_state', '') != 'READY':
                    continue
                # 已隐藏到托盘（用户主动最小化到托盘）：窗口不可见时 WebView
                # 可能被系统级暂停渲染，心跳不能作为“渲染进程崩溃”依据。
                if getattr(api, '_tray_hidden', False):
                    continue
                last = getattr(api, '_last_beat', 0)
                if last and (time.time() - last) > 20:
                    _log_crash(
                        RuntimeError,
                        'RENDERER_UNRESPONSIVE: 前端心跳停止 >20s，渲染进程疑似崩溃(白屏/闪退)',
                        None,
                    )
                    try:
                        with open(SWRENDER_FLAG, 'w', encoding='utf-8') as f:
                            f.write(time.strftime('%Y-%m-%d %H:%M:%S')
                                    + ' 自动切换为软件渲染（GPU 渲染进程崩溃）\n')
                        # 同时撤销用户对 GPU 的主动开启，避免下次又回到 GPU 崩
                        if os.path.exists(GPU_OPTIN):
                            os.remove(GPU_OPTIN)
                    except Exception:
                        pass
                    try:
                        if not api._closing:
                            api._window.destroy()
                    except Exception:
                        pass
                    _exit_log('WATCHDOG_DESTROY')
                    break
            except Exception:
                pass

    threading.Thread(target=_watchdog, daemon=True).start()

    # 恢复线程：连续 3 次 GPU 会话都健康（启动 25s 内心跳正常）→ 自动清除
    # swrender.flag，回到 GPU 渲染。避免「崩过一次就永远卡在软件渲染」。
    def _recovery():
        time.sleep(25)
        try:
            last = getattr(api, '_last_beat', 0)
            if last and (time.time() - last) < 20:
                st = read_json(render_state_path(), {'gpu_ok': 0})
                st['gpu_ok'] = int(st.get('gpu_ok', 0)) + 1
                if st['gpu_ok'] >= 3 and os.path.exists(SWRENDER_FLAG):
                    if os.path.exists(GPU_OPTIN):
                        # 用户主动开启 GPU 且连续 3 次会话健康 → 清除软件渲染标记，保留 GPU
                        try:
                            os.remove(SWRENDER_FLAG)
                        except Exception:
                            pass
                        log('auto-recovered: 连续 %d 次 GPU 会话健康，已清除 swrender.flag' % st['gpu_ok'])
                        st['gpu_ok'] = 0
                    else:
                        # 用户未开启 GPU：保持软件渲染（稳定优先），重置计数避免无谓写盘
                        st['gpu_ok'] = 0
                write_json(render_state_path(), st)
        except Exception:
            pass

    threading.Thread(target=_recovery, daemon=True).start()

    def on_loaded():
        # 主就绪逻辑统一放到 on_ready（由前端 whenApiReady 触发，比 pywebview
        # loaded 事件更可靠——用户机器上 loaded 未触发，导致就绪逻辑不执行）。
        try:
            api.on_ready()
        except Exception:
            pass
        try:
            if float(cfg.get('opacity', 1.0)) < 1.0:
                api.set_opacity(float(cfg['opacity']))
        except Exception:
            pass
        if start_minimized:
            try:
                api.minimize()
            except Exception:
                pass

    window.events.loaded += on_loaded

    def _on_closing():
        # 关闭事件（标题栏关闭已改走前端 hide_to_tray；此处兜底系统关闭路径
        # Alt+F4 / 任务栏关闭等）：默认不退出进程，改为隐藏到系统托盘后台常驻。
        # 返回 False → pywebview 取消本次关闭。真正退出走托盘菜单 quit()，
        # 其先置 _closing=True，此处放行（return None → 继续关闭流程）。
        _exit_log('PY_CLOSING_EVENT')
        if getattr(api, '_closing', False):
            return
        try:
            api.hide_to_tray()
        except Exception:
            pass
        return False
    window.events.closing += _on_closing

    # --- 系统托盘（pystray）：大窗口关闭后隐藏到托盘后台常驻 ---
    # 托盘图标线程独立于 pywebview UI 线程运行。所有回调仅做三类事：
    #   1) window.hide()/show()（pywebview 线程安全，内部封送 UI 线程）
    #   2) api._push_py_cmd() 下发命令，由前端 poll_py_cmd 轮询执行
    #   3) api.quit() 真正退出
    # 严禁在回调内 evaluate_js（原生 SIGSEGV，铁律 8）。
    global _TRAY_ICON
    if _TRAY_OK:
        try:
            icon_path = resource('icon.ico')
            _tray_img = None
            if os.path.isfile(icon_path):
                try:
                    _tray_img = Image.open(icon_path)
                except Exception:
                    _tray_img = None
            if _tray_img is None:
                # 兜底：无 icon.ico 时生成 64x64 深色占位图标，避免托盘空白
                _tray_img = Image.new('RGBA', (64, 64), (11, 13, 20, 255))

            def _tray_toggle_visible(icon=None, item=None):
                # 「打开 / 隐藏」（双击托盘图标默认触发）：切换窗口显示状态
                try:
                    if getattr(api, '_tray_hidden', False):
                        api._show_from_tray()
                    else:
                        api.hide_to_tray()
                except Exception:
                    pass

            def _tray_toggle_mini(icon=None, item=None):
                # 「迷你模式」：若窗口已隐藏先显示，再让前端切换药丸态
                try:
                    if getattr(api, '_tray_hidden', False):
                        api._show_from_tray()
                        time.sleep(0.8)   # 给前端足够的命令处理窗口
                    api._push_py_cmd({'t': 'compact', 'v': not bool(api.config.get('compact'))})
                except Exception:
                    pass

            def _tray_quit(icon=None, item=None):
                # 「退出」：停掉托盘图标 → 走 quit() 真正退出进程
                try:
                    if icon is not None:
                        icon.stop()
                except Exception:
                    pass
                try:
                    api.quit()
                except Exception:
                    pass
                # 兜底：quit() destroy 失败时也确保进程结束（先给 destroy 机会）
                def _force_exit():
                    time.sleep(2)
                    os._exit(0)
                threading.Thread(target=_force_exit, daemon=True).start()

            _menu = pystray.Menu(
                pystray.MenuItem('打开 / 隐藏', _tray_toggle_visible, default=True),
                pystray.MenuItem('迷你模式', _tray_toggle_mini),
                pystray.Menu.SEPARATOR,
                pystray.MenuItem('退出 FocusDeck', _tray_quit),
            )
            _TRAY_ICON = pystray.Icon('FocusDeckPro', _tray_img, 'FocusDeck Pro', _menu)

            def _run_tray():
                try:
                    _TRAY_ICON.run()
                except Exception as e:
                    _exit_log('TRAY_RUN_FAIL: %r' % (e,))
            threading.Thread(target=_run_tray, daemon=True).start()
            log('tray icon started (pystray)')
        except Exception as e:
            _exit_log('TRAY_START_FAIL: %r' % (e,))

    # --- 本地 http 服务端口：必须随机唯一 ---
    # pywebview 在 private_mode=False 时默认用固定端口 42001，且 Windows 允许
    # 多个进程 SO_REUSEADDR 共享绑定同一端口。若机器上残留其它 pywebview 进程
    # （旧版 FocusDeck/僵尸实例/本机其它 pywebview 应用）也占着 42001，本实例
    # 页面的 http 请求会被系统分发到别的进程 → 返回 404 → 页面白屏无 READY，
    # 表现为“启动后卡死、什么都点不了”。修复：每次启动自选一个空闲端口。
    def _pick_http_port():
        import random as _random
        import socket as _socket
        for _ in range(200):
            _p = _random.randint(20000, 60000)
            _s = _socket.socket(_socket.AF_INET, _socket.SOCK_STREAM)
            try:
                _s.bind(('127.0.0.1', _p))
                _s.close()
                return _p
            except OSError:
                try:
                    _s.close()
                except Exception:
                    pass
        return 0
    _http_port = _pick_http_port()
    log('http_port=%d (unique per instance, avoid 42001 collision)' % _http_port)

    icon = resource('icon.ico')
    log_stage('LOAD_UI')
    try:
        webview.start(
            func=None,
            private_mode=False,
            storage_path=os.path.join(data_dir(), 'webview2'),
            icon=icon if os.path.isfile(icon) else None,
            debug=False,
            http_server=True,      # 本地 http 服务，避免 file:// 下的能力限制
            http_port=_http_port,  # 随机空闲端口，防止与其它进程共享 42001 导致 404 白屏
        )
    except Exception as e:
        # 渲染进程启动失败（最常见：WebView2 运行时异常 / GPU 初始化崩溃）
        em = str(e)
        _log_crash(type(e), e, e.__traceback__)
        log('webview.start failed: %s' % em)
        if 'webview2' in em.lower() or 'runtime' in em.lower():
            _fatal('FocusDeck 启动失败',
                   'WebView2 渲染组件初始化失败：\n%s\n\n请确认已安装 Edge WebView2 运行时：\n'
                   'https://go.microsoft.com/fwlink/p/?LinkId=2124703' % em)
        else:
            _fatal('FocusDeck 启动失败', '渲染进程初始化失败：\n%s' % em)
        return

    # 退出前最后保存一次几何信息
    try:
        api._save_geom()
    except Exception:
        pass
    log('webview.start returned; process exiting normally')
    _exit_log('START_RETURNED')


if __name__ == '__main__':
    main()