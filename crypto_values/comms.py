#!/usr/bin/env python

import telepot
import trade_config as config

#Telegram message
def telegram(msg):
    bot = telepot.Bot(config.telegram_key)
    bot.sendMessage(13981480, msg, parse_mode = 'Markdown')
    return;