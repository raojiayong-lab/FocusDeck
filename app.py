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

import ctypes
import json
import os
import sys
import threading
import time
import winreg
from ctypes import wintypes

# 默认启用 GPU 合成/光栅化（普通桌面环境），以获得流畅高帧率：
# 在 120Hz / 144Hz 显示器上可跑满原生刷新率（动画走 requestAnimationFrame + GPU transform）。
# 仅当确遇远程桌面 / 无 GPU 黑屏时，才改为下行注释的形式强制软件渲染。
# os.environ['WEBVIEW2_ADDITIONAL_BROWSER_ARGUMENTS'] = '--disable-gpu --disable-gpu-compositing'
os.environ.setdefault('WEBVIEW2_ADDITIONAL_BROWSER_ARGUMENTS', '')

# ----------------------------------------------------------------------------
# 常量
# ----------------------------------------------------------------------------
APP_NAME = 'FocusDeck'
MIN_W, MIN_H = 240, 96
COMPACT_W, COMPACT_H = 250, 112
DRAG_POLL = 0.008

WM_CLOSE = 0x0010
WM_NCLBUTTONDOWN = 0x00A1
VK_LBUTTON = 0x01
VK_ESCAPE = 0x1B
SW_MINIMIZE = 6
SWP_NOZORDER = 0x0004
SWP_NOACTIVATE = 0x0010
HWND_TOPMOST = -1
HWND_NOTOPMOST = -2
MONITOR_DEFAULTTONEAREST = 2
GWL_EXSTYLE = -20
WS_EX_LAYERED = 0x00080000
LWA_ALPHA = 0x00000002

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
    user32.SetWindowLongPtrW.argtypes = [wintypes.HWND, ctypes.c_int, ctypes.c_void_p]
    _SetWindowLong = user32.SetWindowLongPtrW
    user32.GetWindowLongPtrW.argtypes = [wintypes.HWND, ctypes.c_int]
    _GetWindowLong = user32.GetWindowLongPtrW
except AttributeError:  # 32 位 Python
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


