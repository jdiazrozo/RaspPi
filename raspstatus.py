#!/usr/bin/env python3
import telepot # type: ignore
from datetime import datetime, timedelta
import shutil
import subprocess
import psutil # type: ignore
from dotenv import load_dotenv # type: ignore

# ----------------------------
# ENVIRONMENT
# ----------------------------
load_dotenv('/home/pi/keys/.env')
chat_id = int(psutil.os.getenv("chat_id"))
telegram_key = psutil.os.getenv("telegram_key")
bot = telepot.Bot(telegram_key)

# ----------------------------
# HELPER FUNCTIONS
# ----------------------------
def run_command(cmd):
    """Run a shell command and return its output (stripped)."""
    try:
        return subprocess.run(cmd, shell=True, text=True, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL).stdout.strip()
    except Exception:
        return ""

def get_uptime():
    """Return uptime in human-readable format."""
    try:
        with open("/proc/uptime", "r") as f:
            uptime_seconds = float(f.readline().split()[0])
        days, rest = divmod(int(uptime_seconds), 86400)
        hours, rest = divmod(rest, 3600)
        minutes = rest // 60
        return f"{days}d {hours}h {minutes}m" if days else f"{hours}h {minutes}m"
    except Exception:
        return "ERROR"

def startup_check(threshold_minutes=5):
    """Return startup message if system rebooted recently."""
    try:
        uptime_seconds = float(open("/proc/uptime", "r").read().split()[0])
        return "🔄 *System just started!*" if uptime_seconds < threshold_minutes * 60 else ""
    except Exception:
        return ""

def shutdowns_last_24h():
    """Count shutdown or reboot events in the last 24 hours."""
    try:
        since = (datetime.now() - timedelta(hours=24)).strftime("%Y-%m-%d %H:%M:%S")
        cmd = f"last -x --since '{since}' | grep -E 'shutdown|reboot' | wc -l"
        result = run_command(cmd)
        return result if result else "0"
    except Exception:
        return "ERROR"

def hdd_check(path):
    return "OK" if shutil.os.path.ismount(path) else "NO-OK"

def disk_usage(path, warn_limit_gb=10):
    """Check disk usage and return free space with warning."""
    try:
        total, used, free = shutil.disk_usage(path)
        free_gb = free // (2**30)
        return f"{free_gb} GB free", (free_gb < warn_limit_gb)
    except Exception:
        return "ERROR", True

def hdd_health(device="/dev/sda"):
    """Check HDD health via smartctl."""
    output = run_command(f"sudo smartctl -H {device} | grep 'PASSED'")
    return "OK" if "PASSED" in output else "⚠️ Check Disk"

def check_service(proc_name):
    """Generic service checker using pgrep."""
    return "OK" if subprocess.call(f"pgrep {proc_name}", shell=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL) == 0 else "NO-OK"

def network_check(host="8.8.8.8"):
    """Check network connectivity."""
    return "OK" if subprocess.call(f"ping -c 1 -W 2 {host}", shell=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL) == 0 else "NO-OK"

# ----------------------------
# CACHED COMMANDS
# ----------------------------
VCGENCMD = run_command('vcgencmd measure_temp && vcgencmd get_throttled')
TEMP_OUTPUT = VCGENCMD.splitlines()[0] if VCGENCMD else "temp=0'C"
THROTTLE_OUTPUT = VCGENCMD.splitlines()[1] if len(VCGENCMD.splitlines()) > 1 else "throttled=0x0"

UPDATES_OUTPUT = run_command("apt list --upgradable 2>/dev/null | grep -v 'Listing...'")
FAILED_SERVICES_RAW = run_command("systemctl --failed --no-legend | awk '{print $1}'")
DMESG_ERRORS = run_command("dmesg | grep -iE 'mmc0.*(error|fail|I/O)'")

# ----------------------------
# CHECKS USING CACHE
# ----------------------------
def temp_check():
    try:
        temp_val = float(TEMP_OUTPUT.split('=')[1].split("'")[0])
        return f"{temp_val}°C" + (" ⚠️ HOT!" if temp_val > 70 else ""), temp_val > 70
    except Exception:
        return "ERROR", True

