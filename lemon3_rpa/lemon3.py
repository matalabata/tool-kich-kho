from __future__ import annotations

import ctypes
import re
import time
from ctypes import wintypes
from dataclasses import dataclass
from typing import Any

import pyautogui
from pywinauto import Desktop
from pywinauto.keyboard import send_keys as foreground_keys

pyautogui.FAILSAFE = True
pyautogui.PAUSE = 0.03

user32 = ctypes.windll.user32
kernel32 = ctypes.windll.kernel32

# Khong khai bao thi ctypes coi gia tri tra ve la int 32-bit, lam cat handle/con tro
# tren Windows 64-bit -> GlobalLock tra NULL -> access violation khi memmove.
user32.GetForegroundWindow.restype = wintypes.HWND
user32.SendMessageW.restype = ctypes.c_ssize_t
user32.SendMessageW.argtypes = [wintypes.HWND, wintypes.UINT, ctypes.c_size_t, ctypes.c_void_p]
user32.SetClipboardData.restype = wintypes.HANDLE
user32.SetClipboardData.argtypes = [wintypes.UINT, wintypes.HANDLE]
kernel32.GlobalAlloc.restype = wintypes.HGLOBAL
kernel32.GlobalAlloc.argtypes = [wintypes.UINT, ctypes.c_size_t]
kernel32.GlobalLock.restype = ctypes.c_void_p
kernel32.GlobalLock.argtypes = [wintypes.HGLOBAL]
kernel32.GlobalUnlock.argtypes = [wintypes.HGLOBAL]
kernel32.GlobalFree.restype = wintypes.HGLOBAL
kernel32.GlobalFree.argtypes = [wintypes.HGLOBAL]
user32.GetAsyncKeyState.restype = ctypes.c_short
user32.GetAsyncKeyState.argtypes = [ctypes.c_int]
kernel32.SetThreadExecutionState.restype = wintypes.DWORD
kernel32.SetThreadExecutionState.argtypes = [wintypes.DWORD]
user32.SendMessageTimeoutW.restype = ctypes.c_ssize_t
user32.SendMessageTimeoutW.argtypes = [
    wintypes.HWND,
    wintypes.UINT,
    ctypes.c_size_t,
    ctypes.c_void_p,
    wintypes.UINT,
    wintypes.UINT,
    ctypes.POINTER(ctypes.c_size_t),
]

SKIP_TITLE_PARTS = ("lemon3 rpa",)
HOST_TITLES = ("DIGINET Desktop", "LEMON3-ERP", "D00F3000")
GRID_CLASS_HINTS = ("grid", "spread", "datagrid", "listview", "syslistview", "farpoint", "datagridview")
GW_CHILD = 5
GW_HWNDNEXT = 2


@dataclass
class WindowInfo:
    title: str
    handle: int
    class_name: str
    backend: str


def list_windows(backend: str = "win32") -> list[WindowInfo]:
    backend = "win32"
    desk = Desktop(backend=backend)
    result: list[WindowInfo] = []
    for win in desk.windows():
        try:
            title = win.window_text() or ""
            if not title.strip() or _is_skipped(title):
                continue
            result.append(
                WindowInfo(
                    title=title.strip(),
                    handle=int(win.handle),
                    class_name="",
                    backend=backend,
                )
            )
        except Exception:
            continue
    return result


def _is_skipped(title: str) -> bool:
    return any(part in title.lower() for part in SKIP_TITLE_PARTS)


def find_windows(title_contains: list[str], backend: str = "win32") -> list[Any]:
    backend = "win32"
    needles = [t.lower() for t in title_contains if t]
    desk = Desktop(backend=backend)
    matches = []
    for win in desk.windows():
        try:
            title = (win.window_text() or "").lower()
        except Exception:
            continue
        if not title.strip() or _is_skipped(title):
            continue
        if needles and not any(n in title for n in needles):
            continue
        matches.append(win)
    return _prefer_specific(matches, needles)