# ----------------------------------------------------------------------------
# 路径
# ----------------------------------------------------------------------------
def base_dir():
    """运行目录：打包后为 _MEIPASS，否则为脚本所在目录。"""
    if getattr(sys, 'frozen', False):
        return sys._MEIPASS
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
# 显示器信息
# ----------------------------------------------------------------------------
def enum_monitors():
    """返回所有显示器的工作区矩形（物理像素）。"""
    rects = []
    MONITORENUMPROC = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HMONITOR,
                                         wintypes.HDC, ctypes.POINTER(wintypes.RECT),
                                         wintypes.LPARAM)

    def _cb(hmon, hdc, lprc, lparam):
        mi = MONITORINFO()
        mi.cbSize = ctypes.sizeof(MONITORINFO)
        if user32.GetMonitorInfoW(hmon, ctypes.byref(mi)):
            r = mi.rcWork
            rects.append((r.left, r.top, r.right, r.bottom))
        return True

    user32.EnumDisplayMonitors(0, 0, MONITORENUMPROC(_cb), 0)
    if not rects:
        w = user32.GetSystemMetrics(0)
        h = user32.GetSystemMetrics(1)
        rects = [(0, 0, w, h)]
    return rects


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
        self.window = None
        self._drag_active = False
        self._state_lock = threading.Lock()
        self._state_timer = None
        self._last_state_text = None

    # ---- 句柄 -----------------------------------------------------------
    def hwnd(self):
        """优先用 FindWindow 取窗口句柄，避免 pywebview 的 .native 递归问题。"""
        h = user32.FindWindowW(None, 'FocusDeck Pro')
        if h:
            return int(h) or 0
        w = self.window
        if w is None:
            return 0
        native = getattr(w, 'native', None)
        if native is None:
            return 0
        try:
            return int(native.Handle.ToInt64())
        except Exception:
            try:
                return int(native.Handle.ToInt32())
            except Exception:
                return 0

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
        if 'topmost' in patch:
            self.set_topmost(bool(patch['topmost']))
        if 'opacity' in patch:
            self.set_opacity(float(patch['opacity']))
        return True

    def load_state(self):
        try:
            with open(STATE_PATH, 'r', encoding='utf-8') as f:
                return f.read()
        except Exception:
            return None

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

    # ---- 窗口行为 -------------------------------------------------------
    def set_topmost(self, on):
        hwnd = self.hwnd()
        if not hwnd:
            return False
        flag = HWND_TOPMOST if on else HWND_NOTOPMOST
        user32.SetWindowPos(wintypes.HWND(hwnd), wintypes.HWND(flag),
                            0, 0, 0, 0, SWP_NOACTIVATE | 0x0001 | 0x0002)
        return True

    def set_opacity(self, value):
        hwnd = self.hwnd()
        if not hwnd:
            return False
        try:
            v = float(value)
        except Exception:
            return False
        v = max(0.4, min(1.0, v))
        alpha = int(round(v * 255))
        if alpha >= 255:
            ex = _GetWindowLong(wintypes.HWND(hwnd), GWL_EXSTYLE)
            _SetWindowLong(wintypes.HWND(hwnd), GWL_EXSTYLE,
                           ctypes.c_void_p(int(ex) & ~WS_EX_LAYERED))
            user32.SetLayeredWindowAttributes(wintypes.HWND(hwnd), 0, 255, LWA_ALPHA)
        else:
            ex = _GetWindowLong(wintypes.HWND(hwnd), GWL_EXSTYLE)
            _SetWindowLong(wintypes.HWND(hwnd), GWL_EXSTYLE,
                           ctypes.c_void_p(int(ex) | WS_EX_LAYERED))
            user32.SetLayeredWindowAttributes(wintypes.HWND(hwnd), 0, alpha, LWA_ALPHA)
        return True

    def minimize(self):
        hwnd = self.hwnd()
        if hwnd:
            user32.ShowWindow(wintypes.HWND(hwnd), SW_MINIMIZE)
        return True

    def quit(self):
        self._save_geom()
        self._flush_state_now()
        hwnd = self.hwnd()
        if hwnd:
            user32.PostMessageW(wintypes.HWND(hwnd), WM_CLOSE, 0, 0)
        else:
            os._exit(0)
        return True

    def flash(self):
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

    # ---- 尺寸 -----------------------------------------------------------
    def _scale(self, hwnd):
        try:
            dpi = user32.GetDpiForWindow(wintypes.HWND(hwnd))
            return (dpi or 96) / 96.0
        except Exception:
            return 1.0

    def _rect(self, hwnd):
        r = wintypes.RECT()
        if not user32.GetWindowRect(wintypes.HWND(hwnd), ctypes.byref(r)):
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
        s = self._scale(hwnd)
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
    def drag(self, mode):
        """mode: move | n | s | e | w | nw | ne | sw | se。

        无边框的 WinForms 窗体不会响应 WM_NCLBUTTONDOWN 的边角代码，
        因此这里改为「后台线程跟踪鼠标 + SetWindowPos」的方式直接移动/缩放，
        完全可控、随 DPI 适配、带最小尺寸约束，在任意分辨率下都平滑。
        """
        if self._drag_active:
            return False
        hwnd = self.hwnd()
        if not hwnd:
            return False
        rect = self._rect(hwnd)
        if not rect:
            return False
        start = self._cursor()
        if not start:
            return False

        mode = str(mode)
        is_move = (mode == 'move')
        x0, y0, w0, h0 = rect
        sx, sy = start
        s = self._scale(hwnd)
        min_w = int(MIN_W * s)
        min_h = int(MIN_H * s)
        hwnd_ptr = wintypes.HWND(hwnd)

        def loop():
            self._drag_active = True
            try:
                while user32.GetAsyncKeyState(VK_LBUTTON) & 0x8000:
                    cur = self._cursor()
                    if not cur:
                        break
                    dx = cur[0] - sx
                    dy = cur[1] - sy
                    nx, ny, nw, nh = x0, y0, w0, h0
                    if is_move:
                        nx = x0 + dx
                        ny = y0 + dy
                    else:
                        if 'e' in mode:
                            nw = w0 + dx
                        if 's' in mode:
                            nh = h0 + dy
                        if 'w' in mode:
                            nw = w0 - dx
                            nx = x0 + dx
                        if 'n' in mode:
                            nh = h0 - dy
                            ny = y0 + dy
                        if nw < min_w:
                            if 'w' in mode:
                                nx -= (min_w - nw)
                            nw = min_w
                        if nh < min_h:
                            if 'n' in mode:
                                ny -= (min_h - nh)
                            nh = min_h
                    user32.SetWindowPos(
                        hwnd_ptr, 0, int(round(nx)), int(round(ny)),
                        int(round(nw)), int(round(nh)),
                        SWP_NOZORDER | SWP_NOACTIVATE,
                    )
                    time.sleep(DRAG_POLL)
            finally:
                self._drag_active = False
                self._save_geom()

        t = threading.Thread(target=loop, daemon=True)
        t.start()
        return True

    # ---- 文件 -----------------------------------------------------------
    def export_file(self, filename, content):
        try:
            import webview
            res = self.window.create_file_dialog(
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
            res = self.window.create_file_dialog(
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
            return True
        except Exception:
            return False


# ----------------------------------------------------------------------------
# 启动
# ----------------------------------------------------------------------------
def build_config():
    cfg = read_json(CONFIG_PATH, {})
    cfg.setdefault('topmost', True)
    cfg.setdefault('opacity', 1.0)
    cfg.setdefault('zoom', 1.0)
    cfg.setdefault('compact', False)
    g = cfg.get('geom') or {}
    w = int(g.get('w') or 420)
    h = int(g.get('h') or 700)
    x = g.get('x')
    y = g.get('y')
    if x is None or y is None or not is_on_screen(int(x), int(y), w, h):
        x = y = None
    return cfg, w, h, x, y


def main():
    import webview

    start_minimized = '--min' in sys.argv
    cfg, w, h, x, y = build_config()
    api = Api(cfg)

    html_path = resource('index.html')
    if not os.path.isfile(html_path):
        raise SystemExit('找不到 index.html：%s' % html_path)

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
    api.window = window

    def on_loaded():
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

    icon = resource('icon.ico')
    webview.start(
        func=None,
        private_mode=False,
        storage_path=os.path.join(data_dir(), 'webview2'),
        icon=icon if os.path.isfile(icon) else None,
        debug=False,
        http_server=True,      # 本地 http 服务，避免 file:// 下的能力限制
    )

    # 退出前最后保存一次几何信息
    try:
        api._save_geom()
    except Exception:
        pass


if __name__ == '__main__':
    main()
