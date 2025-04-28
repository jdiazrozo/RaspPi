#!/usr/bin/env python

import time as t
from datetime import datetime
import concurrent.futures
import sys
import random
import argparse
sys.path.insert(0, '/home/pi/personalapp/raspiapp/crypto_values')
import trade_config as config # type: ignore
import binance_init as bint # type: ignore
import trading_scripts as strategy # type: ignore
import comms as comms # type: ignore
import trade_utils # type: ignore


parser = argparse.ArgumentParser(description="Run crypto trading predictor.")
parser.add_argument("--debug", action="store_true", help="Enable debug mode")
parser.add_argument("--flush-cache", action="store_true", help="Delete saved bin_cache before analysis")
parser.add_argument("--flush-only", action="store_true", help="Only flush cache and exit")
args = parser.parse_args()

trade_utils.DEBUG_MODE = args.debug

if args.flush_cache:
    trade_utils.flush_bin_cache()

if args.flush_only:
    trade_utils.flush_bin_cache()
    exit(0)

#Get market status
def market_status(market, mkt_option, mkt_index, margin_tag, last_order_type, difference, volatility):
    # Format difference with sign and leading zero
    diff_str = f"{difference:+03.0f}%"

    # Determine margin label
    if margin_tag == 'Sell':
        if last_order_type == 'BUY':
            margin_opt = f'*TP:  {diff_str}*'
        elif last_order_type == 'SELL':
            margin_opt = f'_TP:  {diff_str}_'
        else:
            margin_opt = f'_TP:  {diff_str}_'  # Fallback
    elif margin_tag == 'Buy':
        if last_order_type in ['SELL', 'N/A'] and mkt_option != '🔴':
            margin_opt = f'*BS:  {diff_str}*'
        elif last_order_type == 'BUY' and mkt_option != '🔴':
            margin_opt = f'_BS:  {diff_str}_'
        else:
            margin_opt = f'_BS:  {diff_str}_'  # Fallback
    else:
        margin_opt = f'_NTZ: {diff_str}_'

    # Format market name with non-breaking spaces for consistent width
    market_fmt = f'#{market:<8}'.replace(' ', '\u00A0')

    # Format mkt_index nicely (always +03.0f with sign and fixed width)
    index_fmt = f'{mkt_index:+03.0f}%'

    # Build final line
    if mkt_option != '🟡':
        message = f'{volatility} *{market_fmt}* *{index_fmt}* → {mkt_option} ({margin_opt})\n'
    else:
        message = f'{volatility} *{market_fmt}*  {index_fmt}  → {mkt_option} ({margin_opt})\n'

    return message

#Trade message based on strategy
def trade_message(client, mkt, suggestion, ticker, last_order_type, value_to_sell):
    warning = f'*#{mkt}:*\n'
    warning += suggestion
    warning += f'→ Average price: {ticker:.5g} {config.stbc}\n'
    warning += f'→ Position: {value_to_sell:.2f} {config.stbc}\n'
    warning += f'→ Last trade price: {bint.orders(client, mkt)} {config.stbc}\n' 
    warning += f'→ Last order type: {last_order_type}\n'
    return warning

#Crypto status
def crypto_status():
    client = bint.client()
    ass, sym = bint.assets(client)
    position = {list(ass.keys())[i]: float(list(ass.values())[i]) * float(list(sym.values())[i])
                for i in range(len(ass))}
    position[config.stbc] = bint.coin(client)
    return position, config.stbc

def get_market_data(client, mkt):
    for _ in range(2):  # Retry once more if an exception occurs
        try:
            klines_full = bint.prices_klines(client, mkt, config.pred_horizon)
            klines_df_full = bint.klines_df(klines_full)
            klines = klines_full[-config.candles:]
            klines_df = bint.klines_df(klines)
            orders = bint.get_orders(client, mkt)
            ticker_data = bint.ticker(client, mkt)
            try:
                ticker = float(ticker_data)
            except (TypeError, ValueError):
                print(f"[ERROR] Invalid ticker value for {mkt}: {ticker_data}")
                return None, None, None, None, None, None, f'Error retrieving ticker for {mkt}\n'
            stats = bint.stats(client, mkt)
            return klines, klines_df, klines_df_full, orders, ticker, stats, ''
        except Exception as ex:
            e = ex
            print(f"Error getting {mkt} data: {e}")
            t.sleep(1)  # Wait for a second before retrying
    return None, None, None, None, None, None, f'Error binance_init functions: {e} for {mkt}\n'

