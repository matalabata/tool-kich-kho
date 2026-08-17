from __future__ import annotations

import json
import sys
import threading
import time
from pathlib import Path
import tkinter as tk
from tkinter import filedialog, messagebox

import customtkinter as ctk

from lemon3_rpa import excel_io, lemon3
from lemon3_rpa.engine import RunOptions, Runner
from lemon3_rpa.scenario import (
    default_scenario,
    load_scenario,
    save_excel_template,
    save_yaml_template,
    update_yaml_automation,
    update_yaml_xy,
)

ROOT = Path(__file__).resolve().parent
SAMPLES = ROOT / "samples"
SCENARIOS = ROOT / "scenarios"
LOGS = ROOT / "logs"
LOCAL = ROOT / "config" / "local.json"


class App(ctk.CTk):
    def __init__(self) -> None:
        super().__init__()
        self.title("Lemon3 RPA")
        self.geometry("920x680")
        self.minsize(800, 580)
        ctk.set_appearance_mode("dark")
        ctk.set_default_color_theme("blue")

        self.runner: Runner | None = None
        self.worker: threading.Thread | None = None
        self._hotkey_off: threading.Event | None = None
        self._ensure_samples()
        self._build()

    def _ensure_samples(self) -> None:
        SAMPLES.mkdir(exist_ok=True)
        SCENARIOS.mkdir(exist_ok=True)
        LOGS.mkdir(exist_ok=True)
        sample_xlsx = SAMPLES / "danh_sach_phieu.xlsx"
        if not sample_xlsx.exists():
            excel_io.create_sample_workbook(sample_xlsx)
        yaml_path = SCENARIOS / "tim_phieu.yaml"
        xlsx_path = SCENARIOS / "tim_phieu.xlsx"
        if not yaml_path.exists():
            save_yaml_template(yaml_path)
        if not xlsx_path.exists():
            save_excel_template(xlsx_path)

    def _build(self) -> None:
        pad = {"padx": 12, "pady": 6}
        header = ctk.CTkLabel(
            self,
            text="Dieu khien Lemon3 theo kich ban Excel",
            font=ctk.CTkFont(size=20, weight="bold"),
        )
        header.pack(anchor="w", padx=16, pady=(16, 4))
        ctk.CTkLabel(
            self,
            text="Kich ban: loc so phieu -> xac minh luoi -> Ctrl+K -> kho 1000 -> Alt+T -> MNNKXB01 -> F11 Dien giai -> Alt+L -> Enter -> Alt+N. Khong doi kich thuoc DIGINET.",
            text_color="#9aa4b2",
        ).pack(anchor="w", padx=16)

        form = ctk.CTkFrame(self, fg_color="transparent")
        form.pack(fill="x", padx=12, pady=8)
        form.grid_columnconfigure(1, weight=1)

        self.excel_var = tk.StringVar(value=str(SAMPLES / "danh_sach_phieu.csv"))
        self.scenario_var = tk.StringVar(value=str(SCENARIOS / "xuat_kho.yaml"))
        self.title_var = tk.StringVar(value="DIGINET Desktop")
        self.column_var = tk.StringVar(value="SỐ PHIẾU")
        self.dry_var = tk.BooleanVar(value=False)
        self.xy_var = tk.StringVar(value=self._initial_xy())

        self._row(form, 0, "File Excel", self.excel_var, self._pick_excel)
        self._row(form, 1, "Kich ban", self.scenario_var, self._pick_scenario)

        opts = ctk.CTkFrame(form, fg_color="transparent")
        opts.grid(row=2, column=0, columnspan=3, sticky="ew", pady=4)
        ctk.CTkLabel(opts, text="Tieu de cua so").pack(side="left", padx=(0, 8))
        ctk.CTkEntry(opts, textvariable=self.title_var, width=140).pack(side="left")
        ctk.CTkLabel(opts, text="Cot so phieu").pack(side="left", padx=(16, 8))
        ctk.CTkEntry(opts, textvariable=self.column_var, width=120).pack(side="left")
        ctk.CTkCheckBox(opts, text="Chi in mo ta (khong bam DIGINET)", variable=self.dry_var).pack(
            side="left", padx=16
        )

        xy_row = ctk.CTkFrame(form, fg_color="transparent")
        xy_row.grid(row=3, column=0, columnspan=3, sticky="ew", pady=4)
        ctk.CTkLabel(xy_row, text="Toa do o loc So phieu", width=160, anchor="w").pack(side="left")
        ctk.CTkEntry(xy_row, textvariable=self.xy_var, width=120).pack(side="left", padx=8)
        ctk.CTkLabel(
            xy_row,
            text="Khong bat buoc. Chi dung neu o loc luoi khong nhan phim. Ghi luc cua so dang mo, khong can phong to.",
            text_color="#9aa4b2",
        ).pack(side="left", padx=8)

        config_row = ctk.CTkFrame(form, fg_color="transparent")
        config_row.grid(row=4, column=0, columnspan=3, sticky="ew", pady=4)
        ctk.CTkButton(
            config_row,
            text="Cai dat automation",
            command=self.open_automation_settings,
            width=160,
            fg_color="#6b4f9e",
        ).pack(side="left", padx=4)
        ctk.CTkLabel(
            config_row,
            text="Chinh tham so, timing va phim tat cua file YAML dang chon.",
            text_color="#9aa4b2",
        ).pack(side="left", padx=8)

        buttons = ctk.CTkFrame(self, fg_color="transparent")
        buttons.pack(fill="x", padx=12, pady=4)
        self.btn_inspect = ctk.CTkButton(buttons, text="Kiem tra Lemon3", command=self.inspect, width=140)
        self.btn_xy = ctk.CTkButton(buttons, text="Ghi toa do (3s)", command=self.capture_xy, width=140)
        self.btn_find = ctk.CTkButton(
            buttons, text="Kiem tra tim phieu", command=lambda: self.start(find_only=True), width=150
        )
        self.btn_run = ctk.CTkButton(buttons, text="Chay", command=self.start, width=100, fg_color="#1f6aa5")
        self.btn_pause = ctk.CTkButton(buttons, text="Tam dung", command=self.pause, width=100, state="disabled")
        self.btn_stop = ctk.CTkButton(
            buttons, text="Dung", command=self.stop, width=100, fg_color="#8b3a3a", state="disabled"
        )
        self.btn_screen = ctk.CTkButton(
            buttons, text="Tat man hinh", command=self.screen_off, width=120, fg_color="#3a3f4b"
        )
        for btn in (
            self.btn_inspect,
            self.btn_xy,
            self.btn_find,
            self.btn_run,
            self.btn_pause,
            self.btn_stop,
            self.btn_screen,
        ):
            btn.pack(side="left", padx=4)

        self.log_box = ctk.CTkTextbox(self, font=ctk.CTkFont(family="Consolas", size=13))
        self.log_box.pack(fill="both", expand=True, padx=16, pady=(8, 16))
        self.append_log("Tab D05F9300 de mo san. Tool khong tim/mo tab, chi dung cua so DIGINET dang co.")
        self.append_log("Tool khong phong to / thu nho cua so DIGINET.")
        self.append_log("'Kiem tra tim phieu' = nhap + xac minh luoi, KHONG Ctrl+K, KHONG Luu.")
        self.append_log("'Chi in mo ta' chi in buoc, khong bam DIGINET. Dung 'Kiem tra tim phieu' de test loc.")
        self.append_log("Ket qua ghi vao artifacts/runs/<id>/ — khong ghi de file Excel goc.")
        self.append_log("Dung khan cap: CTRL+SHIFT+Q, hoac hat chuot vao goc tren trai man hinh.")

    def _row(self, parent: ctk.CTkFrame, row: int, label: str, var: tk.StringVar, command) -> None:
        ctk.CTkLabel(parent, text=label, width=90, anchor="w").grid(row=row, column=0, sticky="w", padx=4, pady=4)
        ctk.CTkEntry(parent, textvariable=var).grid(row=row, column=1, sticky="ew", padx=4, pady=4)
        ctk.CTkButton(parent, text="Chon", width=70, command=command).grid(row=row, column=2, padx=4, pady=4)

    def open_automation_settings(self) -> None:
        scenario_path = Path(self.scenario_var.get().strip())
        if scenario_path.suffix.lower() not in {".yaml", ".yml"}:
            messagebox.showerror("Lemon3 RPA", "Hay chon kich ban YAML de chinh cai dat.")
            return
        try:
            scenario = load_scenario(scenario_path)
        except Exception as exc:
            messagebox.showerror("Lemon3 RPA", f"Khong doc duoc kich ban: {exc}")
            return

        old = getattr(self, "_settings_window", None)
        if old is not None and old.winfo_exists():
            old.focus()
            return

        win = ctk.CTkToplevel(self)
        self._settings_window = win
        win.title("Cai dat automation")
        win.geometry("700x650")
        win.minsize(620, 520)
        win.transient(self)
        win.grab_set()

        ctk.CTkLabel(
            win,
            text=f"Kich ban: {scenario_path.name}",
            font=ctk.CTkFont(size=18, weight="bold"),
        ).pack(anchor="w", padx=18, pady=(16, 2))
        ctk.CTkLabel(
            win,
            text="Timing tinh bang mili-giay. Gia tri nho hon chay nhanh hon, nhung may cham co the bo sot phan hoi.",
            text_color="#9aa4b2",
        ).pack(anchor="w", padx=18, pady=(0, 8))

        body = ctk.CTkScrollableFrame(win)
        body.pack(fill="both", expand=True, padx=14, pady=6)
        body.grid_columnconfigure(1, weight=1)

        values: dict[str, tk.StringVar] = {}
        row = 0

        def section(title: str) -> None:
            nonlocal row
            ctk.CTkLabel(
                body, text=title, font=ctk.CTkFont(size=15, weight="bold")
            ).grid(row=row, column=0, columnspan=2, sticky="w", padx=6, pady=(14, 4))
            row += 1

        def field(key: str, label: str, value: object, hint: str = "") -> None:
            nonlocal row
            var = tk.StringVar(value=str(value))
            values[key] = var
            ctk.CTkLabel(body, text=label, width=190, anchor="w").grid(
                row=row, column=0, sticky="w", padx=6, pady=4
            )
            holder = ctk.CTkFrame(body, fg_color="transparent")
            holder.grid(row=row, column=1, sticky="ew", padx=6, pady=4)
            holder.grid_columnconfigure(0, weight=1)
            ctk.CTkEntry(holder, textvariable=var).grid(row=0, column=0, sticky="ew")
            if hint:
                ctk.CTkLabel(holder, text=hint, text_color="#9aa4b2").grid(
                    row=1, column=0, sticky="w", pady=(2, 0)
                )
            row += 1

        section("An toan")
        field(
            "stop_hotkey",
            "Phim dung khan cap",
            scenario.stop_hotkey,
            "Vi du: ctrl+shift+q, f12, pause. Bam duoc ca khi bot dang gianh chuot.",
        )

        section("Timing")
        field("after_type_ms", "Search toi da (ms)", scenario.after_type_ms, "Thay phieu som thi chay tiep ngay.")
        field("delay_ms", "Cho du phong chung (ms)", scenario.delay_ms, "Dung o cac buoc ERP chua co tin hieu doc duoc.")
        field(
            "operation_ms",
            "Nhip dropdown D05F3105 (ms)",
            scenario.operation_ms,
            "Cho giua xo dropdown, chon dong va Enter. Giam de bot chay nhanh hon.",
        )

        section("Tham so ERP")
        field("warehouse_code", "Ma kho", scenario.warehouse_code)
        field("warehouse_name", "Ten kho", scenario.warehouse_name)
        field("operation_code", "Ma loai nghiep vu", scenario.operation_code)
        field("operation_row", "Dong nghiep vu", scenario.operation_row, "Dong dau tien = 1.")

        section("Phim tat (cu phap pywinauto)")
        field("key_row_down", "Chon dong phieu", scenario.key_row_down)
        field("key_open_dropdown", "Mo dropdown", scenario.key_open_dropdown)
        field("key_continue", "Tiep tuc", scenario.key_continue)
        field("key_goto_description", "Den Dien giai", scenario.key_goto_description)
        field("key_save", "Luu", scenario.key_save)
        field("key_close", "Dong", scenario.key_close)
        field("key_yes", "Dong y", scenario.key_yes)
        field("key_confirm", "Xac nhan / OK", scenario.key_confirm)

        status = tk.StringVar(value="")
        ctk.CTkLabel(win, textvariable=status, text_color="#8bcf9b").pack(
            anchor="w", padx=18, pady=(2, 0)
        )

        def load_defaults() -> None:
            defaults = default_scenario()
            default_values = {
                "after_type_ms": defaults.after_type_ms,
                "delay_ms": defaults.delay_ms,
                "operation_ms": defaults.operation_ms,
                "stop_hotkey": defaults.stop_hotkey,
                "warehouse_code": defaults.warehouse_code,
                "warehouse_name": defaults.warehouse_name,
                "operation_code": defaults.operation_code,
                "operation_row": defaults.operation_row,
                "key_row_down": defaults.key_row_down,
                "key_open_dropdown": defaults.key_open_dropdown,
                "key_continue": defaults.key_continue,
                "key_goto_description": defaults.key_goto_description,
                "key_save": defaults.key_save,
                "key_close": defaults.key_close,
                "key_yes": defaults.key_yes,
                "key_confirm": defaults.key_confirm,
            }
            for key, value in default_values.items():
                values[key].set(str(value))
            status.set("Da nap gia tri mac dinh. Bam Luu de ap dung.")

        def save() -> None:
            try:
                delay_ms = int(values["delay_ms"].get())
                after_type_ms = int(values["after_type_ms"].get())
                operation_ms = int(values["operation_ms"].get())
                operation_row = int(values["operation_row"].get())
                if not 0 <= delay_ms <= 60000:
                    raise ValueError("Cho du phong chung phai tu 0 den 60000 ms.")
                if not 200 <= after_type_ms <= 60000:
                    raise ValueError("Search toi da phai tu 200 den 60000 ms.")
                if not 0 <= operation_ms <= 60000:
                    raise ValueError("Nhip dropdown phai tu 0 den 60000 ms.")
                if not 1 <= operation_row <= 100:
                    raise ValueError("Dong nghiep vu phai tu 1 den 100.")
                hotkey = values["stop_hotkey"].get().strip()
                if not lemon3.parse_hotkey(hotkey):
                    raise ValueError(f"Phim dung khan cap '{hotkey}' khong hop le. Vi du: ctrl+shift+q")
                payload = {key: var.get().strip() for key, var in values.items()}
                payload.update(
                    delay_ms=delay_ms,
                    after_type_ms=after_type_ms,
                    operation_ms=operation_ms,
                    operation_row=operation_row,
                )
                required = (
                    "warehouse_code",
                    "operation_code",
                    "key_row_down",
                    "key_open_dropdown",
                    "key_continue",
                    "key_goto_description",
                    "key_save",
                    "key_close",
                    "key_yes",
                    "key_confirm",
                )
                if any(not str(payload[key]).strip() for key in required):
                    raise ValueError("Ma kho, nghiep vu va cac phim tat khong duoc de trong.")
                update_yaml_automation(scenario_path, payload)
                # Doc lai de bat loi YAML ngay luc luu, khong doi den khi bam Chay.
                load_scenario(scenario_path)
            except Exception as exc:
                messagebox.showerror("Lemon3 RPA", str(exc), parent=win)
                return
            self.append_log(f"Da luu cai dat automation: {scenario_path}")
            win.destroy()

        actions = ctk.CTkFrame(win, fg_color="transparent")
        actions.pack(fill="x", padx=14, pady=(6, 14))
        ctk.CTkButton(actions, text="Mac dinh", command=load_defaults, width=110, fg_color="#666666").pack(
            side="left", padx=4
        )
        ctk.CTkButton(actions, text="Huy", command=win.destroy, width=90, fg_color="#555555").pack(
            side="right", padx=4
        )
        ctk.CTkButton(actions, text="Luu", command=save, width=110).pack(side="right", padx=4)

    def _pick_excel(self) -> None:
        path = filedialog.askopenfilename(
            title="Chon file Excel du lieu",
            filetypes=[("Excel / CSV", "*.xlsx *.xlsm *.csv"), ("Tat ca", "*.*")],
        )
        if path:
            self.excel_var.set(path)

    def _pick_scenario(self) -> None:
        path = filedialog.askopenfilename(
            title="Chon kich ban",
            filetypes=[("Kich ban", "*.yaml *.yml *.xlsx"), ("Tat ca", "*.*")],
        )
        if path:
            self.scenario_var.set(path)
            try:
                loaded = load_scenario(path)
                if loaded.so_phieu_xy:
                    self.xy_var.set(loaded.so_phieu_xy)
            except Exception:
                pass

    def append_log(self, message: str) -> None:
        self.log_box.insert("end", message + "\n")
        self.log_box.see("end")

    def inspect(self) -> None:
        typed = self.title_var.get().strip()
        titles = [t for t in (typed, "DIGINET Desktop", "LEMON3-ERP", "D00F3000") if t]
        self.append_log("--- Cua so ERP ---")
        found = False
        try:
            windows = lemon3.list_windows("win32")
        except Exception as exc:
            self.append_log(f"loi {exc}")
            return
        erp = [
            w
            for w in windows
            if any(k in w.title.lower() for k in ("diginet", "lemon3-erp", "d00f", "d05f"))
            and "lemon3 rpa" not in w.title.lower()
        ]
        if erp:
            found = True
        for info in (erp or windows[:15])[:20]:
            mark = "  <== ERP" if info in erp else ""
            self.append_log(f"{info.title}{mark}")
        if not found:
            self.append_log("Chua thay cua so DIGINET Desktop. De DIGINET mo san roi bam lai.")
            return
        try:
            win = lemon3.attach(titles)
            lemon3.focus(win)
            self.append_log(f"Da gan cua so: {win.window_text()}")
            self.append_log("Khong quet luoi hang ngan dong - tranh treo ERP.")
        except Exception as exc:
            self.append_log(str(exc))

    def capture_xy(self) -> None:
        titles = [self.title_var.get().strip() or "LEMON3"]
        try:
            win = lemon3.attach(titles)
        except Exception as exc:
            messagebox.showerror("Lemon3 RPA", str(exc))
            return
        self.append_log("Dua chuot vao o loc DUOI cot So phieu tren luoi. Ghi sau 3 giay...")
        self.update()
        for i in (3, 2, 1):
            self.append_log(f"  {i}...")
            self.update()
            time.sleep(1)
        try:
            x, y = lemon3.capture_relative(win)
            base = lemon3.window_size_text(win)
            self.append_log(f"Da luu toa do o loc: {x},{y} (cua so {base}, {lemon3.monitor_summary()})")
            self.append_log("Doi do phan giai van chay duoc: toa do se tu quy doi theo kich thuoc cua so.")
            left, top, _w, _h = lemon3.window_rect(win)
            if not lemon3.on_primary_screen(left + x, top + y):
                self.append_log(
                    "CANH BAO: o loc dang nam ngoai man hinh chinh. Anh chup se den va bot doc rong. "
                    "Keo DIGINET ve man hinh chinh roi ghi toa do lai."
                )
            self.xy_var.set(f"{x},{y}")
            self._save_xy(f"{x},{y}", base)
            self.clipboard_clear()
            self.clipboard_append(f"{x},{y}")
        except Exception as exc:
            self.append_log(f"Khong ghi duoc toa do: {exc}")

    def _start_hotkey_watch(self, spec: str) -> None:
        """Bot gianh chuot nen khong bam duoc nut Dung. Canh phim nong o luong rieng."""
        self._stop_hotkey_watch()
        codes = lemon3.parse_hotkey(spec)
        if not codes:
            self.append_log(f"Phim nong '{spec}' khong hop le, bo qua.")
            return
        off = threading.Event()
        self._hotkey_off = off

        def watch() -> None:
            while not off.wait(0.05):
                if lemon3.hotkey_is_down(codes):
                    off.set()
                    self.after(0, self._hotkey_stop)
                    return

        threading.Thread(target=watch, daemon=True).start()
        self.append_log(f"Phim dung khan cap: {spec.upper()} (bam tu bat ky dau)")

    def _stop_hotkey_watch(self) -> None:
        if self._hotkey_off is not None:
            self._hotkey_off.set()
            self._hotkey_off = None

    def _hotkey_stop(self) -> None:
        self.append_log("Da bam phim dung khan cap.")
        self.stop()

    def screen_off(self) -> None:
        self.append_log("Tat man hinh sau 2 giay. Dung bam Win+L: khoa may la bot doc anh den va hong het.")
        self.append_log("Cham chuot/phim se bat man lai. Bot dang chay cung tu bat lai khi no click.")
        self.after(2000, self._do_screen_off)

    def _do_screen_off(self) -> None:
        if not lemon3.monitor_off():
            self.append_log("May khong nhan lenh tat man hinh. Dung nut nguon tren man hinh.")

    def start(self, find_only: bool = False) -> None:
        if self.worker and self.worker.is_alive():
            if self.runner:
                self.runner.request_continue()
                self.append_log("Tiep tuc.")
                self.btn_run.configure(state="disabled", text="Chay")
            return
        excel_path = self.excel_var.get().strip()
        scenario_path = self.scenario_var.get().strip()
        if not Path(excel_path).exists():
            messagebox.showerror("Lemon3 RPA", "Chua chon file Excel hop le.")
            return
        try:
            scenario = load_scenario(scenario_path)
        except Exception as exc:
            messagebox.showerror("Lemon3 RPA", f"Loi kich ban: {exc}")
            return
        gui_xy = self.xy_var.get().strip()
        yaml_xy = scenario.so_phieu_xy.strip()
        if gui_xy:
            scenario.so_phieu_xy = gui_xy
            if gui_xy != yaml_xy:
                self._save_xy(gui_xy)
        elif yaml_xy:
            self.xy_var.set(yaml_xy)
        titles = [t.strip() for t in self.title_var.get().split(";") if t.strip()]
        for extra in ("DIGINET Desktop", "LEMON3-ERP", "D00F3000"):
            if extra not in titles:
                titles.append(extra)
        titles = [t for t in titles if "D05F9300" not in t.upper()]
        titles = titles or scenario.title_contains
        options = RunOptions(
            excel_path=excel_path,
            scenario=scenario,
            voucher_column=self.column_var.get().strip() or scenario.voucher_column,
            title_contains=titles,
            dry_run=bool(self.dry_var.get()) and not find_only,
            find_only=find_only,
            log_dir=str(LOGS),
        )
        self.runner = Runner(options, on_log=lambda m: self.after(0, self.append_log, m))
        if lemon3.keep_awake(True):
            self.append_log("Da chan may ngu trong luc chay. Man hinh van duoc phep tu tat.")
        self._start_hotkey_watch(scenario.stop_hotkey)
        self.btn_run.configure(state="disabled")
        self.btn_find.configure(state="disabled")
        self.btn_pause.configure(state="normal")
        self.btn_stop.configure(state="normal")
        self.worker = threading.Thread(target=self._run_safe, daemon=True)
        self.worker.start()

    def _run_safe(self) -> None:
        try:
            assert self.runner is not None
            self.runner.run()
        except Exception as exc:
            self.after(0, self.append_log, f"LOI: {exc}")
        finally:
            self.after(0, self._reset_buttons)

    def _reset_buttons(self) -> None:
        lemon3.keep_awake(False)
        self._stop_hotkey_watch()
        self.btn_run.configure(state="normal", text="Chay")
        self.btn_find.configure(state="normal")
        self.btn_pause.configure(state="disabled")
        self.btn_stop.configure(state="disabled")

    def pause(self) -> None:
        if self.runner:
            self.runner.request_pause()
            self.btn_run.configure(state="normal", text="Tiep tuc")

    def stop(self) -> None:
        if self.runner:
            self.runner.request_stop()
        self.append_log("Dang dung...")

    def _initial_xy(self) -> str:
        try:
            yaml_xy = load_scenario(SCENARIOS / "xuat_kho.yaml").so_phieu_xy.strip()
            if yaml_xy:
                return yaml_xy
        except Exception:
            pass
        return str(self._load_local().get("so_phieu_xy") or "")

    def _load_local(self) -> dict:
        try:
            if LOCAL.exists():
                return json.loads(LOCAL.read_text(encoding="utf-8"))
        except Exception:
            pass
        return {}

    def _save_xy(self, xy: str, base_size: str = "") -> None:
        LOCAL.parent.mkdir(parents=True, exist_ok=True)
        data = self._load_local()
        data["so_phieu_xy"] = xy
        if base_size:
            data["so_phieu_base"] = base_size
        LOCAL.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        try:
            update_yaml_xy(self.scenario_var.get().strip(), xy, base_size)
        except Exception:
            pass

    def _save_local(self) -> None:
        self._save_xy(self.xy_var.get().strip())


def _redirect_output_to_log() -> None:
    """Chay bang pythonw thi stdout/stderr la None, moi lenh print se lam app chet im."""
    if sys.stdout is not None and sys.stderr is not None:
        return
    LOGS.mkdir(parents=True, exist_ok=True)
    stream = open(LOGS / "app.log", "a", encoding="utf-8", buffering=1)
    if sys.stdout is None:
        sys.stdout = stream
    if sys.stderr is None:
        sys.stderr = stream


def main() -> None:
    app = App()
    app.mainloop()


if __name__ == "__main__":
    _redirect_output_to_log()
    try:
        main()
    except Exception:
        import traceback

        detail = traceback.format_exc()
        try:
            LOGS.mkdir(parents=True, exist_ok=True)
            (LOGS / "app-error.log").write_text(detail, encoding="utf-8")
        except Exception:
            pass
        try:
            print(detail)
        except Exception:
            pass
        # Khong con console de doc loi, nen phai bao bang hop thoai.
        try:
            messagebox.showerror("Lemon3 RPA", f"Loi khi mo app.\nXem logs\\app-error.log\n\n{detail[-700:]}")
        except Exception:
            pass