def _prefer_specific(matches: list[Any], needles: list[str]) -> list[Any]:
    if len(matches) <= 1:
        return matches

    def score(win: Any) -> int:
        try:
            title = (win.window_text() or "").lower()
        except Exception:
            return 0
        points = 0
        for n in needles:
            if n in title:
                points += 10 + len(n)
        if "diginet desktop" in title:
            points += 40
        if "d00f3000" in title:
            points += 25
        if "d05f310" in title:
            points += 35
        return points

    return sorted(matches, key=score, reverse=True)


def attach(
    title_contains: list[str], backend: str = "win32", allow_host_fallback: bool = True
) -> Any:
    matches = find_windows(title_contains, backend="win32")
    if matches:
        return matches[0]
    if allow_host_fallback:
        host = find_windows(list(HOST_TITLES), backend="win32")
        if host:
            return host[0]
    raise RuntimeError(
        "Khong thay cua so DIGINET. Mo DIGINET Desktop, vao tab Danh sach hoa don ban hang."
    )


def child_title_hits(win: Any, needles: list[str], limit: int = 80) -> list[str]:
    hwnd = int(win.handle)
    found: list[str] = []
    needles_l = [n.lower() for n in needles if n]
    parent_top = _window_rect_hwnd(hwnd)[1]
    for child in _walk_controls(hwnd, max_depth=3):
        if len(found) >= 12:
            break
        title = _window_text(child)
        if not title:
            continue
        if any(n in title.lower() for n in needles_l):
            _l, top, _r, _b = _window_rect_hwnd(child)
            if top - parent_top <= 400:
                found.append(title)
    return found


def wait_for_window(
    title_contains: list[str],
    timeout_s: float = 15,
    backend: str = "win32",
    stop_flag: Any = None,
    allow_host_fallback: bool = False,
) -> Any:
    deadline = time.time() + timeout_s
    last_err = None
    while time.time() < deadline:
        if stop_flag is not None and stop_flag.is_set():
            raise InterruptedError("Da dung")
        try:
            return attach(
                title_contains,
                backend="win32",
                allow_host_fallback=allow_host_fallback,
            )
        except RuntimeError as exc:
            last_err = exc
            time.sleep(0.25)
    raise TimeoutError(f"Het gio cho cua so {title_contains}. {last_err or ''}".strip())


def wait_any(
    named: dict[str, list[str]],
    timeout_s: float = 15,
    backend: str = "win32",
    stop_flag: Any = None,
) -> tuple[str, Any]:
    deadline = time.time() + timeout_s
    while time.time() < deadline:
        if stop_flag is not None and stop_flag.is_set():
            raise InterruptedError("Da dung")
        for key, titles in named.items():
            matches = find_windows(titles, backend="win32")
            if matches:
                return key, matches[0]
        time.sleep(0.25)
    raise TimeoutError(f"Het gio cho mot trong cac cua so: {list(named)}")


def focus(win: Any) -> None:
    hwnd = int(win.handle)
    if user32.IsIconic(hwnd):
        user32.ShowWindow(hwnd, 9)
    _force_foreground(hwnd)
    time.sleep(0.08)


def window_rect(win: Any) -> tuple[int, int, int, int]:
    left, top, right, bottom = _window_rect_hwnd(int(win.handle))
    return left, top, right - left, bottom - top


def relative_click(win: Any, x: int, y: int) -> None:
    focus(win)
    left, top, _, _ = window_rect(win)
    pyautogui.click(left + x, top + y)


def capture_relative(win: Any) -> tuple[int, int]:
    left, top, _, _ = window_rect(win)
    pos = pyautogui.position()
    return int(pos.x - left), int(pos.y - top)


def grab_screen() -> Any:
    """Chup toan bo man hinh ao (ke ca man hinh phu)."""
    from PIL import ImageGrab

    return ImageGrab.grab(all_screens=True)


