import os
import sys
import json
import hashlib
import winreg
from datetime import datetime, date

CONFIG_DIR = os.path.join(os.environ.get("LOCALAPPDATA", os.path.expanduser("~")), "FocusGuard")
CONFIG_PATH = os.path.join(CONFIG_DIR, "config.json")

DEFAULT_CONFIG = {
    "enabled": True,
    "blocked_sites": [
        "x.com",
        "twitter.com",
        "api.x.com",
        "api.twitter.com"
    ],
    "schedule": {
        "enabled": True,
        "start_time": "09:00",
        "end_time": "18:00",
        "days": [0, 1, 2, 3, 4]  # 0=Monday .. 6=Sunday (0-4: Weekdays)
    },
    "timer": {
        "enabled": False,
        "daily_limit_minutes": 30,
        "spent_seconds_today": 0,
        "last_date": str(date.today())
    },
    "quick_focus": {
        "active": False,
        "until_timestamp": 0
    },
    "security": {
        "password_hash": "",
        "require_password_to_unblock": False,
        "require_password_to_quit": False
    },
    "settings": {
        "start_on_boot": True,
        "boot_protection": True,
        "use_hosts": True,
        "use_pac": True,
        "notifications": True
    }
}

class ConfigManager:
    def __init__(self, config_path=CONFIG_PATH):
        self.config_path = config_path
        self.config_dir = os.path.dirname(config_path)
        os.makedirs(self.config_dir, exist_ok=True)
        self.config = self.load()

    def load(self):
        if os.path.exists(self.config_path):
            try:
                with open(self.config_path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    # Merge with default to ensure all keys exist
                    merged = self._merge_dict(DEFAULT_CONFIG, data)
                    self._check_and_reset_daily(merged)
                    return merged
            except Exception:
                pass
        config = json.loads(json.dumps(DEFAULT_CONFIG))
        self.save(config)
        return config

    def _merge_dict(self, base, override):
        res = dict(base)
        for k, v in override.items():
            if k in res and isinstance(res[k], dict) and isinstance(v, dict):
                res[k] = self._merge_dict(res[k], v)
            else:
                res[k] = v
        return res

    def _check_and_reset_daily(self, cfg):
        today_str = str(date.today())
        timer_cfg = cfg.get("timer", {})
        if timer_cfg.get("last_date") != today_str:
            timer_cfg["spent_seconds_today"] = 0
            timer_cfg["last_date"] = today_str

    def save(self, config=None):
        if config is not None:
            self.config = config
        self._check_and_reset_daily(self.config)
        try:
            with open(self.config_path, "w", encoding="utf-8") as f:
                json.dump(self.config, f, ensure_ascii=False, indent=2)
        except Exception as e:
            print(f"Error saving config: {e}")

    # Password helpers
    def set_password(self, password_str):
        if not password_str:
            self.config["security"]["password_hash"] = ""
        else:
            hashed = hashlib.sha256(password_str.encode("utf-8")).hexdigest()
            self.config["security"]["password_hash"] = hashed
        self.save()

    def check_password(self, password_str):
        stored_hash = self.config["security"].get("password_hash", "")
        if not stored_hash:
            return True
        hashed = hashlib.sha256(password_str.encode("utf-8")).hexdigest()
        return hashed == stored_hash

    def has_password(self):
        return bool(self.config["security"].get("password_hash"))

    def get_autostart_command(self, script_path=None):
        if not script_path:
            base_dir = os.path.dirname(os.path.abspath(__file__))
            script_path = os.path.join(base_dir, "focus_guard.pyw")
        
        pythonw = os.path.join(os.path.dirname(sys.executable), "pythonw.exe")
        if not os.path.exists(pythonw):
            pythonw = sys.executable
        return f'"{pythonw}" "{os.path.abspath(script_path)}"'

    # Autostart in registry & Windows Startup folder
    def set_autostart(self, enable=True, exe_path=None):
        reg_key = r"Software\Microsoft\Windows\CurrentVersion\Run"
        app_name = "FocusGuard"
        
        if enable:
            if not exe_path:
                exe_path = self.get_autostart_command()
            else:
                exe_path = exe_path.strip()
                # Remove accidental nested outer quotes
                if exe_path.startswith('""') and exe_path.endswith('""'):
                    exe_path = exe_path[1:-1]
        
        # 1. Registry Run Key
        try:
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, reg_key, 0, winreg.KEY_SET_VALUE) as key:
                if enable:
                    winreg.SetValueEx(key, app_name, 0, winreg.REG_SZ, exe_path)
                else:
                    try:
                        winreg.DeleteValue(key, app_name)
                    except FileNotFoundError:
                        pass
        except Exception as e:
            print(f"Error setting registry autostart: {e}")

        # 2. Windows Startup folder backup (silent VBScript launcher)
        try:
            startup_dir = os.path.join(os.environ.get("APPDATA", ""), r"Microsoft\Windows\Start Menu\Programs\Startup")
            if os.path.exists(startup_dir):
                vbs_path = os.path.join(startup_dir, "FocusGuard.vbs")
                if enable:
                    base_dir = os.path.dirname(os.path.abspath(__file__))
                    main_pyw = os.path.join(base_dir, "focus_guard.pyw")
                    pythonw = os.path.join(os.path.dirname(sys.executable), "pythonw.exe")
                    if not os.path.exists(pythonw):
                        pythonw = sys.executable
                    vbs_content = (
                        'Set WshShell = CreateObject("WScript.Shell")\r\n'
                        f'WshShell.Run """{pythonw}"" ""{main_pyw}""", 0, False\r\n'
                    )
                    with open(vbs_path, "w", encoding="utf-8") as f:
                        f.write(vbs_content)
                else:
                    if os.path.exists(vbs_path):
                        try:
                            os.remove(vbs_path)
                        except Exception:
                            pass
        except Exception as e:
            print(f"Error updating startup folder: {e}")

        self.config["settings"]["start_on_boot"] = enable
        self.save()
        return True

    def is_autostart_enabled(self):
        reg_key = r"Software\Microsoft\Windows\CurrentVersion\Run"
        app_name = "FocusGuard"
        try:
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, reg_key, 0, winreg.KEY_READ) as key:
                val, _ = winreg.QueryValueEx(key, app_name)
                if val:
                    return True
        except Exception:
            pass
        startup_dir = os.path.join(os.environ.get("APPDATA", ""), r"Microsoft\Windows\Start Menu\Programs\Startup")
        vbs_path = os.path.join(startup_dir, "FocusGuard.vbs")
        return os.path.exists(vbs_path)

    def ensure_autostart_synced(self):
        """Ensures autostart on Windows matches configuration (called on startup)."""
        should_start = self.config.get("settings", {}).get("start_on_boot", True)
        if should_start:
            if not self.is_autostart_enabled():
                self.set_autostart(True)
        else:
            if self.is_autostart_enabled():
                self.set_autostart(False)