def throttling_check():
    """Decode and return a readable throttling status."""
    try:
        status = THROTTLE_OUTPUT.split('=')[1]
        val = int(status, 16)
        if val == 0:
            return "OK"
        messages = []
        if val & 0x1: messages.append("⚠️ Under-voltage")
        if val & 0x2: messages.append("⚠️ ARM freq capped")
        if val & 0x4: messages.append("⚠️ Throttling active")
        if val & 0x8: messages.append("⚠️ Temp limit active")
        if val & 0x10000: messages.append("Under-voltage occurred")
        if val & 0x20000: messages.append("Freq cap occurred")
        if val & 0x40000: messages.append("Throttling occurred")
        if val & 0x80000: messages.append("Temp limit occurred")
        return ", ".join(messages)
    except Exception:
        return "ERROR"

def updates_check():
    return "⚠️ Updates Available" if UPDATES_OUTPUT else "OK"

def failed_services(ignore_list=None):
    """Return failed services excluding ignored ones."""
    if ignore_list is None:
        ignore_list = ["dhcpcd.service"]
    if not FAILED_SERVICES_RAW:
        return "None"
    services = [s for s in FAILED_SERVICES_RAW.splitlines() if s not in ignore_list]
    return ", ".join(services) if services else "None"

def sd_card_health():
    return "⚠️ Errors detected" if DMESG_ERRORS else "OK"

def memory_usage():
    mem = psutil.virtual_memory()
    warn = mem.percent > 80
    return f"{mem.percent:.1f}% used" + (" ⚠️ High" if warn else ""), warn

def cpu_usage():
    usage = psutil.cpu_percent(interval=0.5)
    warn = usage > 85
    return f"{usage:.1f}%" + (" ⚠️ High" if warn else ""), warn

def cpu_load():
    load1, load5, load15 = psutil.getloadavg()
    cores = psutil.cpu_count(logical=True) or 1
    warn = load1 > cores * 1.5
    return f"{load1:.2f} (1m), {load5:.2f} (5m), {load15:.2f} (15m)" + (" ⚠️ High" if warn else ""), warn

# ----------------------------
# BUILD STATUS MESSAGE
# ----------------------------
hdd1 = "/media/USBHDD1"
hdd2 = "/media/USBHDD2"

startup_msg = startup_check()

hdd1_status, _ = disk_usage(hdd1)
hdd2_status, _ = disk_usage(hdd2)
root_status, _ = disk_usage("/")
temp_status, _ = temp_check()
mem_status, _ = memory_usage()
cpu_usage_status, _ = cpu_usage()
cpu_load_status, _ = cpu_load()

message = (
    f"#CurrentStatus #PagolaPi {datetime.now().strftime('%d/%m/%Y %H:%M')}\n"
    + (startup_msg + "\n\n" if startup_msg else "")
    + f"📊 *System Health*:\n"
    + f"• Uptime: {get_uptime()}\n"
    + f"• Shutdowns (last 24h): {shutdowns_last_24h()}\n"
    + f"• OS updates: {updates_check()}\n"
    + f"• Failed services: {failed_services()}\n"
    + f"• SD card: {sd_card_health()}\n\n"
    + f"💾 *Storage*:\n"
    + f"• HDD1: {hdd_check(hdd1)} ({hdd1_status})\n"
    + f"• HDD2: {hdd_check(hdd2)} ({hdd2_status})\n"
    + f"• HDD Health: {hdd_health()}\n"
    + f"• Root FS: {root_status}\n\n"
    + f"🌐 *Network*:\n"
    + f"• VPN: {check_service('wg')}\n"
    + f"• MiniDLNA: {check_service('minidlna')}\n"
    + f"• Connectivity: {network_check()}\n\n"
    + f"🔥 *CPU & Memory*:\n"
    + f"• Temperature: {temp_status}\n"
    + f"• CPU usage: {cpu_usage_status}\n"
    + f"• CPU load: {cpu_load_status}\n"
    + f"• Throttling: {throttling_check()}\n"
    + f"• Memory: {mem_status}"
)

def telegram(msg):
    try:
        bot.sendMessage(chat_id, msg, parse_mode="Markdown")
    except Exception as e:
        print(f"Telegram error: {e}")

telegram(message)
