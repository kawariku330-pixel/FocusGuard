import os
import re
import sys
import time
import ctypes
import threading
import subprocess
import winreg
from http.server import HTTPServer, BaseHTTPRequestHandler
from urllib.parse import urlparse

HOSTS_PATH = os.path.join(os.environ.get("SystemRoot", r"C:\Windows"), r"System32\drivers\etc\hosts")
BLOCK_START_MARKER = "# --- FocusGuard Block Start ---"
BLOCK_END_MARKER = "# --- FocusGuard Block End ---"

PAC_SERVER_PORT = 18989
PAC_URL = f"http://127.0.0.1:{PAC_SERVER_PORT}/proxy.pac"

# WinINet constants
INTERNET_OPTION_SETTINGS_CHANGED = 39
INTERNET_OPTION_REFRESH = 37

def flush_dns():
    try:
        startupinfo = subprocess.STARTUPINFO()
        startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
        subprocess.run(["ipconfig", "/flushdns"], startupinfo=startupinfo, capture_output=True, check=False)
    except Exception as e:
        print(f"Error flushing DNS: {e}")

def refresh_wininet():
    try:
        wininet = ctypes.windll.wininet
        wininet.InternetSetOptionW(0, INTERNET_OPTION_SETTINGS_CHANGED, 0, 0)
        wininet.InternetSetOptionW(0, INTERNET_OPTION_REFRESH, 0, 0)
    except Exception as e:
        print(f"Error refreshing WinINet: {e}")

def normalize_domain(input_str):
    """Cleans up a domain or URL into a clean hostname."""
    s = input_str.strip().lower()
    if not s:
        return ""
    if not (s.startswith("http://") or s.startswith("https://")):
        s = "https://" + s
    try:
        parsed = urlparse(s)
        host = parsed.netloc or parsed.path
        host = host.split(":")[0]  # remove port if any
        return host
    except Exception:
        return input_str.strip().lower()

def expand_domains(domain_list):
    """Expands list of domains to include subdomains/aliases (e.g. x.com -> www.x.com, api.x.com)."""
    expanded = set()
    for d in domain_list:
        clean = normalize_domain(d)
        if not clean:
            continue
        expanded.add(clean)
        if not clean.startswith("www.") and clean.count(".") == 1:
            expanded.add(f"www.{clean}")
        if clean in ("x.com", "twitter.com"):
            expanded.add("x.com")
            expanded.add("www.x.com")
            expanded.add("api.x.com")
            expanded.add("twitter.com")
            expanded.add("www.twitter.com")
            expanded.add("api.twitter.com")
            expanded.add("mobile.twitter.com")
            expanded.add("mobile.x.com")
    return sorted(list(expanded))

class ReusableHTTPServer(HTTPServer):
    allow_reuse_address = True

class PACRequestHandler(BaseHTTPRequestHandler):
    blocked_domains = []

    def do_GET(self):
        if self.path == "/proxy.pac" or self.path.startswith("/proxy.pac?"):
            self.send_response(200)
            self.send_header("Content-Type", "application/x-ns-proxy-autoconfig")
            self.send_header("Cache-Control", "no-cache, no-store, must-revalidate")
            self.send_header("Pragma", "no-cache")
            self.send_header("Expires", "0")
            self.end_headers()
            
            domains_js = ",\n    ".join([f'"{d.lower()}"' for d in PACRequestHandler.blocked_domains])
            pac_script = f"""function FindProxyForURL(url, host) {{
    var h = (host || "").toLowerCase();
    var blocked = [
    {domains_js}
    ];
    for (var i = 0; i < blocked.length; i++) {{
        var d = blocked[i].toLowerCase();
        if (h === d || h.endsWith("." + d) || dnsDomainIs(h, d) || dnsDomainIs(h, "." + d) || shExpMatch(h, "*." + d)) {{
            return "PROXY 127.0.0.1:0";
        }}
    }}
    return "DIRECT";
}}
"""
            self.wfile.write(pac_script.encode("utf-8"))
        else:
            self.send_response(404)
            self.end_headers()

    def log_message(self, format, *args):
        # Silence HTTP server logging
        return

