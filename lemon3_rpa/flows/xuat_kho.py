from __future__ import annotations

import re
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

from .. import lemon3
from .. import verify
from ..scenario import Scenario

# Chan tren khi tu dem dong kho, tranh go lac xuong cuoi luoi.
_MAX_DESCRIPTION_ROWS = 6


@dataclass
class FlowResult:
    status: str
    message: str
    screenshot: Path | None = None
    erp_reference: str = ""


def run_voucher(
    voucher: str,
    scenario: Scenario,
    row: dict[str, Any] | None = None,
    find_only: bool = False,
    screenshot_dir: Path | None = None,
    on_log: Callable[[str], None] | None = None,
    stop_flag: Any = None,
    pause_fn: Callable[[], None] | None = None,
) -> FlowResult:
    log = on_log or (lambda _m: None)
    pause = pause_fn or (lambda: None)
    row = row or {}
    delay = max(scenario.delay_ms, 80) / 1000

    def check() -> None:
        pause()
        if stop_flag is not None and stop_flag.is_set():
            raise InterruptedError("Da dung")

    check()
    log("Dung cua so DIGINET dang mo")
    _close_leftover_forms(scenario, log)
    danh_sach = lemon3.attach(
        ["DIGINET Desktop", "LEMON3-ERP", "D00F3000"],
        backend=scenario.backend,
    )
    lemon3.focus(danh_sach)
    time.sleep(delay)
    check()

    filter_xy = lemon3.scaled_xy(danh_sach, scenario.so_phieu_xy, scenario.so_phieu_base)
    fill_error = _fill_so_phieu(danh_sach, voucher, filter_xy, log)
    if fill_error:
        shot = _shot(screenshot_dir, f"filter-{voucher}")
        return FlowResult("FAILED", fill_error, shot)

    # Loc thuong xong <= 0.5s: cho den khi luoi hien phieu, khong sleep co dinh + timeout 12s.
    filter_timeout_s = max(scenario.after_type_ms, 200) / 1000
    found = verify.wait_until_result(
        danh_sach,
        voucher,
        timeout_s=filter_timeout_s,
        filter_xy=filter_xy,
        on_log=log,
        stop_flag=stop_flag,
        screenshot_dir=screenshot_dir,
        poll_s=0.08,
    )
    check()
    if not found.found:
        return FlowResult("NOT_FOUND", f"Luoi khong khop {voucher}", found.image_path)

    log(f"Xuong dong phieu ({scenario.key_row_down})")
    lemon3.send_keys(danh_sach, scenario.key_row_down)
    check()
    if find_only:
        shot = found.image_path or _shot(screenshot_dir, f"find-ok-{voucher}")
        return FlowResult("FOUND", f"Tim thay {voucher} bang {found.source}", shot)

    log("Ctrl+K Xuat kho")
    lemon3.send_keys(danh_sach, "^k")

    kind, win = lemon3.wait_any(
        {
            "kho": ["D05F3104", "Chọn kho", "Chon kho"],
            "alert": ["Thông báo", "Thong bao"],
        },
        timeout_s=25,
        backend=scenario.backend,
        stop_flag=stop_flag,
    )
    if kind == "alert":
        msg = lemon3.window_text_blob(win)
        lemon3.send_keys(win, "{ENTER}")
        shot = _shot(screenshot_dir, f"alert-k-{voucher}")
        return FlowResult("FAILED", f"Lemon3 bao khi xuat kho: {msg[:240]}", shot)

    # DIGINET da chon san kho 1000 — khong tick lai, chi bam Tiep tuc.
    log(f"Kho {scenario.warehouse_code} da duoc chon san")
    lemon3.focus(win)
    time.sleep(0.25)
    # Dem kho ngay tai day: dong ra khoi man Chon kho la mat thong tin nay.
    description_rows = _count_ticked_warehouses(win, log)
    log(f"Tiep tuc ({scenario.key_continue})")
    lemon3.send_keys(win, scenario.key_continue)
    time.sleep(delay)
    check()

    pxk = lemon3.wait_for_window(
        ["D05F3105", "Phiếu xuất kho", "Phieu xuat kho"],
        timeout_s=20,
        backend=scenario.backend,
        stop_flag=stop_flag,
    )
    lemon3.focus(pxk)
    time.sleep(max(scenario.operation_ms, 0) / 1000)
    op_error = _select_operation(pxk, scenario, log)
    if op_error:
        shot = _shot(screenshot_dir, f"nv-{voucher}")
        return FlowResult("FAILED", op_error, shot)

    log(f"Toi o Dien giai ({scenario.key_goto_description})")
    lemon3.send_keys(pxk, scenario.key_goto_description)
    time.sleep(0.2)
    desc_error = _fill_description(
        pxk,
        voucher,
        row,
        scenario.description_lines,
        scenario.description_rows or description_rows,
        log,
    )
    if desc_error:
        shot = _shot(screenshot_dir, f"diengiai-{voucher}")
        return FlowResult("FAILED", desc_error, shot)

    log(f"Luu phieu xuat kho ({scenario.key_save})")
    lemon3.send_keys(pxk, scenario.key_save)
    check()

    saved, msg = _handle_save_dialogs(scenario, log, stop_flag)
    if not saved:
        shot = _shot(screenshot_dir, f"uncertain-{voucher}")
        return FlowResult(
            "UNCERTAIN",
            "Popup khong khop dung 'Du lieu da duoc luu thanh cong'. Khong tu chay lai. "
            f"{msg[:240]}",
            shot,
        )

    try:
        pxk = lemon3.wait_for_window(
            ["D05F3105", "Phiếu xuất kho"],
            timeout_s=4,
            backend=scenario.backend,
            stop_flag=stop_flag,
        )
        log(f"Dong phieu xuat kho ({scenario.key_close})")
        lemon3.focus(pxk)
        lemon3.send_keys(pxk, scenario.key_close)
    except TimeoutError:
        log("Phieu xuat kho da dong san")
    return FlowResult("SUCCESS", "Da luu thanh cong")