def grab_region(left: int, top: int, width: int, height: int) -> Any:
    """Chup theo toa do man hinh ao.

    pyautogui.screenshot(region=...) chup rieng man hinh chinh roi moi cat theo
    toa do man hinh ao, nen cua so nam tren man hinh phu se cho ra anh den.
    """
    from PIL import ImageGrab

    left, top = int(left), int(top)
    right = left + max(int(width), 1)
    bottom = top + max(int(height), 1)
    return ImageGrab.grab(bbox=(left, top, right, bottom), all_screens=True)


def image_is_blank(image: Any) -> bool:
    """Anh gan nhu mot mau: thuong la chup trat ra ngoai man hinh."""
    try:
        low, high = image.convert("L").getextrema()
    except Exception:
        return False
    return (high - low) < 8


_VK_NAMES: dict[str, int] = {
    "ctrl": 0x11,
    "control": 0x11,
    "shift": 0x10,
    "alt": 0x12,
    "esc": 0x1B,
    "escape": 0x1B,
    "pause": 0x13,
    "break": 0x13,
    "space": 0x20,
    "insert": 0x2D,
    "delete": 0x2E,
    "home": 0x24,
    "end": 0x23,
    "scrolllock": 0x91,
    "numlock": 0x90,
}
for _i in range(1, 25):
    _VK_NAMES[f"f{_i}"] = 0x6F + _i


def parse_hotkey(spec: str) -> list[int]:
    """'ctrl+shift+q' -> danh sach ma phim ao. Tra rong neu khong hieu."""
    codes: list[int] = []
    for token in str(spec or "").split("+"):
        token = token.strip().lower()
        if not token:
            return []
        if token in _VK_NAMES:
            codes.append(_VK_NAMES[token])
            continue
        if len(token) == 1 and token.isalnum():
            codes.append(ord(token.upper()))
            continue
        return []
    return codes


def key_is_down(vk: int) -> bool:
    return bool(user32.GetAsyncKeyState(int(vk)) & 0x8000)


def hotkey_is_down(codes: list[int]) -> bool:
    return bool(codes) and all(key_is_down(vk) for vk in codes)


def on_primary_screen(x: int, y: int) -> bool:
    return 0 <= int(x) < user32.GetSystemMetrics(0) and 0 <= int(y) < user32.GetSystemMetrics(1)


def monitor_summary() -> str:
    count = user32.GetSystemMetrics(80) or 1
    vx = user32.GetSystemMetrics(76)
    vy = user32.GetSystemMetrics(77)
    vw = user32.GetSystemMetrics(78)
    vh = user32.GetSystemMetrics(79)
    return f"{count} man hinh, vung ao {vw}x{vh} tu ({vx},{vy})"


def parse_xy(text: str) -> tuple[int, int] | None:
    parts = [p for p in re.split(r"[,;x\s]+", str(text or "").strip()) if p]
    if len(parts) < 2:
        return None
    try:
        return int(float(parts[0])), int(float(parts[1]))
    except ValueError:
        return None


def window_size_text(win: Any) -> str:
    _l, _t, width, height = window_rect(win)
    return f"{width}x{height}"


def scaled_xy(win: Any, xy: str, base_size: str = "") -> tuple[int, int] | None:
    """Toa do ghi o do phan giai khac se lech. Quy doi theo ti le kich thuoc cua so."""
    point = parse_xy(xy)
    if point is None:
        return None
    base = parse_xy(base_size)
    if base is None or base[0] <= 0 or base[1] <= 0:
        return point
    _l, _t, width, height = window_rect(win)
    if (width, height) == base:
        return point
    return int(round(point[0] * width / base[0])), int(round(point[1] * height / base[1]))


def escape_keys(text: str) -> str:
    special = {
        "{": "{{}",
        "}": "{}}",
        "+": "{+}",
        "^": "{^}",
        "%": "{%}",
        "~": "{~}",
        "(": "{(}",
        ")": "{)}",
    }
    return "".join(special.get(ch, ch) for ch in str(text))


def send_keys(win: Any, keys: str) -> None:
    focus(win)
    foreground_keys(keys, pause=0.03, with_spaces=True)


