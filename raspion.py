#!/usr/bin/env python

import telepot # type: ignore
from datetime import datetime
import os

#Check if external HDD are mounted
def hdd_check(path):
    hdd_mnt = os.path.ismount(path)
    if hdd_mnt:
        hdd_state = "OK"
    else:
        hdd_state = "NO-OK"
    return(hdd_state)

#Check if VPN service is running
def vpn_check():
    if not bool(os.system('ps aux | pgrep wg')):
        status = "OK"
    else:
        status = "NO-OK"
    return(status)

#Check if MiniDLNA service is running
def dlna_check():
    if not bool(os.system('ps aux | pgrep minidlna')):
        status = "OK"
    else:
        status = "NO-OK"
    return(status)

#Check Raspi Temperature
def temp_check():
    status = os.popen('vcgencmd measure_temp').readline()
    status = status.split("=",1)[1]
    return(status)

#Telegram message
def telegram(msg):
    bot = telepot.Bot('1228874624:AAEkMwsunE4BLoFndVIowKlAUnqcCYEeR78')
    bot.sendMessage(13981480, msg)
    return

hdd1 = "/media/USBHDD1"
hdd2 = "/media/USBHDD2"
message = "Pagola Pi started succesfully!\n" +\
          "- HDD1 unit: " + hdd_check(hdd1) + "\n" +\
          "- HDD2 unit: " + hdd_check(hdd2) + "\n" +\
          "- VPN service: " + vpn_check() + "\n" +\
          "- MiniDLNA service: " + dlna_check() + "\n" +\
          "- CPU temperature: " + temp_check() + "\n" +\
          "- Local time: " + datetime.now().strftime("%d/%m/%Y @ %H:%M")
telegram(message)