def _fill_so_phieu(
    win: Any, voucher: str, filter_xy: tuple[int, int] | None, log: Callable[[str], None]
) -> str:
    if not lemon3.ensure_foreground(win, 4.0):
        return (
            "DIGINET khong len duoc mat truoc, cua so khac dang che. "
            "Thu nho Lemon3 RPA va cac cua so khac roi chay lai."
        )
    ok, info = verify.focus_looks_like_filter(win)
    if filter_xy:
        # Ngay sau khi dong form con, luoi can vai nhip moi nhan click.
        for attempt in range(3):
            lemon3.relative_click(win, filter_xy[0], filter_xy[1])
            time.sleep(0.15 + 0.35 * attempt)
            ok, info = verify.focus_looks_like_filter(win)
            if ok:
                break
        log(f"Click o loc {filter_xy[0]},{filter_xy[1]} tren cua so {lemon3.window_size_text(win)} -> {info}")
    else:
        log(f"Focus hien tai: {info}")
    if not ok:
        return (
            f"Focus khong nam trong o loc ({info}). "
            "Click o loc duoi cot So phieu, hoac bam Ghi toa do."
        )
    return _type_voucher(win, voucher, log)


def _plain(text: str) -> str:
    return re.sub(r"[^A-Z0-9]", "", (text or "").upper())


def _clear_filter_cell(win: Any) -> str:
    """O loc FarPoint khong phai luc nao cung nhan Ctrl+A. Khong xoa sach thi
    lan go sau noi duoi lan truoc va bo loc tra ve rong."""
    lemon3.send_keys(win, "^a{DELETE}")
    left = lemon3.focused_text(win).strip()
    if not left:
        return ""
    lemon3.send_keys(win, "{END}{BACKSPACE 80}{DELETE 20}")
    return lemon3.focused_text(win).strip()


