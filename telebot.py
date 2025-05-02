import telepot # type: ignore
from telepot.loop import MessageLoop # type: ignore
import importlib.util
import re
import os
import time
import pandas as pd # type: ignore
import sys
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
RASPITRADER_PATH = os.path.join(BASE_DIR, 'crypto_trader')
sys.path.insert(0, RASPITRADER_PATH)
import raspitrader as trader # type: ignore
from dotenv import load_dotenv
load_dotenv('/home/pi/keys/.env')

config_file_path = os.path.join(RASPITRADER_PATH, 'crypto_values/trade_config.py')


chat_state = {}
chat_id = int(os.getenv("chat_id"))
telegram_key = os.getenv("telegram_key")

# Function to load the trade_config module
def load_trade_config():
    spec = importlib.util.spec_from_file_location("trade_config", config_file_path)
    trade_config = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(trade_config)
    return trade_config

# Function to update markets list in trade_config.py
def update_markets(new_markets):
    with open(config_file_path, 'r') as file:
        content = file.read()

    # Regular expression to find the markets list
    markets_pattern = re.compile(r"(markets\s*=\s*\[)([^]]*)(\])", re.DOTALL)
    new_markets_str = ',\n           '.join(f"'{market}'" for market in new_markets)
    new_content = markets_pattern.sub(f"\\1{new_markets_str}\\3", content)

    with open(config_file_path, 'w') as file:
        file.write(new_content)

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

#Check if minidlna service is running
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

#Check Network speed
def speed_check():
    speed = os.popen('speedtest-cli --simple').read()
    results = speed.split('\n')
    if "Cannot" in speed:
        status = 'Internet is down or Speedtest not working properly. Please try again'
    else:
        status = results
    return(status)

#Check VPN users
def vpn_users():
    users = os.popen('pivpn list').read()
    users = users.split()[9::7]
    user_list = ['VPN users are:']
    for i in range(len(users)-1):
        user_list.append('- ' + users[i])
    user_list = '\n'.join(user_list)
    return(user_list)

#Check VPN user info
def vpn_info(vpn_user):
    users = os.popen('pivpn -c').read()
    users = users.split("\n")
    total = len(users)-3
    connected = users[2:total]
    user_db = pd.DataFrame(columns=["Name", "IP", "Virtual IP", "Received", "Sent", "Active"])
    for i in range(0, len(connected)):
        user_info = connected[i].split("      ")
        user_info = list(filter(None, user_info))
        user_db.loc[i] = [user_info[0].strip(), user_info[1].strip(), user_info[2].strip(), user_info[3].strip(), user_info[4].strip(), user_info[5].strip()]
    if vpn_user not in user_db['Name'].unique():
        user_info = ['','','','','','']
    else:
        user_info = user_db.loc[user_db['Name'] == vpn_user].values.flatten().tolist()
    return(user_info)

