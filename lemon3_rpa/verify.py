from __future__ import annotations

import re
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

from PIL import Image

from . import lemon3


@dataclass
class FindResult:
    found: bool
    source: str
    text: str
    image_path: Path | None = None


def voucher_exact_in(text: str, voucher: str) -> bool:
    token = re.sub(r"[^A-Z0-9]", "", (voucher or "").upper())
    if not token:
        return False
    tokens = re.findall(r"[A-Z0-9]+", (text or "").upper())
    if token in tokens:
        return True
    compact = "".join(tokens)
    if compact == token or (len(token) >= 10 and token in compact):
        return True
    # OCR crop o loc thuong cat mat tien to chu (MNBH0101... -> 0101...).
    tail = re.sub(r"^[A-Z]+", "", token)
    if len(tail) >= 10 and tail in tokens:
        return True
    return any(len(piece) >= 10 and token.endswith(piece) for piece in tokens)


def popup_is_success(message: str) -> bool:
    compact = re.sub(r"\s+", " ", message or "").strip()
    return "Dữ liệu đã được lưu thành công" in compact


def first_row_region(win: Any, filter_xy: tuple[int, int] | None = None) -> tuple[int, int, int, int]:
    left, top, width, height = lemon3.window_rect(win)
    if filter_xy:
        rel_x, rel_y = filter_xy
        band_left = left + max(rel_x - 200, 160)
        band_top = top + rel_y + 18
        band_w = min(640, width - (band_left - left) - 20)
        # Chi lay dong du lieu; band cao qua se gom dong trong -> RapidOCR tra rong.
        band_h = 32
    else:
        band_left = left + 220
        band_top = top + int(height * 0.38)
        band_w = min(640, width - 260)
        band_h = 36
    return band_left, band_top, max(band_w, 80), max(band_h, 24)


def capture_first_row_image(win: Any, filter_xy: tuple[int, int] | None = None) -> Image.Image:
    return lemon3.grab_region(*first_row_region(win, filter_xy))


_OCR_ENGINE: Any = None
_OCR_READY = False


def _ocr_engine() -> Any:
    """Nap RapidOCR mot lan. Tao moi moi lan goi lam OCR cham hang chuc giay."""
    global _OCR_ENGINE, _OCR_READY
    if not _OCR_READY:
        _OCR_READY = True
        try:
            from rapidocr_onnxruntime import RapidOCR

            _OCR_ENGINE = RapidOCR()
        except Exception:
            _OCR_ENGINE = None
    return _OCR_ENGINE


def ocr_image(image: Image.Image) -> str:
    variants = _ocr_variants(image)
    engine = _ocr_engine()
    if engine is not None:
        try:
            import numpy as np

            for variant in variants:
                # RapidOCR khong nhan PIL Image — can numpy / path / bytes.
                result, _ = engine(np.asarray(variant.convert("RGB")))
                if not result:
                    continue
                text = " ".join(str(row[1]) for row in result if len(row) > 1)
                if text.strip():
                    return text
        except Exception:
            pass
    try:
        import pytesseract

        for variant in variants:
            text = pytesseract.image_to_string(variant, lang="eng") or ""
            if text.strip():
                return text
    except Exception:
        pass
    return ""


def ocr_boxes(image: Image.Image) -> list[tuple[str, int, int, int, int]]:
    """(text, left, top, right, bottom) theo toa do trong anh.

    Tra rong neu khong co RapidOCR: pytesseract o day chi tra chu, khong tra vi tri.
    """
    engine = _ocr_engine()
    if engine is None:
        return []
    try:
        import numpy as np

        result, _ = engine(np.asarray(image.convert("RGB")))
    except Exception:
        return []
    boxes: list[tuple[str, int, int, int, int]] = []
    for row in result or []:
        if len(row) < 2:
            continue
        try:
            xs = [int(point[0]) for point in row[0]]
            ys = [int(point[1]) for point in row[0]]
        except (TypeError, ValueError, IndexError):
            continue
        if not xs or not ys:
            continue
        boxes.append((str(row[1]), min(xs), min(ys), max(xs), max(ys)))
    return boxes


def _ocr_variants(image: Image.Image) -> list[Image.Image]:
    from PIL import ImageOps

    rgb = image.convert("RGB")
    width, height = rgb.size
    top_h = max(20, min(height, int(height * 0.7)))
    top = rgb.crop((0, 0, width, top_h))
    variants = [top, rgb]
    if height <= 40:
        variants.insert(0, top.resize((width * 2, top_h * 2), Image.Resampling.LANCZOS))
    variants.append(ImageOps.invert(top))
    return variants


def read_visible_text(win: Any) -> str:
    return lemon3.window_text_blob(win)