def send_keys_to_focus(keys: str) -> None:
    """Go phim vao control dang giu focus. Dropdown dang xo se dong neu ep foreground."""
    foreground_keys(keys, pause=0.03, with_spaces=True)


def is_foreground(win: Any) -> bool:
    return int(user32.GetForegroundWindow() or 0) == int(win.handle)


def window_responsive(win: Any, timeout_ms: int = 300) -> bool:
    """WM_NULL co hoi am khong: form dang nap du lieu se khong bom message,
    phim gui vao luc do bi nuot."""
    result = ctypes.c_size_t(0)
    sent = user32.SendMessageTimeoutW(
        int(win.handle), 0x0000, 0, None, 0x0002, int(timeout_ms), ctypes.byref(result)
    )
    return bool(sent)


def wait_responsive(win: Any, timeout_s: float = 20.0) -> float:
    """Cho form ranh tay. Tra ve so giay da cho."""
    started = time.time()
    deadline = started + max(timeout_s, 0.0)
    while time.time() < deadline:
        if window_responsive(win):
            return time.time() - started
        time.sleep(0.2)
    return time.time() - started


def ensure_foreground(win: Any, timeout_s: float = 3.0) -> bool:
    """Anh chup la anh man hinh: cua so khac de len DIGINET se lam OCR doc nham."""
    deadline = time.time() + timeout_s
    while time.time() < deadline:
        if is_foreground(win):
            return True
        focus(win)
        time.sleep(0.2)
    return is_foreground(win)


def keep_awake(enable: bool, keep_display: bool = False) -> bool:
    """Chan may ngu giua chung. Man hinh van duoc phep tat: desktop tat man van chup anh duoc.

    Trang thai gan voi thread goi ham, nen phai goi tu thread GUI de no song suot phien chay.
    """
    es_continuous = 0x80000000
    es_system_required = 0x00000001
    es_display_required = 0x00000002
    flags = es_continuous
    if enable:
        flags |= es_system_required
        if keep_display:
            flags |= es_display_required
    return bool(kernel32.SetThreadExecutionState(flags))


def monitor_off() -> bool:
    """Tat man hinh ma khong khoa may. Cham chuot/phim se bat lai, ke ca chuot ao cua bot."""
    hwnd_broadcast = 0xFFFF
    wm_syscommand = 0x0112
    sc_monitorpower = 0xF170
    power_off = 2
    smto_abortifhung = 0x0002
    result = ctypes.c_size_t(0)
    sent = user32.SendMessageTimeoutW(
        hwnd_broadcast,
        wm_syscommand,
        sc_monitorpower,
        power_off,
        smto_abortifhung,
        1000,
        ctypes.byref(result),
    )
    return bool(sent)


class _GUITHREADINFO(ctypes.Structure):
    _fields_ = [
        ("cbSize", wintypes.DWORD),
        ("flags", wintypes.DWORD),
        ("hwndActive", wintypes.HWND),
        ("hwndFocus", wintypes.HWND),
        ("hwndCapture", wintypes.HWND),
        ("hwndMenuOwner", wintypes.HWND),
        ("hwndMoveSize", wintypes.HWND),
        ("hwndCaret", wintypes.HWND),
        ("rcCaret", wintypes.RECT),
    ]


def focused_hwnd(win: Any) -> int:
    pid = wintypes.DWORD()
    tid = user32.GetWindowThreadProcessId(int(win.handle), ctypes.byref(pid))
    info = _GUITHREADINFO()
    info.cbSize = ctypes.sizeof(_GUITHREADINFO)
    if not user32.GetGUIThreadInfo(tid, ctypes.byref(info)):
        return 0
    return int(info.hwndFocus or 0)


def control_text(hwnd: int) -> str:
    """Doc noi dung that cua control. GetWindowText khong doc duoc o nhap khac process."""
    if not hwnd:
        return ""
    wm_gettext, wm_gettextlength = 0x000D, 0x000E
    length = int(user32.SendMessageW(hwnd, wm_gettextlength, 0, 0))
    if length <= 0:
        return ""
    buf = ctypes.create_unicode_buffer(length + 1)
    user32.SendMessageW(hwnd, wm_gettext, length + 1, ctypes.byref(buf))
    return buf.value


