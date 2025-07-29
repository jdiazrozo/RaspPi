#!/usr/bin/env python
import telepot # type: ignore
from datetime import datetime
import os
import shutil
import subprocess
import psutil # type: ignore
from dotenv import load_dotenv # type: ignore

# Load environment variables
load_dotenv('/home/pi/keys/.env')
chat_id = int(os.getenv("chat_id"))
telegram_key = os.getenv("telegram_key")
bot = telepot.Bot(telegram_key)

def status_icon(status, warn=False):
    return "❌" if status == "NO-OK" else ("⚠️" if warn else "✅")

# ----------------------------
# SYSTEM CHECK FUNCTIONS
# ----------------------------

def startup_check(threshold_minutes=5):
    """Check if the system has just started."""
    try:
        uptime_seconds = float(open("/proc/uptime", "r").read().split()[0])
        if uptime_seconds < threshold_minutes * 60:
            return f"🔄 System has just started (uptime: {int(uptime_seconds // 60)} min)"
        return ""
    except Exception:
        return ""

def hdd_check(path):
    return "OK" if os.path.ismount(path) else "NO-OK"

def disk_usage(path, warn_limit_gb=10):
    try:
        total, used, free = shutil.disk_usage(path)
        free_gb = free // (2**30)
        return f"{free_gb} GB free" + (" ⚠️ Low Space" if free_gb < warn_limit_gb else "")
    except Exception:
        return "ERROR"

def root_usage(warn_limit_gb=2):
    return disk_usage("/", warn_limit_gb)

def hdd_health(device="/dev/sda"):
    try:
        output = os.popen(f"smartctl -H {device} 2>/dev/null | grep 'PASSED'").read().strip()
        return "OK" if "PASSED" in output else "⚠️ Check Disk"
    except Exception:
        return "N/A"

def vpn_check():
    try:
        subprocess.check_output("pgrep wg", shell=True)
        return "OK"
    except subprocess.CalledProcessError:
        return "NO-OK"

def dlna_check():
    try:
        subprocess.check_output("pgrep minidlna", shell=True)
        return "OK"
    except subprocess.CalledProcessError:
        return "NO-OK"

def temp_check():
    try:
        temp_str = os.popen('vcgencmd measure_temp').read().strip()
        temp_val = float(temp_str.split('=')[1].split("'")[0])
        return f"{temp_val}°C" + (" ⚠️ HOT!" if temp_val > 70 else "")
    except Exception:
        return "ERROR"

def throttling_check():
    try:
        status = os.popen("vcgencmd get_throttled").read().strip()
        return "OK" if status == "throttled=0x0" else f"⚠️ {status}"
    except Exception:
        return "ERROR"

def memory_usage():
    try:
        mem = psutil.virtual_memory()
        warn = " ⚠️ High" if mem.percent > 80 else ""
        return f"{mem.percent}% used{warn}"
    except Exception:
        return "ERROR"

def cpu_usage():
    try:
        return f"{psutil.cpu_percent(interval=1)}%"
    except Exception:
        return "ERROR"

def cpu_load():
    try:
        load1, load5, load15 = os.getloadavg()
        warn = " ⚠️ High" if load1 > os.cpu_count() else ""
        return f"{load1:.2f} (1m), {load5:.2f} (5m), {load15:.2f} (15m){warn}"
    except Exception:
        return "ERROR"

def network_check(host="8.8.8.8"):
    return "OK" if os.system(f"ping -c 1 -W 2 {host} > /dev/null 2>&1") == 0 else "NO-OK"

def updates_check():
    try:
        result = os.popen("apt list --upgradable 2>/dev/null | grep -v 'Listing...'").read().strip()
        return "Available" if result else "None"
    except Exception:
        return "ERROR"

def failed_services():
    try:
        result = os.popen("systemctl --failed --no-legend | awk '{print $1}'").read().strip()
        return result if result else "None"
    except Exception:
        return "ERROR"

def sd_card_health():
    try:
        errors = os.popen("dmesg | grep -i 'mmc0' | tail -5").read().strip()
        return "⚠️ Errors detected" if errors else "OK"
    except Exception:
        return "ERROR"

def telegram(msg):
    try:
        bot.sendMessage(chat_id, msg)
    except Exception as e:
        print(f"Telegram error: {e}")

# ----------------------------
# MESSAGE CONSTRUCTION
# ----------------------------
hdd1 = "/media/USBHDD1"
hdd2 = "/media/USBHDD2"

startup_msg = startup_check()
updates_status = updates_check()

message = (
    f"#CurrentStatus #PagolaPi {datetime.now().strftime('%d/%m/%Y %H:%M')}\n"
    + (startup_msg + "\n" if startup_msg else "")
    + f"- HDD1: {status_icon(hdd_check(hdd1))} ({disk_usage(hdd1)})\n"
    + f"- HDD2: {status_icon(hdd_check(hdd2))} ({disk_usage(hdd2)})\n"
    + f"- HDD Health: {hdd_health()}\n"
    + f"- Root FS: {root_usage()}\n"
    + f"- VPN service: {status_icon(vpn_check())}\n"
    + f"- MiniDLNA service: {status_icon(dlna_check())}\n"
    + f"- Network: {status_icon(network_check())}\n"
    + f"- CPU temperature: {temp_check()}\n"
    + f"- CPU usage: {cpu_usage()}\n"
    + f"- CPU load: {cpu_load()}\n"
    + f"- Throttling: {throttling_check()}\n"
    + f"- Memory usage: {memory_usage()}\n"
    + f"- OS updates: {'⚠️ Updates Available' if updates_status == 'Available' else '✅ None'}\n"
    + f"- Failed services: {failed_services()}\n"
    + f"- SD card health: {sd_card_health()}"
)

telegram(message)