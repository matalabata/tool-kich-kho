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
_KHO_TITLES = ["D05F3104", "Chọn kho", "Chon kho"]
_PXK_TITLES = ["D05F3105", "Phiếu xuất kho", "Phieu xuat kho"]
_ALERT_TITLES = ["Thông báo", "Thong bao"]
# D05F3105 mo mat 20-22s sau Tiep tuc. Cho that thoang; TUYET DOI khong bam
# Tiep tuc lan hai: DIGINET se coi la mo phieu do lan nua va tu khoa phieu
# ("dang duoc xu ly boi User ...").
_CONTINUE_TIMEOUT_S = 60


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
    leftover = _close_leftover_forms(scenario, log)
    if leftover:
        shot = _shot(screenshot_dir, f"leftover-{voucher}")
        return FlowResult("FAILED", leftover, shot)
    danh_sach = lemon3.attach(
        ["DIGINET Desktop", "LEMON3-ERP", "D00F3000"],
        backend=scenario.backend,
    )
    lemon3.focus(danh_sach)
    time.sleep(delay)
    check()

    filter_xy = lemon3.scaled_xy(danh_sach, scenario.so_phieu_xy, scenario.so_phieu_base)
    fill_error = _fill_so_phieu(
        danh_sach, voucher, filter_xy, log, scenario.key_apply_filter
    )
    if fill_error:
        shot = _shot(screenshot_dir, f"filter-{voucher}")
        return FlowResult("FAILED", fill_error, shot)

    # Go du so xong: cho luoi loc ky tu cuoi, xuong dong, roi Ctrl+K.
    # Khong ep focus cua so (mat o loc). Khong chan Down bang OCR.
    time.sleep(0.4)
    check()
    down_error = _down_from_filter(
        danh_sach, voucher, filter_xy, scenario.key_row_down, log
    )
    if down_error:
        shot = _shot(screenshot_dir, f"down-{voucher}")
        return FlowResult("FAILED", down_error, shot)
    check()
    if find_only:
        filter_timeout_s = max(scenario.filter_timeout_ms, 1000) / 1000
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
        if not found.found:
            return FlowResult("NOT_FOUND", f"Luoi khong khop {voucher}", found.image_path)
        shot = found.image_path or _shot(screenshot_dir, f"find-ok-{voucher}")
        return FlowResult("FOUND", f"Tim thay {voucher} bang {found.source}", shot)

    log("Ctrl+K Xuat kho")
    lemon3.send_keys_to_focus("^k")

    kind, win = lemon3.wait_any(
        {
            "kho": _KHO_TITLES,
            "alert": _ALERT_TITLES,
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
    try:
        pxk = _open_phieu_xuat_kho(win, scenario, log, stop_flag, check)
    except TimeoutError as exc:
        shot = _shot(screenshot_dir, f"kho-{voucher}")
        return FlowResult("FAILED", str(exc), shot)
    lemon3.focus(pxk)
    # Form vua hien khong co nghia la nap xong. Go Alt+Down luc no con nap du lieu
    # thi combo Loai nghiep vu nuot phim, cac buoc sau sai day chuyen.
    waited = lemon3.wait_responsive(pxk, 30)
    if waited >= 0.5:
        log(f"Cho phieu xuat kho nap xong {waited:.1f}s")
    time.sleep(max(scenario.operation_ms, 300) / 1000)

    # DIGINET bao "dang duoc xu ly boi User ..." NGAY tren phieu vua mo. Popup modal
    # nuot phim: go tiep la gieo phim vao form trong roi Alt+L luu phieu rac.
    alert = _pending_alert(scenario, wait_s=0.6)
    if alert is not None:
        msg = lemon3.window_text_blob(alert).replace(chr(10), " ").strip()
        log(f"Thong bao khi mo phieu xuat kho: {msg[:180]}")
        shot = _shot(screenshot_dir, f"khoa-{voucher}")
        _dismiss_dialog(alert, scenario.key_confirm, "OK")
        _abandon_phieu_xuat_kho(scenario, log)
        if _voucher_is_locked(msg):
            return FlowResult(
                "FAILED",
                f"Phieu dang bi khoa boi user khac, khong xuat kho duoc: {msg[:200]}",
                shot,
            )
        return FlowResult("FAILED", f"DIGINET bao khi mo phieu xuat kho: {msg[:200]}", shot)

    op_error = _select_operation(pxk, scenario, log)
    if op_error:
        shot = _shot(screenshot_dir, f"nv-{voucher}")
        _abandon_phieu_xuat_kho(scenario, log)
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
            _PXK_TITLES,
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
    win: Any,
    voucher: str,
    filter_xy: tuple[int, int] | None,
    log: Callable[[str], None],
    apply_key: str = "",
) -> str:
    if not lemon3.ensure_foreground(win, 4.0):
        return (
            "DIGINET khong len duoc mat truoc, cua so khac dang che. "
            "Thu nho Lemon3 RPA va cac cua so khac roi chay lai."
        )
    ok, info = verify.focus_looks_like_filter(win, filter_xy)
    if filter_xy:
        # Ngay sau khi dong form con, luoi can vai nhip moi nhan click.
        for attempt in range(3):
            if ok:
                break
            lemon3.relative_click(win, filter_xy[0], filter_xy[1])
            time.sleep(0.15 + 0.35 * attempt)
            ok, info = verify.focus_looks_like_filter(win, filter_xy)
        log(f"Click o loc {filter_xy[0]},{filter_xy[1]} tren cua so {lemon3.window_size_text(win)} -> {info}")
    else:
        log(f"Focus hien tai: {info}")
    if not ok:
        return (
            f"Focus khong nam trong o loc ({info}). "
            "Click o loc duoi cot So phieu, hoac bam Ghi toa do."
        )
    return _type_voucher(win, voucher, log, apply_key)


def _plain(text: str) -> str:
    return re.sub(r"[^A-Z0-9]", "", (text or "").upper())


def _clear_filter_cell(win: Any) -> str:
    """O loc FarPoint khong phai luc nao cung nhan Ctrl+A. Khong xoa sach thi
    lan go sau noi duoi lan truoc: '...082466MNBH010126082466'.
    Khong focus lai cua so — se mat o loc."""
    for keys in ("^a{DELETE}", "{END}+{HOME}{DELETE}", "{END}{BACKSPACE 60}{DELETE 20}"):
        lemon3.send_keys_to_focus(keys)
        if not lemon3.focused_text(win).strip():
            return ""
    return lemon3.focused_text(win).strip()


def _type_voucher(
    win: Any, voucher: str, log: Callable[[str], None], apply_key: str = ""
) -> str:
    """Go tung ky tu vao o loc dang focus. Chi xuong dong khi o loc da du so."""
    target = _plain(voucher)
    typed = ""
    for attempt in range(3):
        leftover = _clear_filter_cell(win)
        if leftover:
            log(f"O loc chua xoa het, con '{leftover}'")
        # Luoi loc theo tung su kien go phim. Dan clipboard / go qua nhanh
        # thi DIGINET nuot ky tu cuoi. Khong ep foreground trong luc go.
        lemon3.type_into_focus(str(voucher), pause=0.08)
        if apply_key:
            lemon3.send_keys_to_focus(apply_key)
        time.sleep(0.25)
        typed = lemon3.focused_text(win).strip()
        if not typed:
            log("Khong doc lai duoc o loc, coi nhu da go xong")
            return ""
        if _plain(typed) == target:
            log(f"Da go du so phieu: {typed}")
            return ""
        log(f"O loc dang la '{typed}' (can '{voucher}'), go lai ({attempt + 1}/3)")
    return f"O loc khong nhan dung so phieu, dang la '{typed}'"


def _down_from_filter(
    win: Any,
    voucher: str,
    filter_xy: tuple[int, int] | None,
    down_key: str,
    log: Callable[[str], None],
) -> str:
    """Xuong dong phieu tu o loc. Khong click lai va khong focus(win): click lai
    se bo o loc, focus(win) dua phim ve cay menu. Con dang o dung o loc voi dung
    so phieu thi moi Down — Down nham dong la Ctrl+K nham phieu."""
    ok, info = verify.focus_looks_like_filter(win, filter_xy)
    if not ok:
        return (
            f"Go xong nhung focus da roi khoi o loc ({info}), khong dam bao "
            "Down dung dong. Click o loc duoi cot So phieu, hoac bam Ghi toa do."
        )
    still = lemon3.focused_text(win).strip()
    if still and _plain(still) != _plain(voucher):
        return f"O loc dang la '{still}', khong phai '{voucher}'. Khong Down de tranh nham phieu."
    log(f"Xuong dong phieu ({down_key})")
    lemon3.send_keys_to_focus(down_key)
    time.sleep(0.2)
    return ""


# NFD khong tach duoc 'đ', 'ư', 'ơ' — bo qua thi 'được' thanh 'uoc', khong khop noi.
_VN_EXTRA = {"đ": "d", "ư": "u", "ơ": "o"}


def _letters(text: str) -> str:
    folded = lemon3._fold(text or "")
    for src, dst in _VN_EXTRA.items():
        folded = folded.replace(src, dst)
    return re.sub(r"[^a-z]", "", folded)


def _voucher_is_locked(message: str) -> bool:
    """'So phieu "MNBH..." dang duoc xu ly boi User "NV1722"'."""
    return "dangduocxuly" in _letters(message)


def _pending_alert(scenario: Scenario, wait_s: float = 0.0) -> Any | None:
    deadline = time.time() + max(wait_s, 0.0)
    while True:
        try:
            return lemon3.attach(
                _ALERT_TITLES, backend=scenario.backend, allow_host_fallback=False
            )
        except RuntimeError:
            if time.time() >= deadline:
                return None
            time.sleep(0.15)


def _abandon_phieu_xuat_kho(scenario: Scenario, log: Callable[[str], None]) -> None:
    """Dong D05F3105 va tra loi No cho moi hoi luu: bo phieu dang do, khong ghi du lieu."""
    try:
        pxk = lemon3.attach(_PXK_TITLES, backend=scenario.backend, allow_host_fallback=False)
    except RuntimeError:
        return
    log(f"Dong phieu xuat kho, KHONG luu ({scenario.key_close})")
    lemon3.focus(pxk)
    lemon3.send_keys(pxk, scenario.key_close)
    _dismiss_leftover_dialogs(scenario, log)


def _select_operation(win: Any, scenario: Scenario, log: Callable[[str], None]) -> str:
    """Xo dropdown Loai nghiep vu, xuong dong thu N, Enter de xac nhan."""
    code = (scenario.operation_code or "").strip()
    if not code:
        return ""
    alert = _pending_alert(scenario)
    if alert is not None:
        msg = lemon3.window_text_blob(alert).replace(chr(10), " ").strip()
        return f"Con popup dang che phieu xuat kho, khong chon nghiep vu: {msg[:200]}"
    row = max(scenario.operation_row, 1)
    # Dropdown vua xo da dung o dong 1, nen chi can xuong them row-1 lan.
    presses = row - 1
    settle = max(scenario.operation_ms, 300) / 1000
    lemon3.focus(win)
    lemon3.wait_responsive(win, 10)
    log(f"Xo dropdown Loai nghiep vu ({scenario.key_open_dropdown})")
    lemon3.send_keys(win, scenario.key_open_dropdown)
    time.sleep(settle)

    # Tu day khong focus lai form cha: dropdown la popup rieng, ep foreground se nuot phim.
    log(f"Xuong {presses} lan -> dong {row} ({code})")
    if presses > 0:
        lemon3.send_keys_to_focus("{DOWN " + str(presses) + "}")
        # Luoi tra cuu nap 4 dong tu DB; Enter den som la roi vao khoang trong.
        time.sleep(settle)

    for attempt in range(3):
        log(f"Enter xac nhan nghiep vu ({scenario.key_confirm})")
        lemon3.send_keys_to_focus(scenario.key_confirm)
        time.sleep(settle)
        if _operation_shows(win, code):
            log(f"Nghiep vu {code}" + (f" (sau Enter lan {attempt + 1})" if attempt else ""))
            return ""
    return (
        f"Khong chon duoc nghiep vu {code} o dong {row}: dropdown van dang xo "
        "sau 3 lan Enter."
    )


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


def _asks_to_save(message: str) -> bool:
    """DIGINET hoi 'Bạn có muốn lưu dữ liệu này hay không?' truoc khi luu that."""
    return "muonluu" in _letters(message)


def _asks_to_close(message: str) -> bool:
    """'Dữ liệu chưa được lưu. Bạn có muốn đóng không?' — Yes moi dong duoc form."""
    return "muondong" in _letters(message)


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
                {"alert": _ALERT_TITLES},
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
                _ALERT_TITLES,
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
        elif _asks_to_close(msg):
            # 'Du lieu chua duoc luu. Ban co muon dong khong?' — No thi form o lai
            # che luoi, phieu ke tiep khong loc duoc.
            _dismiss_dialog(alert, scenario.key_yes, "Yes")
        else:
            _dismiss_dialog(alert, scenario.key_confirm, "OK")


def _caption_is_continue(text: str) -> bool:
    folded = re.sub(r"[^a-z]", "", lemon3._fold(text or ""))
    return "tieptuc" in folded


def _focused_caption(win: Any) -> str:
    hwnd = lemon3.focused_hwnd(win)
    return (lemon3.control_text(hwnd) or lemon3._window_text(hwnd) or "").replace("&", "")


def _press_continue(win: Any, scenario: Scenario, log: Callable[[str], None]) -> None:
    """Alt+T truot khi focus dang o luoi kho — nut chi nhan focus chu khong bam.
    Nut dang focus thi Enter la chac an nhat. Chi bam DUNG MOT LAN."""
    lemon3.focus(win)
    if _caption_is_continue(_focused_caption(win)):
        log("Tiep tuc: nut dang focus, Enter")
        lemon3.send_keys_to_focus("{ENTER}")
        return
    log(f"Tiep tuc ({scenario.key_continue})")
    lemon3.send_keys(win, scenario.key_continue)


def _open_phieu_xuat_kho(
    kho_win: Any,
    scenario: Scenario,
    log: Callable[[str], None],
    stop_flag: Any,
    check: Callable[[], None],
) -> Any:
    """Bam Tiep tuc MOT LAN roi cho D05F3105. Bam lan hai se mo phieu do them
    lan nua va DIGINET khoa phieu lai ngay."""
    _press_continue(kho_win, scenario, log)
    started = time.time()
    while time.time() - started < _CONTINUE_TIMEOUT_S:
        check()
        pxk = lemon3.find_windows(_PXK_TITLES)
        if pxk:
            log(f"Phieu xuat kho mo sau {time.time() - started:.0f}s")
            return pxk[0]
        alerts = lemon3.find_windows(_ALERT_TITLES)
        if alerts:
            msg = lemon3.window_text_blob(alerts[0])
            lemon3.send_keys(alerts[0], "{ENTER}")
            raise TimeoutError(f"Lemon3 bao khi Tiep tuc: {msg[:240]}")
        time.sleep(0.25)
    raise TimeoutError(
        f"Bam Tiep tuc roi cho {_CONTINUE_TIMEOUT_S}s van chua thay Phieu xuat kho "
        "D05F3105. Khong bam Tiep tuc lan nua de tranh khoa phieu. Xu ly tay man "
        "Chon kho roi chay lai."
    )


def _close_leftover_forms(scenario: Scenario, log: Callable[[str], None]) -> str:
    """Phieu xuat kho / Chon kho con mo se che luoi. ESC khong dong duoc
    D05F3104 khi focus dang o nut Tiep tuc — phai bam nut Dong.
    Tra ve thong bao neu form van de len luoi."""
    _dismiss_leftover_dialogs(scenario, log)
    closed_any = False
    blocked = ""
    for titles, key in (
        (_KHO_TITLES, "{ESC}"),
        (_PXK_TITLES, scenario.key_close),
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
        if titles[0] == "D05F3104" and not _window_gone(win, 1.2):
            try:
                lemon3.click_button("Đóng", win, timeout_s=2)
            except Exception:
                lemon3.send_keys(win, "%{F4}")
            _dismiss_leftover_dialogs(scenario, log)
        if not _window_gone(win, 3.0):
            log(f"{titles[0]} van con mo")
            if titles[0] == "D05F3104":
                blocked = (
                    "Man Chon kho D05F3104 van mo, khong loc duoc phieu ke tiep. "
                    "Bam Dong tren man Chon kho roi chay lai."
                )
    if closed_any:
        time.sleep(0.6)
    return blocked


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