def focused_text(win: Any) -> str:
    return control_text(focused_hwnd(win))


def type_text(win: Any, text: str) -> None:
    if any(ord(ch) > 127 for ch in str(text)):
        _set_clipboard(str(text))
        send_keys(win, "^v")
        return
    send_keys(win, escape_keys(str(text)))


def type_into_focus(text: str, pause: float = 0.08) -> None:
    """Go vao control dang focus. Khong ep foreground — focus(win) se mat o loc luoi."""
    if any(ord(ch) > 127 for ch in str(text)):
        _set_clipboard(str(text))
        foreground_keys("^v", pause=0.03)
        return
    foreground_keys(escape_keys(str(text)), pause=max(pause, 0.04), with_spaces=True)


def _set_clipboard(text: str) -> None:
    cf_unicode = 13
    gmem_moveable = 0x0002
    data = text.encode("utf-16le") + b"\x00\x00"
    handle = kernel32.GlobalAlloc(gmem_moveable, len(data))
    if not handle:
        raise RuntimeError("Khong cap phat duoc bo nho clipboard")
    locked = kernel32.GlobalLock(handle)
    if not locked:
        kernel32.GlobalFree(handle)
        raise RuntimeError("Khong khoa duoc bo nho clipboard")
    ctypes.memmove(locked, data, len(data))
    kernel32.GlobalUnlock(handle)
    if not user32.OpenClipboard(None):
        kernel32.GlobalFree(handle)
        raise RuntimeError("Khong mo duoc clipboard")
    try:
        user32.EmptyClipboard()
        if not user32.SetClipboardData(cf_unicode, handle):
            kernel32.GlobalFree(handle)
            raise RuntimeError("Khong ghi duoc clipboard")
    finally:
        user32.CloseClipboard()


def window_text_blob(win: Any) -> str:
    parts = [win.window_text() or ""]
    hwnd = int(win.handle)

    def collect(child: int) -> None:
        if len(parts) >= 20:
            return
        title = _window_text(child)
        if title:
            parts.append(title)

    for child in _walk_controls(hwnd, max_depth=2):
        collect(child)
        if len(parts) >= 20:
            break
    return "\n".join(parts)


def _text_matches(value: str, needle: str) -> bool:
    return _fold(needle) in _fold(value)


def has_visible_text(win: Any, needle: str, min_y_relative: int = 0) -> bool:
    """Check text exposed by a visible control, optionally only below a screen row."""
    if not needle:
        return False
    hwnd = int(win.handle)
    _left, parent_top, _right, _bottom = _window_rect_hwnd(hwnd)
    if min_y_relative <= 0 and _text_matches(win.window_text() or "", needle):
        return True
    for child in _walk_controls(hwnd, max_depth=4):
        title = _window_text(child)
        if not title or not _text_matches(title, needle):
            continue
        _l, top, _r, _b = _window_rect_hwnd(child)
        if top - parent_top >= min_y_relative:
            return True
    return False


def wait_for_grid_text(
    win: Any, needle: str, timeout_s: float = 8, stop_flag: Any = None
) -> bool:
    """Wait for a voucher in grid controls, never treating the filter input as a result."""
    hwnd = int(win.handle)
    _l, parent_top, _r, parent_bottom = _window_rect_hwnd(hwnd)
    height = max(parent_bottom - parent_top, 1)
    grid_tops = []
    for child in _walk_controls(hwnd, max_depth=3):
        if _looks_like_grid(child):
            _cl, top, _cr, _cb = _window_rect_hwnd(child)
            grid_tops.append(max(0, top - parent_top))
    # Exclude the header/filter row even if Lemon3 does not expose its grid class.
    min_y = min(grid_tops) if grid_tops else max(140, int(height * 0.25))
    deadline = time.time() + max(timeout_s, 0.2)
    while time.time() < deadline:
        if stop_flag is not None and stop_flag.is_set():
            raise InterruptedError("Da dung")
        if has_visible_text(win, needle, min_y_relative=min_y):
            return True
        time.sleep(0.2)
    return False