def get_data_analysis(mkt, klines, klines_df, klines_df_full, orders, ticker, stats):
    for _ in range(2):  # Retry once more if an exception occurs
        try:
            trend, trend_tag = strategy.market_trend(stats)
            ema_trend, ema_cross, ema_tag, crossover_tag = strategy.check_cross(klines_df)
            bollinger, boll_tag = strategy.bollinger_bands(klines_df)
            obv, obv_tag = strategy.OBV(klines)
            macd, macd_tag = strategy.calculate_macd(klines_df)
            pred_price, pred, pred_tag, probability = strategy.bayesian_pred(klines_df_full, mkt)
            trade_utils.debug(f"[DEBUG] Prediction output for {mkt}: {pred_price}, {pred}, {pred_tag}, {probability}")
            margin, margin_tag, last_order_type, difference = strategy.margin(orders, ticker)
            weigths, profile, vol_tag, vol = strategy.calculate_volatility(klines_df, probability, config.volatility)
            rsi, rsi_tag = strategy.rsi(klines_df, vol)
            return trend, trend_tag, ema_trend, ema_cross, ema_tag, crossover_tag, bollinger, boll_tag, rsi, rsi_tag, obv, obv_tag, macd, macd_tag, pred, pred_tag, margin, margin_tag, last_order_type, difference, weigths, profile, vol_tag, ''
        except Exception as ex:
            e = ex
            print(f"Error analyzing {mkt} trading data: {e}\n")
            t.sleep(1)  # Wait for a second before retrying
    return None, None, None, None, None, None, None, None, None, None, None, None, None, None, None, None, None, None, None, None, None, None, None, f'Error trading_scripts functions: {e} for {mkt}\n'


# Market analysis
def analyze_market(client, mkt, fgi_value, fgi_label, fgi_series):
    # Get market data
    klines, klines_df, klines_df_full, orders, ticker, stats, error_handler = get_market_data(client, mkt)
    if error_handler:
        return error_handler, False, ''

    # Align data with historical fgi
    klines_df_full = strategy.align_fgi_history(klines_df_full, fgi_series)

    # Initialize suggestion and alert flag
    suggestion = ''
    alert = False

    # Execute data functions
    trend, trend_tag, ema_trend, ema_cross, ema_tag, crossover_tag, bollinger, boll_tag, rsi, rsi_tag, obv, obv_tag, macd, macd_tag, pred, pred_tag, margin, margin_tag, last_order_type, difference, weigths, profile, vol_tag, error_handler = get_data_analysis(mkt, klines, klines_df, klines_df_full, orders, ticker, stats)
    if error_handler:
        return error_handler, False, ''

    # Get market feed and greed information
    fgi, fgi_tag = strategy.fgi(fgi_value, fgi_label, profile)

    # Get available asset position at the market
    asset = mkt.replace(config.stbc, '')
    balance_asset = bint.get_balance(client, asset)
    balance_stable = bint.get_balance(client, config.stbc)
    value_to_sell = balance_asset * ticker

    # Get strong market trends
    overall_alert, overall_trend = strategy.strong_trend(trend_tag, ema_tag, crossover_tag, macd_tag, boll_tag, rsi_tag, obv_tag, pred_tag, fgi_tag)

    # Get a combined criteria
    mkt_option, mkt_index = strategy.combined_trade_decision(trend_tag, ema_tag, crossover_tag, macd_tag, boll_tag, rsi_tag, obv_tag, margin_tag, pred_tag, fgi_tag, profile, weigths)

    # Check if trade is feasible based on wallet balances
    if mkt_option == '🟢' and balance_stable < config.min_trade:
        suggestion += f'😢*Not possible to {mkt_option}!*\n' 
        suggestion += f'*Only {balance_stable:.2f} {config.stbc}*\n'
        mkt_option = '🚫'
    elif mkt_option == '🔴' and value_to_sell < config.min_trade:
        suggestion += f'😢*Not possible to {mkt_option}!*\n'
        suggestion += f'*Only {value_to_sell:.2f} {config.stbc} in {asset}*\n'
        mkt_option = '🚫'
    else:
        suggestion += f'*Recommendation is: {mkt_option}*\n'


    # Generate suggestion
    if overall_alert:
        suggestion += f'*-------------------------*\n'
        suggestion += f'*{overall_trend} detected!*\n'
        suggestion += f'*-------------------------*\n'
        alert = True

    if mkt_option != '🟡':
        suggestion += f'{trend}\n{ema_trend}\n{ema_cross}\n{bollinger}\n{rsi}\n{macd}\n{obv}\n{margin}\n{pred}\n{fgi}\n'
        alert = True

    # Generate warning and update
    if alert:
        warning = trade_message(client, mkt, suggestion, ticker, last_order_type, value_to_sell)
        warn = True
    else:
        warn = False
        warning = ''

    update = market_status(mkt, mkt_option, mkt_index, margin_tag, last_order_type, difference, vol_tag)

    return update, warn, warning