def _enter_voucher(win: Any, voucher: str, attempt: int) -> None:
    """Luoi DIGINET loc theo su kien go phim. Ctrl+V khong sinh su kien do nen
    phai de lai ky tu cuoi cho go that, neu khong luoi giu nguyen ket qua cu."""
    text = str(voucher)
    _clear_filter_cell(win)
    if attempt == 0 and len(text) > 1:
        lemon3.paste_text(win, text[:-1])
        # Sau khi dan, con tro co the nhay ve dau o -> ky tu chot se lot len truoc.
        lemon3.send_keys(win, "{END}")
        lemon3.send_keys(win, lemon3.escape_keys(text[-1]))
        return
    # Du phong: go tung ky tu. Cham hon nhung chac chan kich hoat bo loc.
    lemon3.type_text(win, text)


def _type_voucher(win: Any, voucher: str, log: Callable[[str], None]) -> str:
    """Go xong doc lai o loc: DIGINET dang loc co the nuot vai ky tu cuoi."""
    target = _plain(voucher)
    typed = ""
    for attempt in range(3):
        _enter_voucher(win, voucher, attempt)
        time.sleep(0.2)
        typed = lemon3.focused_text(win).strip()
        if not typed:
            log("Khong doc lai duoc o loc, bo qua doi chieu")
            return ""
        if _plain(typed) == target:
            return ""
        log(f"O loc dang la '{typed}' (can '{voucher}'), go lai ({attempt + 1}/3)")
    return f"O loc khong nhan dung so phieu, dang la '{typed}'"


def _select_operation(win: Any, scenario: Scenario, log: Callable[[str], None]) -> str:
    """Xo dropdown Loai nghiep vu, xuong dong thu N, Enter de xac nhan."""
    code = (scenario.operation_code or "").strip()
    if not code:
        return ""
    row = max(scenario.operation_row, 1)
    # Dropdown vua xo da dung o dong 1, nen chi can xuong them row-1 lan.
    presses = row - 1
    settle = max(scenario.operation_ms, 0) / 1000
    lemon3.focus(win)
    log(f"Xo dropdown Loai nghiep vu ({scenario.key_open_dropdown})")
    lemon3.send_keys(win, scenario.key_open_dropdown)
    time.sleep(settle)

    # Tu day khong focus lai form cha: dropdown la popup rieng, ep foreground se nuot phim.
    log(f"Xuong {presses} lan -> dong {row} ({code})")
    if presses > 0:
        lemon3.send_keys_to_focus("{DOWN " + str(presses) + "}")
        time.sleep(settle)
    log(f"Enter xac nhan nghiep vu ({scenario.key_confirm})")
    lemon3.send_keys_to_focus(scenario.key_confirm)
    time.sleep(settle)

    if _operation_shows(win, code):
        log(f"Nghiep vu {code}")
        return ""

    # Dropdown co the con mo — Enter lan nua roi doc lai.
    lemon3.send_keys_to_focus(scenario.key_confirm)
    time.sleep(settle)
    if _operation_shows(win, code):
        log(f"Nghiep vu {code} (sau Enter lan 2)")
        return ""
    return f"Khong chon duoc nghiep vu {code} o dong {row}"


def _operation_shows(win: Any, code: str) -> bool:
    """Dung khi dropdown da dong VA combo hien dung ma."""
    needle = code.upper().replace(" ", "")
    left, top, width, height = lemon3.window_rect(win)
    band_h = max(160, min(int(height * 0.45), 420))
    img = lemon3.grab_region(left, top, max(width, 200), band_h)
    text = verify.ocr_image(img) or ""
    # Dong goi y nay chi hien khi dropdown dang xo.
    if "nhanphimenter" in re.sub(r"[^a-z]", "", lemon3._fold(text)):
        return False
    if needle in text.upper().replace(" ", ""):
        return True
    return needle in lemon3.window_text_blob(win).upper().replace(" ", "")


def _asks_to_save(message: str) -> str:
    """DIGINET hoi 'Bạn có muốn lưu dữ liệu này hay không?' truoc khi luu that."""
    folded = re.sub(r"[^a-z]", "", lemon3._fold(message))
    return "muonluudulieu" in folded or "muonluu" in folded


def _window_gone(win: Any, timeout_s: float) -> bool:
    import ctypes

    user32 = ctypes.windll.user32
    hwnd = int(win.handle)
    deadline = time.time() + timeout_s
    while time.time() < deadline:
        if not user32.IsWindow(hwnd) or not user32.IsWindowVisible(hwnd):
            return True
        time.sleep(0.12)
    return False


