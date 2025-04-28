#!/usr/bin/env python

import pandas as pd # type: ignore
import trade_config as config
import time
from datetime import datetime, timezone
start_time = time.time()
from binance import Client # type: ignore
end_time = time.time()

#Binance startup
def binance():
    return (end_time - start_time)

#Init Binance client
def client():
    api_key = config.api_key
    api_secret = config.api_secret
    client = Client(api_key, api_secret)
    
    server_time = client.get_server_time()['serverTime']
    local_time = int(time.time() * 1000)
    sync_time = f'{server_time - local_time} ms'
    return client, sync_time

#Check Binance system status
def status(client):
    status = client.get_system_status()['status']
    if status == 1:
        return False
    return True

#Get historical klines
def klines(client, symbol, limit):
    klines = client.get_historical_klines(symbol=symbol, interval=config.interval, limit=limit)
    klines = pd.DataFrame(klines, columns=config.columns)
    return klines

#Get actual klines
def prices_klines(client, symbol, limit):
    klines = client.get_klines(symbol=symbol, interval=config.interval, limit=limit)
    return klines

#Switch klines to Pandas format
def klines_df(klines):
    df = pd.DataFrame(klines, columns=config.columns)
    # Convert timestamp to datetime and set as index
    df['timestamp'] = pd.to_datetime(df['timestamp'], unit='ms')
    df.set_index('timestamp', inplace=True)
    return df

#Get symbol ticker
def ticker(client, symbol, retries=3, delay=2):
    for attempt in range(1, retries + 1):
        try:
            result = client.get_symbol_ticker(symbol=symbol)  
            if isinstance(result, dict) and 'price' in result:
                return result['price']
            else:
                print(f"[ERROR] Ticker missing 'price' for {symbol}: {result}")
        except Exception as e:
            print(f"[ERROR] Attempt {attempt}: exception getting ticker for {symbol}: {e}")
        time.sleep(delay)
    print(f"[CRITICAL] Failed to retrieve valid ticker for {symbol} after {retries} retries.")
    return None

#Get symbol stats
def stats(client, symbol):
    stats = client.get_ticker(symbol=symbol)
    return stats

#Get symbol orders
def orders(client, symbol):
    orders = client.get_all_orders(symbol=symbol)
    try:
        message = '%.5g' % float(orders[-1]['price'])
    except:
        message = 'n/a'
    return message
    
def get_orders(client, symbol):
    orders = client.get_all_orders(symbol=symbol, limit=1)
    return orders

#Get available assets
def assets(client):
    info = client.get_account()
    asset_name = [sub['asset'] for sub in info['balances'] if float(sub['free']) > 0
                  if sub['asset'] != 'ETHW' if sub['asset'] != config.stbc]
    asset_name = [name[2:] if 'LD' in name else name for name in asset_name]
    asset_quantity = [sub['free'] for sub in info['balances'] if(float(sub['free']) > 0)
                      if sub['asset'] != 'ETHW' if sub['asset'] != config.stbc]
    symbols_name = [name + config.stbc for name in asset_name]
    symbols_price = [client.get_avg_price(symbol=sym)['price'] for sym in symbols_name]
    assets = dict(zip(asset_name, asset_quantity))
    symbols = dict(zip(symbols_name, symbols_price))
    return (assets, symbols)

#Get asset value
def value(client, symbol):
    symbol_price = float(client.get_avg_price(symbol=symbol)['price'])
    asset_names = [symbol[:3], 'LD' + symbol[:3]]
    quantity = 0
    for asset in asset_names:
        try:
            quantity += float(client.get_asset_balance(asset=asset)['free'])
        except TypeError:
            quantity += 0
    value = symbol_price * quantity
    return value

#Get stable coin quantity
def coin(client):
    try:
        quantity = float(client.get_asset_balance(asset=config.stbc)['free'])
    except TypeError:
        quantity = 0
    return quantity

#Get asset balance
def get_balance(client, asset):
    try:
        return float(client.get_asset_balance(asset=asset)['free'])
    except Exception as e:
        print(f"[ERROR] Failed to get balance for {asset}: {e}")
        return 0.0

#Market closing time
def closing_time(client):
    # Fetch candlestick data for the symbol
    candles = client.get_klines(symbol='BTC'+config.stbc, interval=config.interval)
    
    # Extract the closing time from the last candlestick
    closing_time = candles[-1][0]  # Timestamp of close time in milliseconds
    closing_time = datetime.fromtimestamp(closing_time / 1000, tz=timezone.utc)  
    closing_time_str = closing_time.strftime('%d/%m/%Y @ %H:%M')
    
    return closing_time_str

#Get total balance in EUR
def total_balance(client):
    account_info = client.get_account()
    all_prices = {item['symbol']: float(item['price']) for item in client.get_all_tickers()}
    
    total_balance_stbc = 0
    filtered_assets = []

    for asset in account_info['balances']:
        asset_name = asset['asset']
        free = float(asset['free'])
        locked = float(asset['locked'])
        balance = free + locked

        if balance == 0 or asset_name == 'ETHW':
            continue

        if asset_name == config.stbc:
            if balance >= 5:
                total_balance_stbc += balance
                filtered_assets.append(asset_name)
            continue

        try:
            if asset_name.startswith('LD'):
                # Don't include in filtered_assets, but compute value
                stripped_name = asset_name[2:]
                market_symbol = f"{stripped_name}{config.stbc}"
                if market_symbol in all_prices:
                    price = all_prices[market_symbol]
                    asset_value = balance * price
                    total_balance_stbc += asset_value
                continue  # Skip adding to filtered_assets

            # Normal asset
            market_symbol = f"{asset_name}{config.stbc}"
            if market_symbol in all_prices:
                price = all_prices[market_symbol]
                asset_value = balance * price

                if asset_value >= 5:
                    total_balance_stbc += asset_value
                    filtered_assets.append(asset_name)
        except Exception as e:
            print(f"[WARN] Skipping asset {asset_name}: {e}")

    # Convert to EUR equivalent
    try:
        eur_pair = f"EUR{config.stbc}"
        eur_price = all_prices.get(eur_pair, 1.0)
        total_balance_eur = total_balance_stbc / eur_price
    except:
        total_balance_eur = 0

    return total_balance_eur, filtered_assets