def click_visible_text(win: Any, needle: str, min_y_relative: int = 0) -> bool:
    """Click an exposed exact/partial text control. Returns False rather than guessing."""
    if not needle:
        return False
    hwnd = int(win.handle)
    _left, parent_top, _right, _bottom = _window_rect_hwnd(hwnd)
    folded_needle = _fold(needle)
    partial: tuple[int, int, int, int] | None = None
    for child in _walk_controls(hwnd, max_depth=4):
        title = _window_text(child)
        if not title:
            continue
        rect = _window_rect_hwnd(child)
        if rect[1] - parent_top < min_y_relative:
            continue
        folded_title = _fold(title)
        if folded_title == folded_needle:
            pyautogui.click((rect[0] + rect[2]) // 2, (rect[1] + rect[3]) // 2)
            return True
        if folded_needle in folded_title and partial is None:
            partial = rect
    if partial is not None:
        pyautogui.click((partial[0] + partial[2]) // 2, (partial[1] + partial[3]) // 2)
        return True
    return False


def type_near_label(win: Any, label: str, text: str) -> None:
    """Click the edit to the right of a form label, then type. Does not walk grids."""
    focus(win)
    hwnd = int(win.handle)
    needle = _fold(label)
    for child in _walk_controls(hwnd, max_depth=4):
        if _looks_like_grid(child):
            continue
        title = _window_text(child)
        if not title or needle not in _fold(title):
            continue
        left, top, right, bottom = _window_rect_hwnd(child)
        pyautogui.click(right + 40, (top + bottom) // 2)
        time.sleep(0.12)
        foreground_keys("^a", pause=0.02)
        type_text(win, text)
        return
    raise RuntimeError(f"Khong thay o '{label}'")


def type_in_field(win: Any, label: str, text: str) -> None:
    focus(win)
    hwnd = int(win.handle)
    _pl, parent_top, _pr, parent_bottom = _window_rect_hwnd(hwnd)
    height = max(parent_bottom - parent_top, 1)
    needle = _fold(label)
    candidates: list[tuple[int, int, int, int, int]] = []
    for child in _walk_controls(hwnd, max_depth=4):
        title = _window_text(child)
        if not title or needle not in _fold(title):
            continue
        left, top, right, bottom = _window_rect_hwnd(child)
        y_rel = top - parent_top
        if y_rel < 40 or y_rel > int(height * 0.62):
            continue
        candidates.append((y_rel, left, top, right, bottom))
    if not candidates:
        raise RuntimeError(
            "Khong thay o loc cot So phieu tren luoi. "
            "Bam Ghi toa do, dua chuot vao o loc NGAY DUOI tieu de cot So phieu, roi dien so_phieu_xy."
        )
    y_rel, left, top, right, bottom = max(candidates, key=lambda item: item[0])
    if y_rel > 200:
        click_x = (left + right) // 2
        click_y = bottom + 12
    else:
        click_x = right + 36
        click_y = (top + bottom) // 2
    pyautogui.click(click_x, click_y)
    time.sleep(0.12)
    foreground_keys("^a", pause=0.02)
    type_text(win, text)


def click_button(title: str, win: Any | None = None, timeout_s: float = 6) -> None:
    needle = title.strip().lower().replace("&", "")
    deadline = time.time() + timeout_s
    last_err = "khong thay nut"
    while time.time() < deadline:
        targets: list[int] = []
        if win is not None:
            targets = [int(win.handle)]
        else:
            for info in list_windows("win32"):
                targets.append(info.handle)
        for hwnd in targets:
            child = _find_button_hwnd(hwnd, needle)
            if not child:
                continue
            # BM_CLICK qua SendMessageTimeout: khong can man hinh sang, khong treo
            # neu DIGINET dang ban. pyautogui.click chi dung khi BM_CLICK khong di.
            result = ctypes.c_size_t(0)
            sent = user32.SendMessageTimeoutW(
                child,
                0x00F5,
                0,
                None,
                0x0002,
                800,
                ctypes.byref(result),
            )
            if sent:
                return
            left, top, right, bottom = _window_rect_hwnd(child)
            try:
                pyautogui.click((left + right) // 2, (top + bottom) // 2)
                return
            except Exception as exc:
                last_err = str(exc)
        time.sleep(0.2)
    raise RuntimeError(f"Khong bam duoc nut '{title}': {last_err}")


def click_grid(_win: Any) -> None:
    return


def describe_controls(_win: Any, limit: int = 80) -> list[str]:
    return ["Khong quet control tree de tranh treo ERP."]


def _find_button_hwnd(hwnd: int, needle: str) -> int:
    hit = 0
    needle = (needle or "").lower().replace("&", "")
    if not needle:
        return 0
    for child in _walk_controls(hwnd, max_depth=3):
        title = _window_text(child)
        if not title:
            continue
        low = title.lower().replace("&", "")
        if _looks_like_grid(child):
            continue
        if low == needle or low.rstrip(".") == needle:
            return int(child)
        if needle in low and hit == 0 and len(low) <= len(needle) + 10:
            hit = int(child)
    return hit


def _find_button_rect(hwnd: int, needle: str) -> tuple[int, int, int, int] | None:
    child = _find_button_hwnd(hwnd, needle)
    if not child:
        return None
    return _window_rect_hwnd(child)


def _looks_like_grid(hwnd: int) -> bool:
    cls = _class_name(hwnd).lower()
    return any(hint in cls for hint in GRID_CLASS_HINTS)


def _window_text(hwnd: int) -> str:
    length = user32.GetWindowTextLengthW(hwnd) + 1
    if length <= 1:
        return ""
    buf = ctypes.create_unicode_buffer(length)
    user32.GetWindowTextW(hwnd, buf, length)
    return buf.value.strip()


def _class_name(hwnd: int) -> str:
    buf = ctypes.create_unicode_buffer(256)
    user32.GetClassNameW(hwnd, buf, 256)
    return buf.value


def _window_rect_hwnd(hwnd: int) -> tuple[int, int, int, int]:
    rect = wintypes.RECT()
    user32.GetWindowRect(hwnd, ctypes.byref(rect))
    return int(rect.left), int(rect.top), int(rect.right), int(rect.bottom)


def _iter_immediate_children(hwnd: int):
    child = user32.GetWindow(hwnd, GW_CHILD)
    while child:
        yield int(child)
        child = user32.GetWindow(child, GW_HWNDNEXT)


def _walk_controls(hwnd: int, max_depth: int = 3):
    def walk(current: int, depth: int):
        for child in _iter_immediate_children(current):
            yield child
            if _looks_like_grid(child):
                for i, gc in enumerate(_iter_immediate_children(child)):
                    if i >= 10:
                        break
                    yield gc
                    for j, ggf in enumerate(_iter_immediate_children(gc)):
                        if j >= 24:
                            break
                        yield ggf
                continue
            if depth < max_depth:
                yield from walk(child, depth + 1)

    yield from walk(hwnd, 1)


def _fold(text: str) -> str:
    import unicodedata

    nfd = unicodedata.normalize("NFD", text or "")
    return "".join(ch for ch in nfd if unicodedata.category(ch) != "Mn").lower()


def _force_foreground(hwnd: int) -> bool:
    fg = user32.GetForegroundWindow()
    fg_tid = user32.GetWindowThreadProcessId(fg, None)
    this_tid = kernel32.GetCurrentThreadId()
    user32.AttachThreadInput(this_tid, fg_tid, True)
    ok = bool(user32.SetForegroundWindow(hwnd))
    user32.AttachThreadInput(this_tid, fg_tid, False)
    return ok