class PACServer:
    def __init__(self, port=PAC_SERVER_PORT):
        self.port = port
        self.server = None
        self.thread = None
        self.is_running = False

    def start(self, blocked_domains):
        PACRequestHandler.blocked_domains = blocked_domains
        if self.is_running:
            return
        for attempt in range(5):
            try:
                self.server = ReusableHTTPServer(("127.0.0.1", self.port), PACRequestHandler)
                self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
                self.thread.start()
                self.is_running = True
                return
            except Exception as e:
                time.sleep(0.5)
        print("Failed to start PAC server after retries")

    def update_domains(self, blocked_domains):
        PACRequestHandler.blocked_domains = blocked_domains

    def stop(self):
        if self.server and self.is_running:
            try:
                self.server.shutdown()
                self.server.server_close()
            except Exception:
                pass
            self.is_running = False

class Blocker:
    def __init__(self):
        self.pac_server = PACServer()
        self.current_blocked_domains = []
        self.is_blocking = False

    def is_hosts_writable(self):
        try:
            if not os.path.exists(HOSTS_PATH):
                return False
            with open(HOSTS_PATH, "a", encoding="utf-8") as f:
                pass
            return True
        except Exception:
            return False

    def apply_hosts_block(self, domains):
        if not self.is_hosts_writable():
            return False
        try:
            with open(HOSTS_PATH, "r", encoding="utf-8", errors="ignore") as f:
                content = f.read()

            # Remove existing FocusGuard block if present
            pattern = re.compile(rf"{re.escape(BLOCK_START_MARKER)}.*?{re.escape(BLOCK_END_MARKER)}\n?", re.DOTALL)
            content = pattern.sub("", content).strip()

            # Construct new block section
            block_lines = [BLOCK_START_MARKER]
            for d in domains:
                block_lines.append(f"127.0.0.1 {d}")
                block_lines.append(f"::1 {d}")
            block_lines.append(BLOCK_END_MARKER)

            new_content = content + "\n\n" + "\n".join(block_lines) + "\n"
            with open(HOSTS_PATH, "w", encoding="utf-8") as f:
                f.write(new_content)

            flush_dns()
            return True
        except Exception as e:
            print(f"Error applying hosts block: {e}")
            return False

    def remove_hosts_block(self):
        if not self.is_hosts_writable():
            return False
        try:
            with open(HOSTS_PATH, "r", encoding="utf-8", errors="ignore") as f:
                content = f.read()

            pattern = re.compile(rf"{re.escape(BLOCK_START_MARKER)}.*?{re.escape(BLOCK_END_MARKER)}\n?", re.DOTALL)
            cleaned = pattern.sub("", content)

            with open(HOSTS_PATH, "w", encoding="utf-8") as f:
                f.write(cleaned)

            flush_dns()
            return True
        except Exception as e:
            print(f"Error removing hosts block: {e}")
            return False

    def apply_pac_block(self, domains):
        self.pac_server.start(domains)
        self.pac_server.update_domains(domains)
        try:
            pac_url_with_version = f"{PAC_URL}?t={int(time.time())}"
            reg_key = r"Software\Microsoft\Windows\CurrentVersion\Internet Settings"
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, reg_key, 0, winreg.KEY_SET_VALUE) as key:
                winreg.SetValueEx(key, "AutoConfigURL", 0, winreg.REG_SZ, pac_url_with_version)
            refresh_wininet()
            return True
        except Exception as e:
            print(f"Error setting PAC proxy in registry: {e}")
            return False

    def remove_pac_block(self):
        try:
            reg_key = r"Software\Microsoft\Windows\CurrentVersion\Internet Settings"
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, reg_key, 0, winreg.KEY_SET_VALUE) as key:
                try:
                    winreg.DeleteValue(key, "AutoConfigURL")
                except FileNotFoundError:
                    pass
            refresh_wininet()
            self.pac_server.stop()
            return True
        except Exception as e:
            print(f"Error removing PAC proxy from registry: {e}")
            return False

    def block(self, domain_list, use_hosts=True, use_pac=True):
        expanded = expand_domains(domain_list)
        self.current_blocked_domains = expanded
        self.is_blocking = True

        hosts_success = False
        pac_success = False

        if use_hosts and self.is_hosts_writable():
            hosts_success = self.apply_hosts_block(expanded)

        if use_pac:
            pac_success = self.apply_pac_block(expanded)

        flush_dns()
        return {"hosts": hosts_success, "pac": pac_success}

    def unblock(self):
        self.is_blocking = False
        self.current_blocked_domains = []
        h_ok = self.remove_hosts_block()
        p_ok = self.remove_pac_block()
        flush_dns()
        return {"hosts": h_ok, "pac": p_ok}