def wait_until_result(
    win: Any,
    voucher: str,
    timeout_s: float = 0.5,
    filter_xy: tuple[int, int] | None = None,
    on_log: Callable[[str], None] | None = None,
    stop_flag: Any = None,
    screenshot_dir: Path | None = None,
    poll_s: float = 0.08,
    min_scans: int = 2,
) -> FindResult:
    log = on_log or (lambda _m: None)
    started = time.time()
    deadline = started + max(timeout_s, 0.2)
    last_text = ""
    last_image: Image.Image | None = None
    warned_cover = False
    warned_blank = False
    poll = max(poll_s, 0.05)
    scans = 0
    # Mot luot OCR co the lau hon ca timeout, nen phai bao dam du so lan quet
    # thay vi de vong lap thoat khi chua kip doc lan nao.
    while time.time() < deadline or scans < min_scans:
        if stop_flag is not None and stop_flag.is_set():
            raise InterruptedError("Da dung")
        # Khong dung window_text_blob: o loc vua go so phieu se lam false FOUND.
        if lemon3.wait_for_grid_text(win, voucher, timeout_s=0.05, stop_flag=stop_flag):
            log(
                f"FOUND qua control luoi (khong tinh o loc): {voucher} "
                f"sau {time.time() - started:.1f}s"
            )
            return FindResult(True, "control", voucher)
        # Anh chup theo toa do man hinh: cua so khac de len se bi OCR doc nham.
        if not lemon3.ensure_foreground(win, 0.4):
            if not warned_cover:
                warned_cover = True
                log("DIGINET dang bi cua so khac che, khong doc duoc luoi")
            time.sleep(poll)
            continue
        region = first_row_region(win, filter_xy)
        last_image = lemon3.grab_region(*region)
        if lemon3.image_is_blank(last_image) and not warned_blank:
            warned_blank = True
            log(
                f"Vung doc luoi {region} chi mot mau. {lemon3.monitor_summary()}. "
                "Keo DIGINET ve man hinh chinh roi bam Ghi toa do lai."
            )
        ocr = ocr_image(last_image)
        scans += 1
        last_text = ocr
        if voucher_exact_in(ocr, voucher):
            path = _save_image(last_image, screenshot_dir, f"found-{voucher}")
            log(f"FOUND qua OCR dong dau: {voucher} sau {time.time() - started:.1f}s ({scans} lan quet)")
            return FindResult(True, "ocr", ocr, path)
        time.sleep(poll)
    path = _save_image(last_image, screenshot_dir, f"notfound-{voucher}")
    log(
        f"NOT_FOUND {voucher} sau {time.time() - started:.1f}s ({scans} lan quet, "
        f"vung doc {first_row_region(win, filter_xy)}). Doc duoc: {last_text[:180]}"
    )
    return FindResult(False, "timeout", last_text, path)


def focus_looks_like_filter(
    parent_win: Any, expect_xy: tuple[int, int] | None = None
) -> tuple[bool, str]:
    """O nhap cua luoi la MOT control EDIT duoc di chuyen den o dang sua. Chi xet
    class thi o du lieu dang sua cung dat -> go so phieu vao du lieu, luoi khong loc.
    Co expect_xy thi doi hoi control dang phu dung o loc."""
    hwnd = lemon3.focused_hwnd(parent_win)
    if not hwnd:
        return False, "khong co control focus"
    cls = lemon3._class_name(hwnd)
    title = lemon3._window_text(hwnd)
    low = cls.lower()
    ok = any(token in low for token in ("edit", "tedit", "tmask", "textbox", "combo"))
    if not ok or expect_xy is None:
        return ok, f"{cls} | {title}"

    parent_left, parent_top, _w, _h = lemon3.window_rect(parent_win)
    want_x = parent_left + expect_xy[0]
    want_y = parent_top + expect_xy[1]
    left, top, right, bottom = lemon3._window_rect_hwnd(hwnd)
    pad = 8
    inside = (left - pad) <= want_x <= (right + pad) and (top - pad) <= want_y <= (bottom + pad)
    if inside:
        return True, f"{cls} | {title}"
    return False, (
        f"{cls} dang o ({left - parent_left},{top - parent_top})-"
        f"({right - parent_left},{bottom - parent_top}), khong phai o loc "
        f"({expect_xy[0]},{expect_xy[1]})"
    )


def _save_image(image: Image.Image | None, folder: Path | None, name: str) -> Path | None:
    if image is None or folder is None:
        return None
    folder.mkdir(parents=True, exist_ok=True)
    safe = re.sub(r"[^\w.-]+", "_", name)[:60]
    path = folder / f"{safe}.png"
    image.save(path)
    return path