#Telegram message parser
def handle(msg):
    comm = msg['text'].split()
    if len(comm) == 1:
        command = comm[0]
        parameter = ''
    else:
        command = comm[0]
        parameter = comm[1]

    if msg['chat']['id'] == chat_id and command == '/reboot':
        send('Restarting RasPi, see you...')
        os.system('sudo reboot now')

    elif msg['chat']['id'] == chat_id and command == '/vpn':
        status = vpn_check()
        send('VPN service is: ' + status)

    elif msg['chat']['id'] == chat_id and command == '/dlna':
        status = dlna_check()
        send('MiniDLNA service is: ' + status)

    elif msg['chat']['id'] == chat_id and command == '/temp':
        status = temp_check()
        send('CPU temperature is: ' + status)

    elif msg['chat']['id'] == chat_id and command == '/speed':
        send('Speed test in progress. This may take 30 seconds...\n')
        status = speed_check()
        message = '- ' + status[0] + '\n' +\
                  '- ' + status[1] + '\n' +\
                  '- ' + status[2]
        send(message)

    elif msg['chat']['id'] == chat_id and command == '/hdd':
        hdd1 = '/media/USBHDD1'
        hdd2 = '/media/USBHDD2'
        message = '- HDD1 unit is: ' + hdd_check(hdd1) + '\n' +\
                  '- HDD2 unit is: ' + hdd_check(hdd2)
        send(message)

    elif msg['chat']['id'] == chat_id and command == '/reload':
        send('Indexing DLNA content. Please wait few seconds...\n')
        os.system('sudo service minidlna force-reload')

    elif msg['chat']['id'] == chat_id and command == '/vpn_users':
        message = vpn_users()
        send(message)

    elif msg['chat']['id'] == chat_id and command == '/vpn_info':
        if parameter == '':
            message = 'Please introduce user!\n'
        else:
            user_data = vpn_info(parameter)
            message = ' VPN user info:\n' +\
                    '- User: ' + user_data[0] + '\n' +\
                    '- Real IP: ' + user_data[1] + '\n' +\
                    '- Virtual IP: ' + user_data[2] + '\n' +\
                    '- Received data: ' + user_data[3] + '\n' +\
                    '- Sent data: ' + user_data[4] + '\n' +\
                    '- Last active: ' + user_data[5] + '\n'
        send(message)

    elif msg['chat']['id'] == chat_id and command == '/weather':
        os.popen('python /home/pi/personalapp/raspiapp/weathertwit.py')

    elif msg['chat']['id'] == chat_id and command == '/crypto':
        message = '#Crypto current free value:\n'
        crypto, stb = trader.crypto_status()
        for key in crypto:
            message += f'*- {key}*: {crypto[key]:.2f} {stb}\n'

        message += f'*- Total: {sum(crypto.values()):.2f} {stb}*'
        send(message, parse_mode = 'Markdown')

    elif msg['chat']['id'] == chat_id and command == '/crypto_trade':
        send('Getting latest market data. Please wait few seconds...\n')
        trader.main()

    elif msg['chat']['id'] == chat_id and command == '/crypto_markets':
        trade_config = load_trade_config()
        markets = trade_config.markets
        formatted_markets = "\n".join(f"{idx + 1}. {market}" for idx, market in enumerate(markets))
        send(f"*Current markets:*\n{formatted_markets}", parse_mode = 'Markdown')
        send("*Do you want to change a market?* (yes/no)", parse_mode = 'Markdown')
        chat_state[chat_id] = 'ask_if_change'

    elif msg['chat']['id'] == chat_id in chat_state:
        text = msg['text'].lower()
        if chat_state[chat_id] == 'ask_if_change':
            if text == 'yes':
                send("Enter the index of the market to replace and the new market (e.g., '2 XRPUSDT'):")
                chat_state[chat_id] = 'process_market_change'
            elif text == 'no':
                send("No changes will be made. Thank you!")
                del chat_state[chat_id]
            else:
                send("Invalid response. Please reply with 'yes' or 'no'.")
        
        elif chat_state[chat_id] == 'process_market_change':
            try:
                trade_config = load_trade_config()
                markets = trade_config.markets

                user_input = text.split()
                index = int(user_input[0]) - 1
                new_market = user_input[1].upper()

                if 0 <= index < len(markets):
                    old_market = markets[index]
                    markets[index] = new_market

                    # Save the updated markets list back to trade_config.py
                    update_markets(markets)

                    updated_markets = "\n".join(f"{idx + 1}. {market}" for idx, market in enumerate(markets))
                    send(f"Replaced *{old_market}* with *{new_market}*.\n*Updated markets:*\n{updated_markets}", parse_mode = 'Markdown')
                    del chat_state[chat_id]
                else:
                    send("Invalid index. Please try again.")
            except Exception as e:
                send(f"An error occurred: {str(e)}. Please try again.")
        
    elif msg['chat']['id'] == chat_id and command == '/trader_log':
        log_file = '/home/pi/personalapp/raspiapp/crypto_trader/raspitrader_cron.log'
        if os.path.exists(log_file):
            # Read last 100 lines only
            with open(log_file, 'r') as f:
                lines = f.readlines()[-100:]
            temp_file = '/tmp/raspitrader_cron_last100.log'
            with open(temp_file, 'w') as f:
                f.writelines(lines)
            send('Sending last 100 lines of raspitrader\_cron.log...')
            bot.sendDocument(chat_id, open(temp_file, 'rb'))
        else:
            send('Log file not found at /home/pi/personalapp/raspiapp/crypto_trader/raspitrader\_cron.log')

    elif msg['chat']['id'] == chat_id and command == '/update_bot':
        send('♻️ Updating and restarting Telebot...')
        os.system('/home/pi/personalapp/raspiapp/restart_telebot.sh &')

    elif msg['chat']['id'] == chat_id and command == '/telebot_log':
        log_file = '/home/pi/personalapp/raspiapp/telebot.log'
        if os.path.exists(log_file):
            # Read last 100 lines only
            with open(log_file, 'r') as f:
                lines = f.readlines()[-100:]
            temp_file = '/tmp/telebot_last100.log'
            with open(temp_file, 'w') as f:
                f.writelines(lines)
            send('Sending last 100 lines of telebot.log...')
            bot.sendDocument(chat_id, open(temp_file, 'rb'))
        else:
            send('Log file not found at /home/pi/personalapp/raspiapp/telebot.log')
    
    elif msg['chat']['id'] == chat_id and command == '/backup_log':
        log_file = '/home/pi/rsync-backup.log'
        if os.path.exists(log_file):
            # Read last 100 lines only
            with open(log_file, 'r') as f:
                lines = f.readlines()[-100:]
            temp_file = '/tmp/rsync-backup_last100.log'
            with open(temp_file, 'w') as f:
                f.writelines(lines)
            send('Sending last 100 lines of rsync-backup.log...')
            bot.sendDocument(chat_id, open(temp_file, 'rb'))
        else:
            send('Log file not found at /home/pi/rsync-backup.log')


    elif msg['chat']['id'] == chat_id and command == '/help':
        message = (
            '*These are the commands available:*\n'
            '/update\_bot → Update Telebot service.\n'
            '/weather → Get 3-day weather forcast.\n'
            '/reboot → Reboot Raspi.\n'
            '/vpn → VPN service status.\n'
            '/vpn\_users → Get list of VPN users.\n'
            '/vpn\_info user → Get info about VPN users.\n'
            '/hdd → HDD units status.\n'
            '/dlna → MiniDLNA service status.\n'
            '/temp → CPU temperature.\n'
            '/speed → Network speed test.\n'
            '/reload → Index miniDLNA catalog.\n'
            '/crypto → Get crypto wallet info.\n'
            '/crypto\_trade → Get crypto market.\n'
            '/crypto\_markets → Configure markets.\n'
            '/trader\_log → Send the raspitrader log file.\n'
            '/telebot\_log → Send the telebot log file.\n'
            '/backup\_log → Send the Rsync log file.\n'
        )
        send(message)

def send(text):
    bot.sendMessage(chat_id, text, parse_mode='Markdown')

#Telegram message
bot = telepot.Bot(telegram_key)
send("✅ Pagola RasPi Telebot is back online.")
bot.message_loop(handle)

while 1:
    time.sleep(10)
