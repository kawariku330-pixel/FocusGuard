import os
import sys
import time
import threading
from datetime import datetime, date, timedelta
import tkinter as tk
from tkinter import ttk, messagebox, simpledialog
from PIL import Image, ImageDraw

from config_manager import ConfigManager
from blocker import Blocker, normalize_domain

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

        # Start monitoring background thread
        self.monitor_thread = threading.Thread(target=self._monitor_loop, daemon=True)
        self.monitor_thread.start()

    def _setup_ui(self):
        style = ttk.Style()
        try:
            style.theme_use("clam")
        except Exception:
            pass

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

        desc = ttk.Label(frame, text="ブロックするWebサイトのドメイン（例: x.com, youtube.com）を指定します。\nx.com を指定すると、twitter.com や関連サブドメインも自動的に網羅されます。")
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

    def _remove_site(self):
        sel = self.site_listbox.curselection()
        if not sel:
            return
        idx = sel[0]
        sites = self.cm.config.get("blocked_sites", [])
        if 0 <= idx < len(sites):
            del sites[idx]
            self.cm.save()
            self._refresh_site_list()

    def _reset_default_sites(self):
        if messagebox.askyesno("確認", "ブロック対象サイトを初期設定（X / Twitter）に戻しますか？"):
            self.cm.config["blocked_sites"] = ["x.com", "twitter.com", "api.x.com", "api.twitter.com"]
            self.cm.save()
            self._refresh_site_list()

    # --- TAB 3: SCHEDULE & TIMER ---
    def _build_schedule_tab(self):
        frame = ttk.Frame(self.tab_schedule, padding=15)
        frame.pack(fill="both", expand=True)

        # Schedule Section
        sched_box = ttk.LabelFrame(frame, text="⏰ 時間帯制限（スケジュール）", padding=15)
        sched_box.pack(fill="x", pady=5)

        self.var_sched_enabled = tk.BooleanVar(value=self.cm.config["schedule"].get("enabled", True))
        chk_sched = ttk.Checkbutton(sched_box, text="時間帯制限を有効にする", variable=self.var_sched_enabled, command=self._save_schedule_config)
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
            ttk.Checkbutton(days_box, text=name, variable=v, command=self._save_schedule_config).pack(side="left", padx=3)

        # Daily Timer Limit Section
        timer_box = ttk.LabelFrame(frame, text="⏳ 1日の利用時間上限（タイマー制限）", padding=15)
        timer_box.pack(fill="x", pady=10)

        self.var_timer_enabled = tk.BooleanVar(value=self.cm.config["timer"].get("enabled", False))
        chk_timer = ttk.Checkbutton(timer_box, text="1日の利用時間上限を有効にする（指定時間を使用したら当日はブロック）", 
                                    variable=self.var_timer_enabled, command=self._save_timer_config)
        chk_timer.pack(anchor="w", pady=(0, 8))

        timer_row = ttk.Frame(timer_box)
        timer_row.pack(fill="x")

        ttk.Label(timer_row, text="1日の閲覧上限（分）:").pack(side="left", padx=(0, 5))
        self.entry_timer_limit = ttk.Entry(timer_row, width=8)
        self.entry_timer_limit.insert(0, str(self.cm.config["timer"].get("daily_limit_minutes", 30)))
        self.entry_timer_limit.pack(side="left", padx=(0, 15))

        ttk.Button(timer_row, text="保存", command=self._save_timer_config).pack(side="left", padx=4)
        ttk.Button(timer_row, text="本日の利用時間をリセット", command=self._reset_today_timer).pack(side="left", padx=4)

    def _set_preset(self, start, end):
        self.entry_start_time.delete(0, tk.END)
        self.entry_start_time.insert(0, start)
        self.entry_end_time.delete(0, tk.END)
        self.entry_end_time.insert(0, end)
        self._save_schedule_config()

    def _save_schedule_config(self):
        s = self.entry_start_time.get().strip()
        e = self.entry_end_time.get().strip()
        self.cm.config["schedule"]["enabled"] = self.var_sched_enabled.get()
        self.cm.config["schedule"]["start_time"] = s
        self.cm.config["schedule"]["end_time"] = e
        self.cm.config["schedule"]["days"] = [i for i, v in enumerate(self.day_vars) if v.get()]
        self.cm.save()

    def _save_timer_config(self):
        try:
            val = int(self.entry_timer_limit.get().strip())
            self.cm.config["timer"]["daily_limit_minutes"] = max(1, val)
        except ValueError:
            pass
        self.cm.config["timer"]["enabled"] = self.var_timer_enabled.get()
        self.cm.save()

    def _reset_today_timer(self):
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

        pass_desc = ttk.Label(pass_box, text="意思の弱さで勝手に解除してしまうのを防ぐため、設定変更や制限解除にパスワードを要求できます。")
        pass_desc.pack(anchor="w", pady=(0, 8))

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
        script_path = os.path.abspath(sys.argv[0])
        # Use pythonw to launch silently on boot
        pythonw = os.path.join(os.path.dirname(sys.executable), "pythonw.exe")
        if not os.path.exists(pythonw):
            pythonw = sys.executable
        cmd = f'"{pythonw}" "{script_path}"'
        self.cm.set_autostart(val, exe_path=cmd)

    def _change_password(self):
        if self.cm.has_password():
            curr = simpledialog.askstring("認証", "現在のパスワードを入力してください:", show="*")
            if not curr or not self.cm.check_password(curr):
                messagebox.showerror("エラー", "パスワードが正しくありません。")
                return
        new_pass = simpledialog.askstring("設定", "新しいパスワードを入力してください:", show="*")
        if new_pass:
            self.cm.set_password(new_pass)
            messagebox.showinfo("成功", "パスワードを設定しました。")

    def _remove_password(self):
        if not self.cm.has_password():
            messagebox.showinfo("情報", "パスワードは設定されていません。")
            return
        curr = simpledialog.askstring("認証", "現在のパスワードを入力してください:", show="*")
        if curr and self.cm.check_password(curr):
            self.cm.set_password("")
            messagebox.showinfo("成功", "パスワードを解除しました。")
        else:
            messagebox.showerror("エラー", "パスワードが正しくありません。")

    def _on_master_toggle(self):
        if not self.var_master_enabled.get() and self.cm.has_password():
            pwd = simpledialog.askstring("認証", "保護機能をOFFにするにはパスワードを入力してください:", show="*")
            if not pwd or not self.cm.check_password(pwd):
                messagebox.showerror("エラー", "パスワードが一致しません。")
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
            pwd = simpledialog.askstring("認証", "集中モードを解除するにはパスワードを入力してください:", show="*")
            if not pwd or not self.cm.check_password(pwd):
                messagebox.showerror("エラー", "パスワードが正しくありません。")
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
            if not self.blocker.is_blocking:
                sites = cfg.get("blocked_sites", [])
                use_hosts = cfg.get("settings", {}).get("use_hosts", True)
                use_pac = cfg.get("settings", {}).get("use_pac", True)
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

    def show_window(self):
        self.root.deiconify()
        self.root.lift()
        self.root.focus_force()

    def hide_window(self):
        self.root.withdraw()

    def quit_app(self):
        if self.cm.has_password():
            pwd = simpledialog.askstring("認証", "FocusGuardを終了するにはパスワードを入力してください:", show="*")
            if not pwd or not self.cm.check_password(pwd):
                messagebox.showerror("エラー", "パスワードが正しくありません。")
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

def main():
    root = tk.Tk()
    app = FocusGuardApp(root)
    root.mainloop()

if __name__ == "__main__":
    main()
