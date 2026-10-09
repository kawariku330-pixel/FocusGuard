import os
import sys
import time
import socket
import ctypes
import threading
from datetime import datetime, date, timedelta
import tkinter as tk
from tkinter import ttk, messagebox, simpledialog
from PIL import Image, ImageDraw, ImageTk

from config_manager import ConfigManager
from blocker import Blocker, normalize_domain, expand_domains

IPC_PORT = 18990

# Generate dynamic tray icon images using Pillow
def create_icon_image(is_blocked=False):
    width = 64
    height = 64
    image = Image.new('RGBA', (width, height), (0, 0, 0, 0))
    draw = ImageDraw.Draw(image)

    # Shield polygon
    shield_color = (220, 53, 69, 255) if is_blocked else (40, 167, 69, 255)
    border_color = (180, 40, 50, 255) if is_blocked else (30, 130, 50, 255)

    points = [
        (32, 4),
        (56, 14),
        (54, 42),
        (32, 60),
        (10, 42),
        (8, 14)
    ]
    draw.polygon(points, fill=shield_color, outline=border_color, width=3)

    if is_blocked:
        # Cross / X
        draw.line((22, 22, 42, 42), fill=(255, 255, 255, 255), width=5)
        draw.line((22, 42, 42, 22), fill=(255, 255, 255, 255), width=5)
    else:
        # Checkmark
        draw.line((18, 32, 28, 44), fill=(255, 255, 255, 255), width=5)
        draw.line((28, 44, 46, 20), fill=(255, 255, 255, 255), width=5)

    return image

