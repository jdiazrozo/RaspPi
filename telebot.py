import telepot # type: ignore
from telepot.loop import MessageLoop # type: ignore
import importlib.util
import re
import os
import time
import pandas as pd # type: ignore
import json
import shutil
import re
from io import StringIO
import sys
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
RASPITRADER_PATH = os.path.join(BASE_DIR, 'crypto_trader')
CRYPTO_VALUES_PATH = os.path.join(RASPITRADER_PATH, 'crypto_values')
sys.path.insert(0, CRYPTO_VALUES_PATH)
STATE_PATH = os.path.join(RASPITRADER_PATH, 'crypto_values/state.json')
RL_Q_PATH = os.path.join(RASPITRADER_PATH, 'crypto_values/rl_q_table.pkl')
RL_REWARD_PATH = os.path.join(RASPITRADER_PATH, 'crypto_values/rl_reward_history.pkl')
RL_VISITS_PATH = os.path.join(RASPITRADER_PATH, 'crypto_values/rl_visits.pkl')
RL_EPSILON_PATH = os.path.join(RASPITRADER_PATH, 'crypto_values/rl_epsilon.pkl')
sys.path.insert(0, RASPITRADER_PATH)

import raspitrader as trader # type: ignore
from trade_config import EPSILON as DEFAULT_EPSILON # type: ignore
import trade_utils # type: ignore
from dotenv import load_dotenv # type: ignore
load_dotenv('/home/pi/keys/.env')

config_file_path = os.path.join(RASPITRADER_PATH, 'crypto_values/trade_config.py')


chat_state = {}
chat_id = int(os.getenv("chat_id"))
telegram_key = os.getenv("telegram_key")

def load_state_json(path):
    with open(path, 'r') as f:
        return json.load(f)

def save_state_json(path, data):
    with open(path, 'w') as f:
        json.dump(data, f, indent=2)

def backup_state_file(original, backup):
    shutil.copy(original, backup)

def restore_persistance():
    try:
        if os.path.exists(STATE_PATH + '.bak'):
            shutil.copy(STATE_PATH + '.bak', STATE_PATH)
            send("✅ state.json has been restored from backup.")
        if os.path.exists(RL_Q_PATH + '.bak'):
            shutil.copy(RL_Q_PATH + '.bak', RL_Q_PATH)
            send("✅ RL Q-table restored from backup.")
        if os.path.exists(RL_REWARD_PATH + '.bak'):
            shutil.copy(RL_REWARD_PATH + '.bak', RL_REWARD_PATH)
            send("✅ RL reward history restored from backup.")
        if os.path.exists(RL_VISITS_PATH + '.bak'):
            shutil.copy(RL_VISITS_PATH + '.bak', RL_VISITS_PATH)
            send("✅ RL reward history restored from backup.")
        if os.path.exists(RL_EPSILON_PATH + '.bak'):
            shutil.copy(RL_EPSILON_PATH + '.bak', RL_EPSILON_PATH)
            send("✅ RL reward history restored from backup.")
    except Exception as e:
        send(f"⚠️ Error restoring backup: {e}")

def list_symbols_and_common_keys(path):
    state = load_state_json(path)
    symbols = list(state.keys())
    first_symbol = symbols[0] if symbols else None
    keys = list(state[first_symbol].keys()) if first_symbol else []

    listing = ["*Available symbols:*"]
    for symbol in symbols:
        listing.append(f"- `{symbol}`")

    if keys:
        listing.append("\n*Editable keys:*")
        for key in keys:
            listing.append(f"- `{key}`")

    return '\n'.join(listing)

def escape_markdown(text):
    # Escape MarkdownV2 reserved characters
    escape_chars = r'_[]()~>#+-=|{}.!'
    return re.sub(r'([%s])' % re.escape(escape_chars), r'\\\1', text)

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

# Format Q-values
def format_qvalues(buy, sell, hold):
    """Format B, S, H with colored dot emojis."""
    buy_colored = buy.replace("B:", "🟢")
    sell_colored = sell.replace("S:", "🔴")
    hold_colored = hold.replace("H:", "🟡")
    return f"{buy_colored} |{sell_colored} |{hold_colored}"

#Delete all RL persistance files
def reset_rl_files():
    """Delete all RL persistence files (Q-table, rewards, visits, epsilon)."""
    files_to_delete = [RL_Q_PATH, RL_REWARD_PATH, RL_VISITS_PATH, RL_EPSILON_PATH]
    removed = []
    for file in files_to_delete:
        try:
            if os.path.exists(file):
                os.remove(file)
                removed.append(os.path.basename(file))
        except Exception as e:
            print(f"[WARN] Failed to remove {file}: {e}")
    return removed