def _dismiss_dialog(win: Any, key: str, button_title: str) -> bool:
    """Bam phim tat truoc; popup khong dong thi click nut."""
    lemon3.focus(win)
    lemon3.send_keys_to_focus(key)
    if _window_gone(win, 2.0):
        return True
    try:
        lemon3.click_button(button_title, win, timeout_s=2)
    except Exception:
        pass
    return _window_gone(win, 2.0)


def _handle_save_dialogs(
    scenario: Scenario,
    log: Callable[[str], None],
    stop_flag: Any,
) -> tuple[bool, str]:
    """Alt+L -> hoi 'co muon luu' (Yes) -> bao 'luu thanh cong' (OK)."""
    last = ""
    for _round in range(3):
        try:
            _kind, alert = lemon3.wait_any(
                {"alert": ["Thông báo", "Thong bao"]},
                timeout_s=25,
                backend=scenario.backend,
                stop_flag=stop_flag,
            )
        except TimeoutError:
            return False, last or "Khong thay popup nao sau khi Luu"
        last = lemon3.window_text_blob(alert)
        log(f"Thong bao: {last.replace(chr(10), ' ')[:180]}")
        if verify.popup_is_success(last):
            if not _dismiss_dialog(alert, scenario.key_confirm, "OK"):
                log("Popup thanh cong chua dong duoc")
            return True, last
        if _asks_to_save(last):
            log(f"Xac nhan luu ({scenario.key_yes})")
            if not _dismiss_dialog(alert, scenario.key_yes, "Yes"):
                return False, last
            continue
        return False, last
    return False, last


def _dismiss_leftover_dialogs(scenario: Scenario, log: Callable[[str], None]) -> None:
    for _round in range(3):
        try:
            alert = lemon3.attach(
                ["Thông báo", "Thong bao"],
                backend=scenario.backend,
                allow_host_fallback=False,
            )
        except RuntimeError:
            return
        msg = lemon3.window_text_blob(alert)
        log(f"Dong popup con sot: {msg.replace(chr(10), ' ')[:120]}")
        if _asks_to_save(msg):
            # Khong tu luu du lieu dang do cua lan chay truoc.
            _dismiss_dialog(alert, "%n", "No")
        else:
            _dismiss_dialog(alert, scenario.key_confirm, "OK")


def _close_leftover_forms(scenario: Scenario, log: Callable[[str], None]) -> None:
    """Phieu xuat kho con mo se che luoi, lam phieu ke tiep NOT_FOUND."""
    # Popup modal chan het phim — phai dong popup truoc roi moi dong form.
    _dismiss_leftover_dialogs(scenario, log)
    closed_any = False
    for titles, key in (
        (["D05F3104", "Chọn kho"], "{ESC}"),
        (["D05F3105", "Phiếu xuất kho"], scenario.key_close),
    ):
        try:
            win = lemon3.attach(titles, backend=scenario.backend, allow_host_fallback=False)
        except RuntimeError:
            continue
        log(f"Dong form con sot: {titles[0]}")
        lemon3.focus(win)
        lemon3.send_keys(win, key)
        closed_any = True
        _dismiss_leftover_dialogs(scenario, log)
        if not _window_gone(win, 3.0):
            log(f"{titles[0]} van con mo")
    if closed_any:
        # Luoi D05F9300 can thoi gian ve lai truoc khi click o loc.
        time.sleep(0.6)


def _count_ticked_warehouses(win: Any, log: Callable[[str], None]) -> int:
    """Man Chon kho D05F3104 tick san cac kho se xuat va day chung len dau danh
    sach. So kho duoc tick chinh la so dong Dien giai tren D05F3105."""
    if not lemon3.ensure_foreground(win, 2.0):
        log("Man Chon kho bi che, khong dem duoc so kho")
        return 0
    left, top, width, height = lemon3.window_rect(win)
    image = lemon3.grab_region(left, top, width, height)
    if lemon3.image_is_blank(image):
        log("Anh man Chon kho chi mot mau, khong dem duoc so kho")
        return 0
    codes = _ticked_warehouse_codes(image)
    if not codes:
        log("Khong doc duoc kho nao duoc tick, se dien 1 dong dien giai")
        return 0
    log(f"Kho duoc xuat: {', '.join(codes)} -> {len(codes)} dong dien giai")
    return len(codes)