class FocusGuardApp:
    def __init__(self, root):
        self.root = root
        self.root.title("FocusGuard - 特定サイト利用制限")
        self.root.geometry("640x560")
        self.root.minsize(580, 500)

        # Apply icon to window
        self.icon_active = create_icon_image(is_blocked=True)
        self.icon_inactive = create_icon_image(is_blocked=False)

        self.cm = ConfigManager()
        self.blocker = Blocker()

        self.running = True
        self.current_status_text = "待機中"
        self.is_currently_blocked = False

        self._setup_ui()
        self._setup_tray()

        # Handle window close (minimize to tray)
        self.root.protocol("WM_DELETE_WINDOW", self.hide_window)

        # Start IPC server to allow subsequent launches to bring window to front
        self._start_ipc_server()

        # Start monitoring background thread
        self.monitor_thread = threading.Thread(target=self._monitor_loop, daemon=True)
        self.monitor_thread.start()

    def _start_ipc_server(self):
        def _ipc_worker():
            try:
                server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
                bound = False
                for _ in range(5):
                    try:
                        server.bind(("127.0.0.1", IPC_PORT))
                        bound = True
                        break
                    except Exception:
                        time.sleep(0.5)
                if not bound:
                    print("Could not bind IPC port, existing instance may be active.")
                    return

                server.listen(5)
                while self.running:
                    try:
                        client, _ = server.accept()
                        data = client.recv(1024)
                        if b"SHOW" in data or b"PING" in data:
                            self.show_window()
                            client.sendall(b"OK\n")
                        client.close()
                    except Exception:
                        pass
            except Exception as e:
                print(f"IPC server error: {e}")
        threading.Thread(target=_ipc_worker, daemon=True).start()

    def _setup_ui(self):
        style = ttk.Style()
        try:
            if "vista" in style.theme_names():
                style.theme_use("vista")
            elif "xpnative" in style.theme_names():
                style.theme_use("xpnative")
            elif "winnative" in style.theme_names():
                style.theme_use("winnative")
        except Exception:
            pass

        # Configure checkmark (✓) for all checkboxes
        self._setup_checkbox_style(style)

        notebook = ttk.Notebook(self.root)
        notebook.pack(fill="both", expand=True, padx=10, pady=10)

        # Tabs
        self.tab_home = ttk.Frame(notebook)
        self.tab_sites = ttk.Frame(notebook)
        self.tab_schedule = ttk.Frame(notebook)
        self.tab_settings = ttk.Frame(notebook)

        notebook.add(self.tab_home, text=" 🛡️ ホーム ")
        notebook.add(self.tab_sites, text=" 🌐 対象サイト ")
        notebook.add(self.tab_schedule, text=" ⏱️ スケジュール・タイマー ")
        notebook.add(self.tab_settings, text=" ⚙️ 設定・セキュリティ ")

        self._build_home_tab()
        self._build_sites_tab()
        self._build_schedule_tab()
        self._build_settings_tab()

    def _setup_checkbox_style(self, style):
        try:
            box_size = 18
            pad_r = 6
            w, h = box_size + pad_r, box_size

            def make_img(fill, outline, checked=False, ck_color='#ffffff'):
                im = Image.new('RGBA', (w, h), (0, 0, 0, 0))
                d = ImageDraw.Draw(im)
                d.rounded_rectangle([1, 1, box_size - 2, box_size - 2], radius=3, fill=fill, outline=outline, width=1)
                if checked:
                    # Draw checkmark ✓
                    d.line([(4, 9), (7, 13), (14, 5)], fill=ck_color, width=2)
                    d.ellipse([6, 12, 8, 14], fill=ck_color)
                return ImageTk.PhotoImage(im)

            un = make_img('#ffffff', '#737373', False)
            un_h = make_img('#f5f5f5', '#1976d2', False)
            un_d = make_img('#f0f0f0', '#cccccc', False)

            ck = make_img('#1976d2', '#1565c0', True, '#ffffff')
            ck_h = make_img('#1565c0', '#0d47a1', True, '#ffffff')
            ck_d = make_img('#b0bec5', '#90a4ae', True, '#ffffff')

            self._cb_images = (un, un_h, un_d, ck, ck_h, ck_d)

            style.element_create('Custom.indicator', 'image', un,
                                 ('disabled', 'selected', ck_d),
                                 ('disabled', un_d),
                                 ('selected', 'active', ck_h),
                                 ('selected', ck),
                                 ('active', un_h))

            style.layout('TCheckbutton', [
                ('Checkbutton.padding', {'sticky': 'nswe', 'children': [
                    ('Custom.indicator', {'side': 'left', 'sticky': ''}),
                    ('Checkbutton.focus', {'side': 'left', 'sticky': 'w', 'children': [
                        ('Checkbutton.label', {'sticky': 'nswe'})
                    ]})
                ]})
            ])
        except Exception as e:
            print(f"Failed to setup custom checkbox style: {e}")

    # --- PASSWORD & VALIDATION HELPERS ---
    def _prompt_password(self, prompt="設定を変更するにはパスワードを入力してください:"):
        if not self.cm.has_password():
            return True
        pwd = simpledialog.askstring("認証", prompt, show="*")
        if pwd is None:
            return False
        if not self.cm.check_password(pwd):
            messagebox.showerror("エラー", "パスワードが正しくありません。")
            return False
        return True

    def _validate_time_str(self, time_str):
        try:
            datetime.strptime(time_str.strip(), "%H:%M")
            return True
        except ValueError:
            return False

    def _sync_schedule_ui_from_config(self):
        sched = self.cm.config.get("schedule", {})
        self.var_sched_enabled.set(sched.get("enabled", True))
        self.entry_start_time.delete(0, tk.END)
        self.entry_start_time.insert(0, sched.get("start_time", "09:00"))
        self.entry_end_time.delete(0, tk.END)
        self.entry_end_time.insert(0, sched.get("end_time", "18:00"))
        active_days = sched.get("days", [0, 1, 2, 3, 4])
        for i, v in enumerate(self.day_vars):
            v.set(i in active_days)

    def _update_password_status_ui(self):
        if hasattr(self, "lbl_pass_status"):
            if self.cm.has_password():
                self.lbl_pass_status.config(
                    text="🔒 パスワード保護: 有効（時間帯制限の変更やサイト削除が保護されています）",
                    fg="#28a745"
                )
            else:
                self.lbl_pass_status.config(
                    text="🔓 パスワード保護: 未設定（誰でも設定を変更できます）",
                    fg="#6c757d"
                )

    # --- TAB 1: HOME ---
    def _build_home_tab(self):
        frame = ttk.Frame(self.tab_home, padding=15)
        frame.pack(fill="both", expand=True)

        # Status Banner
        self.status_card = tk.Frame(frame, bg="#f8f9fa", bd=1, relief="solid", padx=15, pady=15)
        self.status_card.pack(fill="x", pady=(0, 15))

        self.lbl_status_icon = tk.Label(self.status_card, text="🟢", font=("Segoe UI", 32), bg="#f8f9fa")
        self.lbl_status_icon.pack(side="left", padx=(0, 15))

        status_text_frame = tk.Frame(self.status_card, bg="#f8f9fa")
        status_text_frame.pack(side="left", fill="both", expand=True)

        self.lbl_status_title = tk.Label(status_text_frame, text="現在: アクセス許可中", font=("Segoe UI", 16, "bold"), bg="#f8f9fa", fg="#28a745")
        self.lbl_status_title.pack(anchor="w")

        self.lbl_status_detail = tk.Label(status_text_frame, text="スケジュール時間外です", font=("Segoe UI", 10), bg="#f8f9fa", fg="#6c757d")
        self.lbl_status_detail.pack(anchor="w", pady=(4, 0))

        # Quick Focus Box
        qf_box = ttk.LabelFrame(frame, text="⚡ クイック集中モード（即時ブロック）", padding=15)
        qf_box.pack(fill="x", pady=10)

        qf_desc = ttk.Label(qf_box, text="指定した時間だけ、スケジュールに関わらず直ちにブロックを開始します。")
        qf_desc.pack(anchor="w", pady=(0, 10))

        btn_row = ttk.Frame(qf_box)
        btn_row.pack(fill="x")

        ttk.Button(btn_row, text="25分 集中開始", command=lambda: self.start_quick_focus(25)).pack(side="left", padx=4)
        ttk.Button(btn_row, text="50分 集中開始", command=lambda: self.start_quick_focus(50)).pack(side="left", padx=4)
        ttk.Button(btn_row, text="集中モード終了", command=self.stop_quick_focus).pack(side="left", padx=4)

        # Manual Master Toggle
        master_box = ttk.LabelFrame(frame, text="🛡️ 全体制御", padding=15)
        master_box.pack(fill="x", pady=10)

        self.var_master_enabled = tk.BooleanVar(value=self.cm.config.get("enabled", True))
        chk_master = ttk.Checkbutton(master_box, text="FocusGuard 保護機能を有効化する（OFFにすると全制限を解除）", 
                                     variable=self.var_master_enabled, command=self._on_master_toggle)
        chk_master.pack(anchor="w")

        # Today's Summary
        today_box = ttk.LabelFrame(frame, text="📊 本日の利用状況", padding=15)
        today_box.pack(fill="x", pady=10)

        self.lbl_today_summary = ttk.Label(today_box, text="読み込み中...", font=("Segoe UI", 10))
        self.lbl_today_summary.pack(anchor="w")

    # --- TAB 2: SITES ---
    def _build_sites_tab(self):
        frame = ttk.Frame(self.tab_sites, padding=15)
        frame.pack(fill="both", expand=True)

        desc = ttk.Label(frame, text="ブロックするWebサイトのドメイン（例: x.com, youtube.com）を指定します。\nx.com を指定すると、twitter.com や関連サブドメインも自動的に網羅されます。\n※ サイトの追加は自由に行えますが、削除・初期化にはパスワードが必要です。")
        desc.pack(anchor="w", pady=(0, 10))

        # List frame
        list_frame = ttk.Frame(frame)
        list_frame.pack(fill="both", expand=True)

        self.site_listbox = tk.Listbox(list_frame, font=("Segoe UI", 11), selectmode="single")
        self.site_listbox.pack(side="left", fill="both", expand=True)

        scrollbar = ttk.Scrollbar(list_frame, orient="vertical", command=self.site_listbox.yview)
        scrollbar.pack(side="right", fill="y")
        self.site_listbox.config(yscrollcommand=scrollbar.set)

        self._refresh_site_list()

        # Input and Buttons
        input_frame = ttk.Frame(frame)
        input_frame.pack(fill="x", pady=(10, 0))

        self.entry_new_site = ttk.Entry(input_frame, font=("Segoe UI", 10))
        self.entry_new_site.pack(side="left", fill="x", expand=True, padx=(0, 8))
        self.entry_new_site.bind("<Return>", lambda e: self._add_site())

        ttk.Button(input_frame, text="サイト追加", command=self._add_site).pack(side="left", padx=4)
        ttk.Button(input_frame, text="選択削除", command=self._remove_site).pack(side="left", padx=4)
        ttk.Button(input_frame, text="初期設定に戻す", command=self._reset_default_sites).pack(side="left", padx=4)

    def _refresh_site_list(self):
        self.site_listbox.delete(0, tk.END)
        for s in self.cm.config.get("blocked_sites", []):
            self.site_listbox.insert(tk.END, f"  🚫  {s}")

    def _add_site(self):
        val = self.entry_new_site.get().strip()
        if not val:
            return
        dom = normalize_domain(val)
        if not dom:
            messagebox.showerror("エラー", "正しいURLまたはドメイン名を入力してください。")
            return
        sites = self.cm.config.get("blocked_sites", [])
        if dom not in sites:
            sites.append(dom)
            self.cm.save()
            self._refresh_site_list()
            self.entry_new_site.delete(0, tk.END)
            self._check_and_update_block_state()

    def _remove_site(self):
        sel = self.site_listbox.curselection()
        if not sel:
            return
        idx = sel[0]
        sites = self.cm.config.get("blocked_sites", [])
        if 0 <= idx < len(sites):
            target_site = sites[idx]
            if self.cm.has_password():
                if not self._prompt_password(f"「{target_site}」をブロック対象から削除するにはパスワードを入力してください:"):
                    return
            del sites[idx]
            self.cm.save()
            self._refresh_site_list()
            self._check_and_update_block_state()
            messagebox.showinfo("成功", f"「{target_site}」をブロック対象から削除しました。")

    def _reset_default_sites(self):
        if self.cm.has_password():
            if not self._prompt_password("ブロック対象サイトを初期設定に戻すにはパスワードを入力してください:"):
                return
        if messagebox.askyesno("確認", "ブロック対象サイトを初期設定（X / Twitter）に戻しますか？"):
            self.cm.config["blocked_sites"] = ["x.com", "twitter.com", "api.x.com", "api.twitter.com"]
            self.cm.save()
            self._refresh_site_list()
            self._check_and_update_block_state()
            messagebox.showinfo("成功", "初期設定に戻しました。")

    # --- TAB 3: SCHEDULE & TIMER ---
    def _build_schedule_tab(self):
        frame = ttk.Frame(self.tab_schedule, padding=15)
        frame.pack(fill="both", expand=True)

        # Schedule Section
        sched_box = ttk.LabelFrame(frame, text="⏰ 時間帯制限（スケジュール）", padding=15)
        sched_box.pack(fill="x", pady=5)

        ttk.Label(sched_box, text="※ パスワード設定時は、時間帯制限の変更（ON/OFF・時間・曜日）にパスワードが必要です。", font=("Segoe UI", 9), foreground="#555555").pack(anchor="w", pady=(0, 6))

        self.var_sched_enabled = tk.BooleanVar(value=self.cm.config["schedule"].get("enabled", True))
        chk_sched = ttk.Checkbutton(sched_box, text="時間帯制限を有効にする", variable=self.var_sched_enabled, command=self._on_sched_toggle)
        chk_sched.pack(anchor="w", pady=(0, 8))

        time_row = ttk.Frame(sched_box)
        time_row.pack(fill="x", pady=4)

        ttk.Label(time_row, text="開始時間 (例 09:00):").pack(side="left", padx=(0, 5))
        self.entry_start_time = ttk.Entry(time_row, width=8)
        self.entry_start_time.insert(0, self.cm.config["schedule"].get("start_time", "09:00"))
        self.entry_start_time.pack(side="left", padx=(0, 15))

        ttk.Label(time_row, text="終了時間 (例 18:00):").pack(side="left", padx=(0, 5))
        self.entry_end_time = ttk.Entry(time_row, width=8)
        self.entry_end_time.insert(0, self.cm.config["schedule"].get("end_time", "18:00"))
        self.entry_end_time.pack(side="left", padx=(0, 15))

        ttk.Button(time_row, text="設定を保存", command=self._save_schedule_config).pack(side="left")

        # Presets
        preset_row = ttk.Frame(sched_box)
        preset_row.pack(fill="x", pady=(8, 0))
        ttk.Label(preset_row, text="プリセット:").pack(side="left", padx=(0, 5))
        ttk.Button(preset_row, text="日中・仕事中 (09:00〜18:00)", command=lambda: self._set_preset("09:00", "18:00")).pack(side="left", padx=3)
        ttk.Button(preset_row, text="夜間・就寝前 (22:00〜07:00)", command=lambda: self._set_preset("22:00", "07:00")).pack(side="left", padx=3)

        # Days of week
        days_box = ttk.Frame(sched_box)
        days_box.pack(fill="x", pady=(10, 0))
        ttk.Label(days_box, text="適用曜日:").pack(side="left", padx=(0, 8))

        day_names = ["月", "火", "水", "木", "金", "土", "日"]
        self.day_vars = []
        active_days = self.cm.config["schedule"].get("days", [0, 1, 2, 3, 4])
        for i, name in enumerate(day_names):
            v = tk.BooleanVar(value=(i in active_days))
            self.day_vars.append(v)
            ttk.Checkbutton(days_box, text=name, variable=v, command=lambda idx=i: self._on_day_toggle(idx)).pack(side="left", padx=3)

        # Daily Timer Limit Section
        timer_box = ttk.LabelFrame(frame, text="⏳ 1日の利用時間上限（タイマー制限）", padding=15)
        timer_box.pack(fill="x", pady=10)

        self.var_timer_enabled = tk.BooleanVar(value=self.cm.config["timer"].get("enabled", False))
        chk_timer = ttk.Checkbutton(timer_box, text="1日の利用時間上限を有効にする（指定時間を使用したら当日はブロック）", 
                                    variable=self.var_timer_enabled, command=self._on_timer_toggle)
        chk_timer.pack(anchor="w", pady=(0, 8))

        timer_row = ttk.Frame(timer_box)
        timer_row.pack(fill="x")

        ttk.Label(timer_row, text="1日の閲覧上限（分）:").pack(side="left", padx=(0, 5))
        self.entry_timer_limit = ttk.Entry(timer_row, width=8)
        self.entry_timer_limit.insert(0, str(self.cm.config["timer"].get("daily_limit_minutes", 30)))
        self.entry_timer_limit.pack(side="left", padx=(0, 15))

        ttk.Button(timer_row, text="保存", command=self._save_timer_config).pack(side="left", padx=4)
        ttk.Button(timer_row, text="本日の利用時間をリセット", command=self._reset_today_timer).pack(side="left", padx=4)

    def _on_sched_toggle(self):
        if self.cm.has_password():
            if not self._prompt_password("時間帯制限を切り替えるにはパスワードを入力してください:"):
                self.var_sched_enabled.set(self.cm.config["schedule"].get("enabled", True))
                return
        self.cm.config["schedule"]["enabled"] = self.var_sched_enabled.get()
        self.cm.save()

    def _on_day_toggle(self, idx):
        if self.cm.has_password():
            if not self._prompt_password("適用曜日を変更するにはパスワードを入力してください:"):
                saved_days = self.cm.config["schedule"].get("days", [0, 1, 2, 3, 4])
                self.day_vars[idx].set(idx in saved_days)
                return
        self.cm.config["schedule"]["days"] = [i for i, v in enumerate(self.day_vars) if v.get()]
        self.cm.save()

    def _set_preset(self, start, end):
        if self.cm.has_password():
            if not self._prompt_password("プリセットを適用するにはパスワードを入力してください:"):
                return
        self.entry_start_time.delete(0, tk.END)
        self.entry_start_time.insert(0, start)
        self.entry_end_time.delete(0, tk.END)
        self.entry_end_time.insert(0, end)
        self.cm.config["schedule"]["start_time"] = start
        self.cm.config["schedule"]["end_time"] = end
        self.cm.save()
        messagebox.showinfo("成功", f"プリセット ({start}〜{end}) を適用・保存しました。")

    def _save_schedule_config(self):
        s = self.entry_start_time.get().strip()
        e = self.entry_end_time.get().strip()

        if not self._validate_time_str(s) or not self._validate_time_str(e):
            messagebox.showerror("エラー", "時間の形式が正しくありません。\n例: 09:00, 18:00 (半角数字・コロン)")
            return

        sched = self.cm.config["schedule"]
        current_days = [i for i, v in enumerate(self.day_vars) if v.get()]
        is_changed = (
            s != sched.get("start_time") or
            e != sched.get("end_time") or
            self.var_sched_enabled.get() != sched.get("enabled", True) or
            current_days != sched.get("days", [])
        )
        if not is_changed:
            messagebox.showinfo("情報", "設定に変更はありません。")
            return

        if self.cm.has_password():
            if not self._prompt_password("時間帯制限の設定を変更するにはパスワードを入力してください:"):
                self._sync_schedule_ui_from_config()
                return

        sched["enabled"] = self.var_sched_enabled.get()
        sched["start_time"] = s
        sched["end_time"] = e
        sched["days"] = current_days
        self.cm.save()
        messagebox.showinfo("成功", "時間帯制限の設定を保存しました。")

    def _on_timer_toggle(self):
        if self.cm.has_password():
            if not self._prompt_password("タイマー制限を切り替えるにはパスワードを入力してください:"):
                self.var_timer_enabled.set(self.cm.config["timer"].get("enabled", False))
                return
        self.cm.config["timer"]["enabled"] = self.var_timer_enabled.get()
        self.cm.save()

    def _save_timer_config(self):
        try:
            val = int(self.entry_timer_limit.get().strip())
        except ValueError:
            messagebox.showerror("エラー", "正の整数（分）を入力してください。")
            return

        if val < 1:
            messagebox.showerror("エラー", "1分以上を指定してください。")
            return

        timer_cfg = self.cm.config["timer"]
        is_changed = (val != timer_cfg.get("daily_limit_minutes") or
                      self.var_timer_enabled.get() != timer_cfg.get("enabled", False))
        if not is_changed:
            messagebox.showinfo("情報", "設定に変更はありません。")
            return

        if self.cm.has_password():
            if not self._prompt_password("タイマー制限の設定を変更するにはパスワードを入力してください:"):
                self.var_timer_enabled.set(timer_cfg.get("enabled", False))
                self.entry_timer_limit.delete(0, tk.END)
                self.entry_timer_limit.insert(0, str(timer_cfg.get("daily_limit_minutes", 30)))
                return

        timer_cfg["daily_limit_minutes"] = val
        timer_cfg["enabled"] = self.var_timer_enabled.get()
        self.cm.save()
        messagebox.showinfo("成功", "タイマー設定を保存しました。")

    def _reset_today_timer(self):
        if self.cm.has_password():
            if not self._prompt_password("本日の利用時間をリセットするにはパスワードを入力してください:"):
                return
        self.cm.config["timer"]["spent_seconds_today"] = 0
        self.cm.save()
        messagebox.showinfo("完了", "本日の利用時間カウントをゼロにリセットしました。")

    # --- TAB 4: SETTINGS & SECURITY ---
    def _build_settings_tab(self):
        frame = ttk.Frame(self.tab_settings, padding=15)
        frame.pack(fill="both", expand=True)

        # Autostart
        boot_box = ttk.LabelFrame(frame, text="🚀 スタートアップ設定", padding=15)
        boot_box.pack(fill="x", pady=5)

        self.var_boot = tk.BooleanVar(value=self.cm.config["settings"].get("start_on_boot", True))
        chk_boot = ttk.Checkbutton(boot_box, text="Windows起動時に自動起動する（バックグラウンド常駐）", 
                                   variable=self.var_boot, command=self._on_boot_toggle)
        chk_boot.pack(anchor="w")

        # Security Password
        pass_box = ttk.LabelFrame(frame, text="🔒 解除防止パスワード", padding=15)
        pass_box.pack(fill="x", pady=10)

        pass_desc = ttk.Label(pass_box, text="意思の弱さで勝手に解除してしまうのを防ぐため、時間帯制限の変更やサイト削除、制限解除にパスワードを要求します。")
        pass_desc.pack(anchor="w", pady=(0, 6))

        self.lbl_pass_status = tk.Label(pass_box, text="", font=("Segoe UI", 9, "bold"))
        self.lbl_pass_status.pack(anchor="w", pady=(0, 8))
        self._update_password_status_ui()

        btn_pass_row = ttk.Frame(pass_box)
        btn_pass_row.pack(fill="x")

        ttk.Button(btn_pass_row, text="パスワードを設定・変更", command=self._change_password).pack(side="left", padx=4)
        ttk.Button(btn_pass_row, text="パスワードを解除", command=self._remove_password).pack(side="left", padx=4)

        # Blocker status
        tech_box = ttk.LabelFrame(frame, text="🛡️ 通信遮断エンジンの状態", padding=15)
        tech_box.pack(fill="x", pady=10)

        hosts_ok = self.blocker.is_hosts_writable()
        status_h = "✅ hosts ファイル直接書込可能 (全通信・全ブラウザ完全遮断)" if hosts_ok else "⚠️ PAC プロキシ連携モードで稼働中 (管理者権限不要)"
        self.lbl_tech_status = ttk.Label(tech_box, text=status_h, font=("Segoe UI", 10))
        self.lbl_tech_status.pack(anchor="w")

    def _on_boot_toggle(self):
        val = self.var_boot.get()
        if not val and self.cm.has_password():
            if not self._prompt_password("自動起動をOFFにするにはパスワードを入力してください:"):
                self.var_boot.set(True)
                return
        script_path = os.path.abspath(sys.argv[0])
        # Use pythonw to launch silently on boot
        pythonw = os.path.join(os.path.dirname(sys.executable), "pythonw.exe")
        if not os.path.exists(pythonw):
            pythonw = sys.executable
        cmd = f'"{pythonw}" "{script_path}"'
        self.cm.set_autostart(val, exe_path=cmd)

    def _change_password(self):
        if self.cm.has_password():
            if not self._prompt_password("現在のパスワードを入力してください:"):
                return
        new_pass = simpledialog.askstring("設定", "新しいパスワードを入力してください:", show="*")
        if new_pass is not None:
            if not new_pass.strip():
                messagebox.showwarning("警告", "パスワードが空です。解除する場合は「パスワードを解除」ボタンを使用してください。")
                return
            self.cm.set_password(new_pass.strip())
            self._update_password_status_ui()
            messagebox.showinfo("成功", "パスワードを設定しました。")

    def _remove_password(self):
        if not self.cm.has_password():
            messagebox.showinfo("情報", "パスワードは設定されていません。")
            return
        if not self._prompt_password("パスワードを解除するには現在のパスワードを入力してください:"):
            return
        self.cm.set_password("")
        self._update_password_status_ui()
        messagebox.showinfo("成功", "パスワードを解除しました。")

    def _on_master_toggle(self):
        if not self.var_master_enabled.get() and self.cm.has_password():
            if not self._prompt_password("保護機能をOFFにするにはパスワードを入力してください:"):
                self.var_master_enabled.set(True)
                return
        self.cm.config["enabled"] = self.var_master_enabled.get()
        self.cm.save()

    # --- QUICK FOCUS ACTIONS ---
    def start_quick_focus(self, minutes):
        until = time.time() + (minutes * 60)
        self.cm.config["quick_focus"]["active"] = True
        self.cm.config["quick_focus"]["until_timestamp"] = until
        self.cm.save()
        messagebox.showinfo("集中モード開始", f"{minutes}分間の集中ブロックを開始しました！\n対象サイトへのアクセスは遮断されます。")

    def stop_quick_focus(self):
        if self.cm.has_password():
            if not self._prompt_password("集中モードを解除するにはパスワードを入力してください:"):
                return
        self.cm.config["quick_focus"]["active"] = False
        self.cm.config["quick_focus"]["until_timestamp"] = 0
        self.cm.save()
        messagebox.showinfo("集中モード終了", "集中モードを解除しました。")

    # --- MONITORING LOOP ---
    def _monitor_loop(self):
        while self.running:
            try:
                self._check_and_update_block_state()
            except Exception as e:
                print(f"Monitor error: {e}")
            time.sleep(1)

    def _is_time_in_range(self, start_str, end_str):
        now = datetime.now().time()
        try:
            s_time = datetime.strptime(start_str, "%H:%M").time()
            e_time = datetime.strptime(end_str, "%H:%M").time()
            if s_time <= e_time:
                return s_time <= now <= e_time
            else:  # Crosses midnight (e.g. 22:00 to 07:00)
                return now >= s_time or now <= e_time
        except Exception:
            return False

    def _check_and_update_block_state(self):
        cfg = self.cm.config
        master_enabled = cfg.get("enabled", True)

        should_block = False
        reason = ""

        if master_enabled:
            # 1. Check Quick Focus
            qf = cfg.get("quick_focus", {})
            if qf.get("active", False):
                rem = qf.get("until_timestamp", 0) - time.time()
                if rem > 0:
                    should_block = True
                    mins_rem = int(rem // 60)
                    secs_rem = int(rem % 60)
                    reason = f"⚡ クイック集中モード中 (残り {mins_rem}分{secs_rem}秒)"
                else:
                    qf["active"] = False
                    self.cm.save()

            # 2. Check Schedule
            if not should_block and cfg.get("schedule", {}).get("enabled", False):
                sched = cfg["schedule"]
                today_weekday = datetime.now().weekday()
                if today_weekday in sched.get("days", []):
                    if self._is_time_in_range(sched.get("start_time", "09:00"), sched.get("end_time", "18:00")):
                        should_block = True
                        reason = f"⏰ スケジュール制限中 ({sched.get('start_time')} 〜 {sched.get('end_time')})"

            # 3. Check Daily Timer Limit
            if not should_block and cfg.get("timer", {}).get("enabled", False):
                timer_cfg = cfg["timer"]
                limit_secs = timer_cfg.get("daily_limit_minutes", 30) * 60
                spent = timer_cfg.get("spent_seconds_today", 0)
                if spent >= limit_secs:
                    should_block = True
                    reason = f"⏳ 1日の上限利用時間 ({timer_cfg.get('daily_limit_minutes')}分) を超過しました"

        # Apply state to blocker
        if should_block:
            sites = cfg.get("blocked_sites", [])
            use_hosts = cfg.get("settings", {}).get("use_hosts", True)
            use_pac = cfg.get("settings", {}).get("use_pac", True)
            expanded = expand_domains(sites)
            if not self.blocker.is_blocking or set(self.blocker.current_blocked_domains) != set(expanded):
                self.blocker.block(sites, use_hosts=use_hosts, use_pac=use_pac)
            self.is_currently_blocked = True
        else:
            if self.blocker.is_blocking:
                self.blocker.unblock()
            self.is_currently_blocked = False
            if not master_enabled:
                reason = "全体の保護機能がOFFになっています"
            else:
                reason = "現在アクセス可能です（スケジュール時間外）"

        self.current_status_text = reason

        # Schedule UI update in main thread
        self.root.after(0, self._update_ui_state)

    def _update_ui_state(self):
        if self.is_currently_blocked:
            self.lbl_status_icon.config(text="🛡️", fg="#dc3545")
            self.lbl_status_title.config(text="現在: アクセス遮断中（ブロック発動）", fg="#dc3545")
            self.lbl_status_detail.config(text=self.current_status_text)
        else:
            self.lbl_status_icon.config(text="🟢", fg="#28a745")
            self.lbl_status_title.config(text="現在: アクセス許可中", fg="#28a745")
            self.lbl_status_detail.config(text=self.current_status_text)

        # Update today summary text
        timer_cfg = self.cm.config.get("timer", {})
        spent_min = timer_cfg.get("spent_seconds_today", 0) // 60
        limit_min = timer_cfg.get("daily_limit_minutes", 30)
        timer_enabled_str = "有効" if timer_cfg.get("enabled", False) else "無効"
        self.lbl_today_summary.config(
            text=f"本日の利用時間: {spent_min} 分 / 上限 {limit_min} 分 (タイマー制限: {timer_enabled_str})"
        )

        # Update tray icon & tooltip
        if hasattr(self, "tray_icon") and self.tray_icon:
            tooltip = f"FocusGuard: {'🛡️ ブロック中' if self.is_currently_blocked else '🟢 許可中'}"
            self.tray_icon.title = tooltip
            new_img = self.icon_active if self.is_currently_blocked else self.icon_inactive
            self.tray_icon.icon = new_img

    # --- SYSTEM TRAY ---
    def _setup_tray(self):
        try:
            import pystray
            from pystray import MenuItem as item

            menu = (
                item("⚙️ 設定画面を開く", self.show_window, default=True),
                item("⚡ クイック集中 (25分)", lambda: self.start_quick_focus(25)),
                item("🔓 集中解除", self.stop_quick_focus),
                pystray.Menu.SEPARATOR,
                item("❌ FocusGuard 終了", self.quit_app)
            )

            self.tray_icon = pystray.Icon(
                "FocusGuard",
                self.icon_inactive,
                "FocusGuard: 待機中",
                menu
            )
            threading.Thread(target=self.tray_icon.run, daemon=True).start()
        except Exception as e:
            print(f"Failed to initialize pystray: {e}")
            self.tray_icon = None

    def show_window(self, icon=None, item=None):
        self.root.after(0, self._bring_window_to_front)

    def _bring_window_to_front(self):
        try:
            self.root.deiconify()
            self.root.state("normal")
            hwnd = int(self.root.wm_frame(), 16)
            if hwnd:
                user32 = ctypes.windll.user32
                user32.ShowWindow(hwnd, 9)  # SW_RESTORE
                user32.ShowWindow(hwnd, 5)  # SW_SHOW
                fg_hwnd = user32.GetForegroundWindow()
                fg_thread = user32.GetWindowThreadProcessId(fg_hwnd, None)
                cur_thread = ctypes.windll.kernel32.GetCurrentThreadId()
                if fg_thread != 0 and fg_thread != cur_thread:
                    user32.AttachThreadInput(cur_thread, fg_thread, True)
                    user32.SetForegroundWindow(hwnd)
                    user32.BringWindowToTop(hwnd)
                    user32.AttachThreadInput(cur_thread, fg_thread, False)
                else:
                    user32.SetForegroundWindow(hwnd)
                    user32.BringWindowToTop(hwnd)
        except Exception as e:
            print(f"Error restoring window: {e}")

        self.root.lift()
        self.root.attributes("-topmost", True)
        self.root.after(150, self._remove_topmost)
        self.root.focus_force()

    def _remove_topmost(self):
        try:
            self.root.attributes("-topmost", False)
        except Exception:
            pass

    def hide_window(self):
        self.root.withdraw()
        if hasattr(self, "tray_icon") and self.tray_icon:
            try:
                self.tray_icon.notify(
                    "FocusGuard はタスクトレイで常駐監視中です。\n再度開くには run.bat を実行するか、トレイアイコンをクリックしてください。",
                    "FocusGuard 最小化"
                )
            except Exception:
                pass

    def quit_app(self):
        if self.cm.has_password():
            if not self._prompt_password("FocusGuardを終了するにはパスワードを入力してください:"):
                return

        self.running = False
        try:
            self.blocker.unblock()
        except Exception:
            pass

        if hasattr(self, "tray_icon") and self.tray_icon:
            self.tray_icon.stop()

        self.root.destroy()
        sys.exit(0)

_single_instance_mutex_handle = None

def try_signal_existing_instance():
    try:
        try:
            ctypes.windll.user32.AllowSetForegroundWindow(-1)
        except Exception:
            pass
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.settimeout(1.2)
        s.connect(("127.0.0.1", IPC_PORT))
        s.sendall(b"SHOW\n")
        resp = s.recv(1024)
        s.close()
        return b"OK" in resp
    except Exception:
        return False

def acquire_single_instance_lock():
    global _single_instance_mutex_handle
    mutex_name = "Local\\FocusGuard_SingleInstance_Mutex_App"
    handle = ctypes.windll.kernel32.CreateMutexW(None, False, mutex_name)
    last_error = ctypes.windll.kernel32.GetLastError()
    ERROR_ALREADY_EXISTS = 183
    if last_error == ERROR_ALREADY_EXISTS:
        return None
    _single_instance_mutex_handle = handle
    return handle

def kill_other_focusguard_instances():
    my_pid = os.getpid()
    try:
        import subprocess
        # Terminate any process holding IPC_PORT
        s_cmd = f"(Get-NetTCPConnection -LocalPort {IPC_PORT} -ErrorAction SilentlyContinue).OwningProcess | Where-Object {{ $_ -ne {my_pid} -and $_ -gt 0 }} | ForEach-Object {{ Stop-Process -Id $_ -Force }}"
        subprocess.run(["powershell", "-NoProfile", "-Command", s_cmd], capture_output=True, timeout=5)
    except Exception:
        pass

def main():
    # If already running, signal existing instance to show its window and exit
    if try_signal_existing_instance():
        sys.exit(0)

    mutex_handle = acquire_single_instance_lock()
    if mutex_handle is None:
        time.sleep(0.5)
        if try_signal_existing_instance():
            sys.exit(0)

        # Mutex exists but IPC does not respond
        root = tk.Tk()
        root.withdraw()
        ans = messagebox.askyesno(
            "FocusGuard",
            "FocusGuard は既に起動しているか、前回のプロセスが終了していません。\n\n"
            "画面右下のタスクトレイにアイコンが見当たらない場合、前回のプロセスが停止している可能性があります。\n\n"
            "前回のプロセスを終了して、FocusGuard を新しく起動しますか？"
        )
        root.destroy()
        if ans:
            kill_other_focusguard_instances()
            time.sleep(0.8)
            mutex_handle = acquire_single_instance_lock()
        else:
            sys.exit(0)

    root = tk.Tk()
    app = FocusGuardApp(root)
    root.deiconify()
    root.state("normal")
    root.lift()
    root.focus_force()
    root.mainloop()

if __name__ == "__main__":
    main()