#Telegram message parser
def handle(msg):
    if 'location' in msg:
        lat = msg['location']['latitude']
        lon = msg['location']['longitude']
        send(f"📍 Location received: {lat:.4f}, {lon:.4f}. Fetching forecast...")
        result = os.popen(f'python /home/pi/personalapp/raspiapp/weathertwit.py {lat} {lon}').read()
        if result.strip():  # Only send output if something is returned (e.g., an error)
            send(f"⚠️ Weather script returned:\n{result}")
        return
    
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
        send('🔄 Getting latest market data. Please wait few seconds...\n')
        trader.main()
        restore_persistance()

    elif msg['chat']['id'] == chat_id and command == '/crypto_markets':
        trade_config = load_trade_config()
        markets = trade_config.markets
        formatted_markets = "\n".join(f"{idx + 1}. {market}" for idx, market in enumerate(markets))
        send(f"*Current markets:*\n{formatted_markets}")
        send("*Do you want to change a market?* (yes/no)")
        chat_state[chat_id] = 'ask_if_change'

    elif msg['chat']['id'] == chat_id and command == '/crypto_state':
        if os.path.exists(STATE_PATH):
            send('Sending state.json...')
            bot.sendDocument(chat_id, open(STATE_PATH, 'rb'))
        else:
            send('Log file not found at /home/pi/personalapp/raspiapp/crypto_trader/crypto_values/state.json')

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
            send('Sending last 100 lines of raspitrader_cron.log...')
            bot.sendDocument(chat_id, open(temp_file, 'rb'))
        else:
            send('Log file not found at /home/pi/personalapp/raspiapp/crypto_trader/raspitrader_cron.log')

    elif msg['chat']['id'] == chat_id and command == '/update_raspibot':
        send('🍊 Pulling latest updates from Git...')
        status = os.system('cd /home/pi/raspi_services && git pull origin master > /tmp/git_pull.log 2>&1')
        if status == 0:
            send('✅ Raspi Telebot Service updated successfully. Sending the log...')
            bot.sendDocument(chat_id, open('/tmp/git_pull.log', 'rb'))
        else:
            send('⚠️ Git pull failed. Sending log...')
            bot.sendDocument(chat_id, open('/tmp/git_pull.log', 'rb'))
        send('♻️ Restarting Telebot...')
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

    elif msg['chat']['id'] == chat_id and command == '/update_trader':
        send('🍊 Pulling latest updates from Git...')
        status = os.system('cd /home/pi/crypto_trader && git pull origin master > /tmp/git_pull.log 2>&1')
        if status == 0:
            send('✅ Crypto Trader update completed successfully. Sending the log...')
            bot.sendDocument(chat_id, open('/tmp/git_pull.log', 'rb'))
        else:
            send('⚠️ Git pull failed. Sending log...')
            bot.sendDocument(chat_id, open('/tmp/git_pull.log', 'rb'))

    elif msg['chat']['id'] == chat_id and command == '/set_state':
        try:
            if len(comm) != 4:
                send(
                    "Usage: /set_state <symbol> <key> <value>\n" \
                    "Example: /set_state BTCUSDC cumulative_profit 42.0\n" \
                    "Use /list_state_keys to view available options."
                    )
            else:
                symbol, key, raw_value = comm[1], comm[2], comm[3]

                state = load_state_json(STATE_PATH)
                if symbol not in state:
                    send(f"❌ Symbol `{symbol}` not found.\nUse /list_state_keys to view valid options.")
                    return
                if key not in state[symbol]:
                    send(f"❌ Key `{key}` not found in `{symbol}`.\nUse /list_state_keys to view valid options.")
                    return

                # Detect type from existing value
                old_value = state[symbol][key]
                if isinstance(old_value, bool):
                    if raw_value.lower() not in ['true', 'false']:
                        send(f"❌ Invalid boolean. Use `true` or `false` for `{key}`.")
                        return
                    new_value = raw_value.lower() == 'true'
                elif isinstance(old_value, (int, float)):
                    try:
                        new_value = type(old_value)(raw_value)
                    except ValueError:
                        send(f"❌ Invalid numeric input. Expected {type(old_value).__name__} for `{key}`.")
                        return
                elif isinstance(old_value, str):
                    new_value = raw_value
                else:
                    send("❌ Unsupported key type.")
                    return

                # Backup before update
                backup_file = STATE_PATH + '.bak'
                backup_state_file(STATE_PATH, backup_file)

                # Save new value
                state[symbol][key] = new_value
                save_state_json(STATE_PATH, state)

                send(f"✅ Updated `{symbol}` → `{key}`: `{old_value}` → `{new_value}`\nBackup saved at `{backup_file}`")

        except Exception as e:
            send(f"⚠️ Error: {e}")

    elif msg['chat']['id'] == chat_id and command == '/list_state_keys':
        try:
            message = list_symbols_and_common_keys(STATE_PATH)
            send(message)
        except Exception as e:
            send(f"⚠️ Error retrieving symbols and keys: {e}")

    elif msg['chat']['id'] == chat_id and command == '/restore_persistance':
        restore_persistance()
        send("✅ Backups (State, Q-table and reward history) restored.")

    elif msg['chat']['id'] == chat_id and command == '/rl_performance':
        try:
            # Load Q-table and rewards
            from trade_rl import load_q_table, _reward_history # type: ignore
            from trade_utils import load_rl_epsilon # type: ignore

            load_q_table()  # Load Q-values
            # Explicitly reload reward history
            _reward_history.clear()
            _reward_history.update(trade_utils.load_rl_rewards())

            # Load state.json
            state = load_state_json(STATE_PATH)

            # Capture the printed output of global_performance
            buffer = StringIO()
            backup_stdout = sys.stdout
            sys.stdout = buffer
            trade_utils.global_performance(state)
            sys.stdout = backup_stdout


            lines = buffer.getvalue().splitlines()

            # Format markets for Telegram
            formatted_message = []
            for line in lines[2:]:  # Skip [SUMMARY] and ------
                if not line.strip():
                    continue

                # Handle "No RL data"
                if "No RL data" in line:
                    # Extract only the market and profit part (before '|')
                    market_info = line.split("|")[0].strip()
                    formatted_message.append(f"*{market_info}*\n- No RL data")
                    continue

                # Split into parts
                parts = [p.strip() for p in line.split("|") if p.strip()]

                if len(parts) == 6:
                    market_info, buy, sell, hold, visits, reward = parts
                    reward_colored = reward.replace("R", "🏆")
                    visits_colored = visits.replace("V:", "📊 ")
                    formatted_message.append(
                        f"*{market_info}*\n- {format_qvalues(buy, sell, hold)}\n- {reward_colored} | {visits_colored}"
                    )
                elif len(parts) == 5:
                    market_info, buy, sell, hold, visits = parts
                    visits_colored = visits.replace("V:", "📊 ")
                    formatted_message.append(
                        f"*{market_info}*\n- {format_qvalues(buy, sell, hold)}\n- {visits_colored}"
                    )
                elif len(parts) == 4:
                    market_info, buy, sell, hold = parts
                    formatted_message.append(
                        f"*{market_info}*\n- {format_qvalues(buy, sell, hold)}"
                    )
                else:
                    formatted_message.append(line)

            current_epsilon = load_rl_epsilon(DEFAULT_EPSILON)
            message_to_send = f"*#Reinforcement Learning Performance:*\n*(EPSILON={current_epsilon:.3f})*\n" + "\n".join(formatted_message)
            send(message_to_send)
        except Exception as e:
            send(f"⚠️ Error generating RL performance: {e}")

    elif msg['chat']['id'] == chat_id and command == '/reset_rl':
        removed_files = reset_rl_files()
        if removed_files:
            send(f"✅ RL data reset. Deleted: {', '.join(removed_files)}")
        else:
            send("ℹ️ No RL persistence files found to delete.")
    
    elif msg['chat']['id'] == chat_id and command == '/help':
        message = (
            '*General Raspi services commands available:*\n'
            '/update_raspibot → Update Telebot service.\n'
            '/reboot → Reboot Raspi.\n'
            '/vpn → VPN service status.\n'
            '/vpn_users → Get list of VPN users.\n'
            '/vpn_info user → Get info about VPN users.\n'
            '/hdd → HDD units status.\n'
            '/dlna → MiniDLNA service status.\n'
            '/temp → CPU temperature.\n'
            '/reload → Index miniDLNA catalog.\n'
            '/telebot_log → Send the telebot log file.\n'
            '/backup_log → Send the Rsync log file.\n'
            '\n*Information commands available:*\n'
            '/speed → Network speed test.\n'
            '/weather → Get 3-day weather forcast.\n'
            '\n*Crypto trading commands available:*\n'
            '/update_trader → Update Trader bot.\n'
            '/crypto → Get crypto wallet positions.\n'
            '/crypto_trade → Get crypto market analysis.\n'
            '/crypto_state → Get state.json.\n'
            '/list_state_keys → List of keys in json.\n'
            '/set_state → <symbol> <key> <value>.\n'
            '/restore_persistance → Restore backups.\n'
            '/crypto_markets → Configure markets.\n'
            '/trader_log → Send the raspitrader log file.\n'
            '/rl_performance → Get RL performance.\n'
            '/reset_rl → Reset persistance RL.\n'
        )
        send(message)

def send(text):
    escaped_text = escape_markdown(text)
    bot.sendMessage(chat_id, escaped_text, parse_mode='MarkdownV2')

#Telegram message
bot = telepot.Bot(telegram_key)
send("✅ Pagola RasPi Telebot is back online.")
bot.message_loop(handle)

while 1:
    time.sleep(10)