def _ticked_warehouse_codes(image: Any) -> list[str]:
    width, height = image.size
    # Chi OCR dai hep chua cot Ma kho cho nhanh; o tick doc bang mau, khong can OCR.
    strip = image.crop((0, 0, int(width * 0.20), height))
    codes: list[str] = []
    for text, _x0, y0, _x1, y1 in verify.ocr_boxes(strip):
        # Ma kho la day 3-6 chu so mo dau o. OCR co luc gop ca ten kho vao cung
        # mot o nen chi doi khop phan dau.
        match = re.match(r"(\d{3,6})\b", text.strip())
        if not match:
            continue
        if _row_is_ticked(image, y0, y1, width):
            codes.append(match.group(1))
    return codes


def _row_is_ticked(image: Any, top: int, bottom: int, width: int) -> bool:
    """Cot 'Chon kho' o ria phai: o da tick to xanh dac, o chua tick de trang."""
    band = image.crop(
        (int(width * 0.80), max(top - 4, 0), width, bottom + 4)
    ).convert("RGB")
    blue = 0
    for red, green, blue_ch in band.getdata():
        if blue_ch > 120 and blue_ch - red > 60 and blue_ch - green > 30:
            blue += 1
            if blue >= 20:
                return True
    return False


def _fill_description(
    win: Any,
    voucher: str,
    row: dict[str, Any],
    lines: list[dict[str, Any]],
    row_count: int,
    log: Callable[[str], None],
) -> str:
    """Luoi kho co 1-3 dong, moi dong mot o Dien giai rieng. Phai dien het cac
    dong roi flow moi bam Luu, khong gop thanh mot o nhieu dong."""
    values: list[str] = []
    for item in lines:
        template = str(item.get("template") or "")
        text = _render(template, voucher, row)
        if not text and bool(item.get("required")):
            return f"Thieu dien giai bat buoc: {template}"
        values.append(text)
    # Dong nao khong co mau rieng thi dung chung dien giai cua dong dau (so phieu).
    default_text = next((value for value in values if value), "")
    if not default_text:
        return ""

    rows = max(1, min(row_count or 1, _MAX_DESCRIPTION_ROWS))
    lemon3.focus(win)
    for index in range(rows):
        text = values[index] if index < len(values) and values[index] else default_text
        error = _type_description_cell(win, text)
        if error:
            return f"Dien giai dong {index + 1}: {error}"
        log(f"Dien giai dong {index + 1}: {text}")
        if index + 1 < rows:
            lemon3.send_keys(win, "{DOWN}")
            time.sleep(0.15)
    log(f"Da dien {rows} dong dien giai")
    return ""


def _type_description_cell(win: Any, text: str) -> str:
    """Go xong doc lai: Ctrl+A khong an thi noi dung cu con nam trong o."""
    typed = ""
    for _attempt in range(2):
        lemon3.send_keys(win, "^a")
        lemon3.type_text(win, text)
        time.sleep(0.12)
        typed = lemon3.focused_text(win).strip()
        if not typed or lemon3._fold(typed) == lemon3._fold(text):
            return ""
    return f"o dang la '{typed}', can '{text}'"


def _render(template: str, voucher: str, row: dict[str, Any]) -> str:
    text = template.replace("{so_phieu}", voucher)
    for key, value in list(row.items()):
        if key.startswith("_") or value is None:
            continue
        text = text.replace("{" + str(key) + "}", str(value).strip())
        text = text.replace("{column:" + str(key) + "}", str(value).strip())
    if "{" in text and "}" in text:
        return ""
    return text.strip()


def _shot(folder: Path | None, name: str) -> Path | None:
    if folder is None:
        return None
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / f"{name}.png"
    lemon3.grab_screen().save(path)
    return path
