from __future__ import annotations

import re
import threading
import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Callable

from . import excel_io, lemon3
from .scenario import Scenario, Step

TEMPLATE_RE = re.compile(r"\{\{\s*([^}]+?)\s*\}\}")

# Nhieu phieu lien tiep NOT_FOUND thuong la DIGINET dang o man hinh khac, khong
# phai phieu that khong ton tai. Chay tiep chi lam hong ca danh sach.
MAX_MISS_STREAK = 5


@dataclass
class RunOptions:
    excel_path: str
    scenario: Scenario
    voucher_column: str
    title_contains: list[str]
    dry_run: bool = False
    find_only: bool = False
    write_status: bool = True
    log_dir: str = "logs"


class Runner:
    def __init__(self, options: RunOptions, on_log: Callable[[str], None] | None = None) -> None:
        self.options = options
        self.on_log = on_log or (lambda _msg: None)
        self.pause_event = threading.Event()
        self.stop_event = threading.Event()
        self.continue_event = threading.Event()
        self.pause_event.clear()
        self.win = None

    def log(self, message: str) -> None:
        self.on_log(message)

    def request_pause(self) -> None:
        self.pause_event.set()
        self.continue_event.clear()

    def request_continue(self) -> None:
        self.pause_event.clear()
        self.continue_event.set()

    def request_stop(self) -> None:
        self.stop_event.set()
        self.continue_event.set()

    def _wait_if_paused(self) -> None:
        if self.stop_event.is_set():
            raise InterruptedError("Da dung")
        if self.pause_event.is_set():
            self.log("Tam dung. Bam Tiep tuc de chay tiep.")
            self.continue_event.wait()
            self.continue_event.clear()
            if self.stop_event.is_set():
                raise InterruptedError("Da dung")

    def _row_value(self, row: dict[str, Any], column: str) -> str:
        if column in row and row[column] is not None:
            return str(row[column]).strip()
        key = excel_io._norm(column)
        if key in row and row[key] is not None:
            return str(row[key]).strip()
        return ""

    def _fill(self, text: str, row: dict[str, Any]) -> str:
        def repl(match: re.Match[str]) -> str:
            return self._row_value(row, match.group(1).strip())

        return TEMPLATE_RE.sub(repl, text)

    def run(self) -> tuple[int, int]:
        from .run_store import RunStore

        opt = self.options
        headers, rows = excel_io.load_rows(opt.excel_path)
        if not rows:
            raise RuntimeError("File Excel khong co du lieu.")
        voucher_col = excel_io.find_voucher_column(headers, opt.voucher_column)
        if not voucher_col:
            raise RuntimeError("Khong tim thay cot so phieu.")
        store = RunStore()
        result_path = store.copy_excel(opt.excel_path)
        gui_log = self.on_log

        def log(message: str) -> None:
            store.log(message)
            gui_log(message)

        self.on_log = log
        self.log(f"Run {store.run_id} | khong ghi de file Excel goc")
        self.log(f"Ket qua: {result_path}")
        self.log(f"Log file: {store.log_path}")
        self.log(f"Cot phieu: {voucher_col} | {len(rows)} dong")

        if opt.dry_run:
            self.log("Chi chay thu: khong nhap DIGINET.")
        else:
            if opt.find_only:
                self.log("KIEM TRA TIM PHIEU: nhap + xac minh, KHONG Ctrl+K, KHONG Luu.")
            self.win = lemon3.attach(opt.title_contains, backend=opt.scenario.backend)
            self.log(f"Dung cua so dang mo: {self.win.window_text()}")

        skip = {(opt.scenario.skip_if_status or "OK").upper(), "SUCCESS", "SKIPPED"}
        ok = 0
        fail = 0
        miss_streak = 0
        for index, row in enumerate(rows, start=1):
            try:
                self._wait_if_paused()
            except InterruptedError:
                self.log("Dung giua chung.")
                break
            status = (
                self._row_value(row, "AUTOMATION_STATUS")
                or self._row_value(row, "KetQua")
                or self._row_value(row, "ket_qua")
            )
            if (not opt.find_only) and status.upper() in skip:
                self.log(f"[{index}/{len(rows)}] Bo qua ({status})")
                continue
            voucher = self._row_value(row, voucher_col)
            if not voucher:
                self.log(f"[{index}/{len(rows)}] Thieu so phieu")
                excel_io.write_run_result(
                    result_path, int(row["_excel_row"]), "SKIPPED", "Thieu so phieu", 0, store.run_id
                )
                continue
            self.log(f"[{index}/{len(rows)}] Phieu {voucher}")
            store.checkpoint(voucher=voucher, state="START", index=index)
            try:
                if opt.dry_run:
                    self.log("  [thu] go phieu -> wait_until_result -> Ctrl+K -> kho 1000 -> Luu")
                    outcome, message, shot, erp_ref = "SKIPPED", "dry_run", "", ""
                elif opt.scenario.flow == "xuat_kho":
                    from .flows.xuat_kho import run_voucher

                    result = run_voucher(
                        voucher=voucher,
                        scenario=opt.scenario,
                        row=row,
                        find_only=opt.find_only,
                        screenshot_dir=store.shots,
                        on_log=self.log,
                        stop_flag=self.stop_event,
                        pause_fn=self._wait_if_paused,
                    )
                    outcome, message = result.status, result.message
                    shot = str(result.screenshot or "")
                    erp_ref = result.erp_reference
                    if not shot and outcome not in {"SUCCESS", "FOUND"}:
                        shot = str(store.screenshot(f"{outcome}-{voucher}"))
                else:
                    self._run_steps(opt.scenario.steps, row, voucher_col)
                    outcome, message, shot, erp_ref = "SUCCESS", "", "", ""
                store.checkpoint(voucher=voucher, state=outcome, message=message)
                if outcome in {"SUCCESS", "FOUND"}:
                    ok += 1
                    miss_streak = 0
                else:
                    fail += 1
                    self.log(f"{outcome} {voucher}: {message}")
                    miss_streak = miss_streak + 1 if outcome == "NOT_FOUND" else 0
                excel_io.write_run_result(
                    result_path,
                    int(row["_excel_row"]),
                    outcome,
                    message,
                    1,
                    store.run_id,
                    shot,
                    erp_ref,
                )
                if miss_streak >= MAX_MISS_STREAK:
                    self.log(
                        f"{miss_streak} phieu lien tiep khong thay tren luoi. Dung lai de "
                        "khong chay hong ca danh sach. Kiem tra DIGINET dang mo dung tab "
                        "'Danh sach hoa don ban hang - D05F9300' va khong co man hinh khac de len."
                    )
                    break
                if "D05F3104 van mo" in message:
                    self.log(
                        "Man Chon kho D05F3104 dang de len luoi. Dung ca luot chay. "
                        "Bam Dong tren man Chon kho roi chay lai tu phieu bi fail."
                    )
                    break
            except InterruptedError:
                self.log("Dung giua chung.")
                excel_io.write_run_result(
                    result_path,
                    int(row["_excel_row"]),
                    "UNCERTAIN",
                    "Dung giua chung",
                    1,
                    store.run_id,
                    str(store.screenshot(f"stop-{voucher}")),
                )
                break
            except Exception as exc:
                fail += 1
                shot = str(store.screenshot(f"error-{voucher}"))
                self.log(f"FAILED {voucher}: {exc}")
                excel_io.write_run_result(
                    result_path, int(row["_excel_row"]), "FAILED", str(exc), 1, store.run_id, shot
                )
            time.sleep(max(opt.scenario.delay_ms, 50) / 1000)
        excel_io.close_results(result_path)
        self.log(f"Xong. OK={ok} | LOI={fail} | {store.root}")
        return ok, fail

    def _run_steps(self, steps: list[Step], row: dict[str, Any], voucher_col: str) -> None:
        for step in steps:
            self._wait_if_paused()
            value = self._fill(step.value, row)
            self.log(f"  - {step.action} {value} {step.note}".strip())
            if self.options.dry_run:
                if step.wait_ms:
                    time.sleep(min(step.wait_ms, 200) / 1000)
                continue
            self._do_step(step, value, row, voucher_col)
            if step.wait_ms and step.action != "wait":
                time.sleep(step.wait_ms / 1000)

    def _do_step(self, step: Step, value: str, row: dict[str, Any], voucher_col: str) -> None:
        win = self.win
        action = step.action
        if action == "focus":
            lemon3.focus(win)
        elif action == "wait":
            time.sleep((step.wait_ms or 300) / 1000)
        elif action == "keys":
            lemon3.send_keys(win, value or step.extra.get("keys") or "")
        elif action == "type":
            lemon3.type_text(win, value)
        elif action == "type_col":
            col = value or voucher_col
            lemon3.type_text(win, self._row_value(row, col))
        elif action == "enter":
            lemon3.send_keys(win, "{ENTER}")
        elif action == "tab":
            times = int(value or 1)
            lemon3.send_keys(win, "{TAB}" * max(times, 1))
        elif action == "alt":
            lemon3.send_keys(win, "%" + value.lstrip("%"))
        elif action == "click_xy":
            x_str, y_str = [p.strip() for p in value.replace(";", ",").split(",")[:2]]
            lemon3.relative_click(win, int(x_str), int(y_str))
        elif action == "click":
            extra = step.extra
            if "x" in extra and "y" in extra:
                lemon3.relative_click(win, int(extra["x"]), int(extra["y"]))
            elif value:
                ctrl = win.child_window(title=value)
                ctrl.click_input()
            else:
                raise RuntimeError("click can ten control hoac x,y")
        elif action == "pause":
            self.request_pause()
            self._wait_if_paused()
        elif action == "screenshot":
            self._screenshot(value or row.get("so_phieu") or "step")
        elif action == "wait_window":
            self.win = lemon3.wait_for_window(
                [value],
                timeout_s=max((step.wait_ms or 15000) / 1000, 1),
                backend=self.options.scenario.backend,
                stop_flag=self.stop_event,
            )
            lemon3.focus(self.win)
        elif action == "focus_window":
            self.win = lemon3.attach([value], backend=self.options.scenario.backend)
            lemon3.focus(self.win)
        elif action == "click_button":
            lemon3.click_button(value, self.win, timeout_s=8)
        elif action == "type_field":
            label = str(step.extra.get("field") or step.extra.get("label") or value)
            col = str(step.extra.get("from") or voucher_col)
            lemon3.type_in_field(self.win, label, self._row_value(row, col))
        else:
            raise RuntimeError(f"Hanh dong chua ho tro: {action}")

    def _screenshot(self, name: str) -> str | None:
        folder = Path(self.options.log_dir)
        folder.mkdir(parents=True, exist_ok=True)
        safe = re.sub(r"[^\w.-]+", "_", str(name))[:40]
        path = folder / f"{datetime.now().strftime('%H%M%S')}_{safe}.png"
        lemon3.grab_screen().save(path)
        self.log(f"  Anh: {path}")
        return str(path)
