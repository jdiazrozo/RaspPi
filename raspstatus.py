#!/usr/bin/env python3
import telepot # type: ignore
from datetime import datetime, timedelta
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

def get_uptime():
    """Return uptime in human-readable format."""
    try:
        with open("/proc/uptime", "r") as f:
            uptime_seconds = float(f.readline().split()[0])
        days, rest = divmod(uptime_seconds, 86400)
        hours, rest = divmod(rest, 3600)
        minutes = int(rest // 60)
        if days >= 1:
            return f"{int(days)}d {int(hours)}h {minutes}m"
        return f"{int(hours)}h {minutes}m"
    except Exception:
        return "ERROR"

def startup_check(threshold_minutes=5):
    """Check if the system has just started."""
    try:
        uptime_seconds = float(open("/proc/uptime", "r").read().split()[0])
        if uptime_seconds < threshold_minutes * 60:
            return f"🔄 *System just started!*"
        return ""
    except Exception:
        return ""

def shutdowns_last_24h():
    """Count number of shutdowns or reboots in last 24h."""
    try:
        since = (datetime.now() - timedelta(hours=24)).strftime("%b %_d")
        cmd = f"last -x | grep -E 'shutdown|reboot' | grep '{since}' | wc -l"
        count = os.popen(cmd).read().strip()
        return count if count else "0"
    except Exception:
        return "ERROR"

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
        return "⚠️ Updates Available" if result else "OK"
    except Exception:
        return "ERROR"

def failed_services():
    try:
        result = os.popen("systemctl --failed --no-legend | awk '{print $1}'").read().strip()
        # Filter out irrelevant services
        ignored = ["dhcpcd.service"]
        services = [s for s in result.split() if s not in ignored]
        return ", ".join(services) if services else "None"
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
        bot.sendMessage(chat_id, msg, parse_mode="Markdown")
    except Exception as e:
        print(f"Telegram error: {e}")

# ----------------------------
# BUILD MESSAGE
# ----------------------------
hdd1 = "/media/USBHDD1"
hdd2 = "/media/USBHDD2"

startup_msg = startup_check()
hdd1_status, _ = disk_usage(hdd1)
hdd2_status, _ = disk_usage(hdd2)
root_status, _ = root_usage()
temp_status, _ = temp_check()
mem_status, _ = memory_usage()
cpu_usage_status, _ = cpu_usage()
cpu_load_status, _ = cpu_load()

message = (
    f"#CurrentStatus #PagolaPi {datetime.now().strftime('%d/%m/%Y %H:%M')}\n"
    + (startup_msg + "\n\n" if startup_msg else "")
    + f"📊 **System Health**\n"
    + f"• ⏱ Uptime: {get_uptime()}\n"
    + f"• 🔌 Shutdowns (last 24h): {shutdowns_last_24h()}\n"
    + f"• 🛠 OS updates: {updates_check()}\n"
    + f"• ❗ Failed services: {failed_services()}\n"
    + f"• 💾 SD card: {sd_card_health()}\n\n"
    + f"🖴 **Storage**\n"
    + f"• HDD1: {hdd_check(hdd1)} ({hdd1_status})\n"
    + f"• HDD2: {hdd_check(hdd2)} ({hdd2_status})\n"
    + f"• HDD Health: {hdd_health()}\n"
    + f"• Root FS: {root_status}\n\n"
    + f"🌐 **Network**\n"
    + f"• 🔒 VPN: {vpn_check()}\n"
    + f"• 📺 MiniDLNA: {dlna_check()}\n"
    + f"• 🌍 Connectivity: {network_check()}\n\n"
    + f"🔥 **CPU & Memory**\n"
    + f"• 🌡 Temperature: {temp_status}\n"
    + f"• 🧮 CPU usage: {cpu_usage_status}\n"
    + f"• 📈 CPU load: {cpu_load_status}\n"
    + f"• ⚡ Throttling: {throttling_check()}\n"
    + f"• 🧠 Memory: {mem_status}"
)

telegram(message)