# Function to submit tasks with retry
def submit_task(executor, func, *args):
    for _ in range(2):  # Retry once more if an exception occurs
        try:
            future = executor.submit(func, *args)
            return future
        except Exception as e:
            print(f"Error submitting task: {e}")
            t.sleep(1)  # Wait for a second before retrying
    return None

# Function to retrieve results with retry
def retrieve_result(future,symbol):
    for _ in range(2):  # Retry once more if an exception occurs
        try:
            update, warn, warning = future.result()  # Retrieve result
            return update, warn, warning
        except Exception as e:
            print(f"Error retrieving result: {e}")
            t.sleep(1)  # Wait for a second before retrying
    return f"Failed to retrieve result for {symbol}\n", False, ''

#Main
def main():
    #Get general Binance account information
    current_time = datetime.now().strftime('%d/%m/%Y @ %H:%M')
    print(f'---------------------')
    print(f'Date: {current_time}')
    connection_time_start = t.time()
    client, sync_time = bint.client()
    connection_time_stop = t.time()
    print(f"Binance sync: {sync_time}")
    connection_time = (connection_time_stop - connection_time_start) + bint.binance()
    print(f"Connected to Binance in {connection_time * 1000:.0f} ms")
        
    data_time = bint.closing_time(client)
    balance_eur, asset_names = bint.total_balance(client)
    asset_names = ', '.join(asset_names)

    #Get contextual data
    n_days = trade_utils.get_required_fgi_days(config.interval, config.pred_horizon)
    fgi_value, fgi_label = strategy.get_fear_greed_index()
    fgi_series = strategy.get_fgi_history(n_days=n_days)
    trade_utils.debug(f'[DEBUG] FGI obatined with value {fgi_value} and label {fgi_label}')
    trade_utils.debug(f'[DEBUG] Example of FGI historical obtained for {n_days}:\n')
    trade_utils.debug(f'{fgi_series.head(20)}')

    start_time = t.time()  # Start measuring processing time
    # Create thread pool executor
    with concurrent.futures.ThreadPoolExecutor(max_workers=len(config.markets)) as executor:
        # Submit tasks for each symbol with retry
        future_to_symbol = {}
        for symbol in config.markets:
            random_delay = random.uniform(0.01, 0.05)  # Random delay in seconds
            t.sleep(random_delay)  # Introduce random delay before submitting task
            future = submit_task(executor, analyze_market, client, symbol, fgi_value, fgi_label, fgi_series)
            if future:
                future_to_symbol[future] = symbol

        # Accumulate results in a dictionary
        results_dict = {symbol: None for symbol in config.markets}
        for future in concurrent.futures.as_completed(future_to_symbol):
            symbol = future_to_symbol[future]
            update, warn, warning = retrieve_result(future, symbol)
            results_dict[symbol] = (update, warn, warning)

    # Accumulate updates and warnings in the same order as config.markets
    updates = ''
    warnings = '🔥*#CryptoMarket Warning!*\nTrade suggestion detected for:\n'
    for symbol in config.markets:
        update, warn, warning = results_dict[symbol]
        updates += update
        if warn:
            warnings += warning


    end_time = t.time()  # Stop measuring processing time
    analysis_time = (end_time - start_time)
    print(f"Processing time: {analysis_time * 1000:.0f} ms")
    print(f'---------------------')

    message = (
    f'🚀 *#Crypto trade analysis with {config.interval} interval:*\n'
    f'Fear & Greed index: *{fgi_value} → {fgi_label}*\n'
    f'Market closed: *{data_time} UTC*\n'
    f'Assets in SPOT wallet: *{asset_names}*\n'
    f'Account balance: *{balance_eur:.2f} €*\n'
    f'*Market status:*\n'
    )

    message += updates
    message += f'*---------------------------------*\n'
    message += f'⌛ Market analysis time: *{analysis_time:.1f} s*\n'
    comms.telegram(message)
    t.sleep(5)
    if warnings != '🔥*#CryptoMarket Warning!*\nTrade suggestion detected for:\n':
        comms.telegram(warnings)

if __name__ == "__main__":
    main()
