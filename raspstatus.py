#!/usr/bin/env python3
import telepot # type: ignore
from datetime import datetime
import os
import shutil
import psutil # type: ignore
from dotenv import load_dotenv # type: ignore

# Load environment variables
load_dotenv('/home/pi/keys/.env')
chat_id = int(os.getenv("chat_id"))
telegram_key = os.getenv("telegram_key")
bot = telepot.Bot(telegram_key)

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
        return f"{free_gb} GB free", (free_gb < warn_limit_gb)
    except Exception:
        return "ERROR", True

def root_usage(warn_limit_gb=2):
    return disk_usage("/", warn_limit_gb)

def hdd_health(device="/dev/sda"):
    try:
        output = os.popen(f"sudo smartctl -H {device} 2>/dev/null | grep 'PASSED'").read().strip()
        return "OK" if "PASSED" in output else "⚠️ Check Disk"
    except Exception:
        return "N/A"

def vpn_check():
    return "OK" if os.system("pgrep wg > /dev/null") == 0 else "NO-OK"

def dlna_check():
    return "OK" if os.system("pgrep minidlna > /dev/null") == 0 else "NO-OK"

def temp_check():
    try:
        temp_str = os.popen('vcgencmd measure_temp').read().strip()
        temp_val = float(temp_str.split('=')[1].split("'")[0])
        warn = temp_val > 70
        return f"{temp_val}°C" + (" ⚠️ HOT!" if warn else ""), warn
    except Exception:
        return "ERROR", True

def throttling_check():
    try:
        status = os.popen("vcgencmd get_throttled").read().strip()
        return "OK" if status == "throttled=0x0" else f"⚠️ {status}"
    except Exception:
        return "ERROR"

def memory_usage():
    try:
        mem = psutil.virtual_memory()
        warn = mem.percent > 80
        return f"{mem.percent}% used" + (" ⚠️ High" if warn else ""), warn
    except Exception:
        return "ERROR", True

def cpu_usage():
    try:
        usage = psutil.cpu_percent(interval=1)
        warn = usage > 85
        return f"{usage}%" + (" ⚠️ High" if warn else ""), warn
    except Exception:
        return "ERROR", True

def cpu_load():
    try:
        load1, load5, load15 = os.getloadavg()
        cores = os.cpu_count() or 1
        warn = load1 > cores * 1.5
        return f"{load1:.2f} (1m), {load5:.2f} (5m), {load15:.2f} (15m)" + (" ⚠️ High" if warn else ""), warn
    except Exception:
        return "ERROR", True

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
        if "dhcpcd.service" in result:
            result = result.replace("dhcpcd.service", "").strip()
        return result if result else "None"
    except Exception:
        return "ERROR"

def sd_card_health():
    try:
        errors = os.popen("dmesg | grep -iE 'mmc0.*(error|fail|I/O)'").read().strip()
        return "⚠️ Errors detected" if errors else "OK"
    except Exception:
        return "ERROR"

def telegram(msg):
    try:
        bot.sendMessage(chat_id, msg)
    except Exception as e:
        print(f"Telegram error: {e}")

# ----------------------------
# BUILD MESSAGE
# ----------------------------
hdd1 = "/media/USBHDD1"
hdd2 = "/media/USBHDD2"

startup_msg = startup_check()
updates_status = updates_check()

warnings = []

hdd1_status, hdd1_warn = disk_usage(hdd1)
hdd2_status, hdd2_warn = disk_usage(hdd2)
root_status, root_warn = root_usage()

temp_status, temp_warn = temp_check()
mem_status, mem_warn = memory_usage()
cpu_usage_status, cpu_usage_warn = cpu_usage()
cpu_load_status, cpu_load_warn = cpu_load()

if hdd1_warn: warnings.append(f"HDD1 low space: {hdd1_status}")
if hdd2_warn: warnings.append(f"HDD2 low space: {hdd2_status}")
if root_warn: warnings.append(f"Root FS low space: {root_status}")
if temp_warn: warnings.append(f"High CPU temperature: {temp_status}")
if mem_warn: warnings.append(f"Memory usage: {mem_status}")
if cpu_usage_warn: warnings.append(f"CPU usage: {cpu_usage_status}")
if cpu_load_warn: warnings.append(f"CPU load: {cpu_load_status}")
if updates_status == "Available": warnings.append("OS updates available")
if failed_services() != "None": warnings.append(f"Failed services: {failed_services()}")
if sd_card_health() != "OK": warnings.append("SD card errors detected")

# Summary header
summary = f"#CurrentStatus #PagolaPi {datetime.now().strftime('%d/%m/%Y %H:%M')}\n"
if startup_msg:
    summary += startup_msg + "\n\n"

if warnings:
    summary += "⚠️ Issues detected:\n  - " + "\n  - ".join(warnings) + "\n\n"
else:
    summary += "✅ All systems are OK.\n\n"

# Full detailed status
details = (
    f"- HDD1: {hdd_check(hdd1)} ({hdd1_status})\n"
    f"- HDD2: {hdd_check(hdd2)} ({hdd2_status})\n"
    f"- HDD Health: {hdd_health()}\n"
    f"- Root FS: {root_status}\n"
    f"- VPN service: {vpn_check()}\n"
    f"- MiniDLNA service: {dlna_check()}\n"
    f"- Network: {network_check()}\n"
    f"- CPU temperature: {temp_status}\n"
    f"- CPU usage: {cpu_usage_status}\n"
    f"- CPU load: {cpu_load_status}\n"
    f"- Throttling: {throttling_check()}\n"
    f"- Memory usage: {mem_status}\n"
    f"- OS updates: {'⚠️ Updates Available' if updates_status == 'Available' else '✅ None'}\n"
    f"- Failed services: {failed_services()}\n"
    f"- SD card health: {sd_card_health()}"
)

telegram(summary + details)