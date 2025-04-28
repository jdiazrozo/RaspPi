#!/usr/bin/env python

import requests
from datetime import datetime, timedelta
import numpy as np
import pandas as pd # type: ignore
import trade_config as config
import trade_pred as pred
from trade_utils import debug, DEBUG_MODE

#Compute Heikin-Ashi close prices from OHLC data
def heikin_ashi_close(df):
    return ((df['open'].astype(float) + df['high'].astype(float) +
             df['low'].astype(float) + df['close'].astype(float)) / 4).rolling(2).mean().dropna()

#Market trend
def market_trend(ticker_stats):
    # Extract relevant information
    price_change_percent = float(ticker_stats['priceChangePercent'])

    # Determine trend based on price change percent
    if price_change_percent > config.trend_buy:
        suggestion = f'🟢 _(24h trend: {price_change_percent:.2f}%)_'
        trend_tag = 'Buy'
    elif price_change_percent < config.trend_sell:
        suggestion = f'🔴 _(24h trend: {price_change_percent:.2f}%)_'
        trend_tag = 'Sell'
    else:
        suggestion = f'🟡 _(24h trend: {price_change_percent:.2f}%)_'
        trend_tag = 'Hold'

    return (suggestion, trend_tag)

#EMA Death Cross calculation
def calculate_ema(data, periods):
    return data.ewm(span=periods, adjust=False).mean()

def check_cross(klines):
    ema_long = calculate_ema(klines['close'], config.ema_long)
    ema_mid = calculate_ema(klines['close'], config.ema_mid)
    ema_short = calculate_ema(klines['close'], config.ema_short)

    # Cross detection remains, for tagging
    suggestion_cross = '🟡 _(EMA Cross)_'
    crossover_tag = 'Hold'

    short_cross_mid = (ema_short[-1] < ema_mid[-1]) & (ema_short[-2] >= ema_mid[-2])
    short_cross_mid_buy = (ema_short[-1] > ema_mid[-1]) & (ema_short[-2] <= ema_mid[-2])

    short_cross_long = (ema_short[-1] < ema_long[-1]) & (ema_short[-2] >= ema_long[-2])
    short_cross_long_buy = (ema_short[-1] > ema_long[-1]) & (ema_short[-2] <= ema_long[-2])

    if short_cross_mid.any():
        crossover_tag = 'Sell'
        suggestion_cross = '🔴 _(EMA Cross Short)_'
    elif short_cross_mid_buy.any():
        crossover_tag = 'Buy'
        suggestion_cross = '🟢 _(EMA Cross Short)_'

    if short_cross_long.any():
        crossover_tag = 'Sell'
        suggestion_cross = '🔴 _(EMA Cross Long)_'
    elif short_cross_long_buy.any():
        crossover_tag = 'Buy'
        suggestion_cross = '🟢 _(EMA Cross Long)_'

    # Trend confirmation logic (replaces one-time crossover signal)
    tolerance = 0.001 * float(klines['close'].iloc[-1])  # 0.1% price tolerance

    if abs(ema_short.iloc[-1] - ema_long.iloc[-1]) < tolerance:
        tag = 'Hold'
        suggestion_trend = '🟡 _(Trend EMA: Flat)_'
    elif ema_short.iloc[-1] > ema_long.iloc[-1]:
        tag = 'Buy'
        suggestion_trend = '🟢 _(Trend EMA: Bullish)_'
    else:
        tag = 'Sell'
        suggestion_trend = '🔴 _(Trend EMA: Bearish)_'

    return suggestion_trend, suggestion_cross, tag, crossover_tag


#Bollinger Bands strategy
def bollinger_bands(klines, window_size=config.boll_candles):

    # Extract close prices
    close_prices = klines['close'].astype(float)
    rolling_mean = close_prices.rolling(window=window_size).mean()
    rolling_std = close_prices.rolling(window=window_size).std()
    upper_band = rolling_mean + (rolling_std * 2)
    lower_band = rolling_mean - (rolling_std * 2)

    # Get the most recent close price
    current_close_price = close_prices.iloc[-1]

    # Calculate band spread (volatility proxy)
    band_spread = upper_band.iloc[-1] - lower_band.iloc[-1]
    min_spread = 0.005 * current_close_price  # 0.5% of price

    if band_spread < min_spread:
        tag = 'Hold'
        suggestion = '🟡 _(Bollinger - low spread)_'

    elif current_close_price > upper_band.iloc[-1]:
        tag = 'Sell'
        suggestion = '🔴 _(Bollinger)_'
    elif current_close_price < lower_band.iloc[-1]:
        tag = 'Buy'
        suggestion = '🟢 _(Bollinger)_'
    else:
        tag = 'Hold'
        suggestion = '🟡 _(Bollinger)_'

    return (suggestion, tag)

#RSI
def rsi(klines_df, vol, period=config.rsi_period):
    ha_close = heikin_ashi_close(klines_df)
    close_prices = ha_close.values.astype(float)
    
    # Compute deltas
    deltas = np.diff(close_prices)
    up = np.maximum(0, deltas)
    down = np.maximum(0, -deltas)

    # Avoid zero-division on first RS calc
    avg_up = np.mean(up[:period])
    avg_down = np.mean(down[:period])
    if avg_down == 0:
        rs = np.inf
    else:
        rs = avg_up / avg_down

    rsi = np.zeros_like(close_prices)
    rsi[:period] = 100. - 100. / (1. + rs)

    for i in range(period, len(close_prices)):
        delta = deltas[i - 1]
        if delta > 0:
            avg_up = (avg_up * (period - 1) + delta) / period
            avg_down = (avg_down * (period - 1)) / period
        else:
            avg_down = (avg_down * (period - 1) - delta) / period
            avg_up = (avg_up * (period - 1)) / period

        if avg_down == 0:
            rs = np.inf
        else:
            rs = avg_up / avg_down

        rsi[i] = 100. - 100. / (1. + rs)

    rsi_value = rsi[-1]

    # Volatility-aware threshold buffer
    buffer = 5
    if vol > config.high_volatility:
        buffer = 10
    elif vol < config.low_volatility:
        buffer = 3

    upper_threshold = 70 + buffer
    lower_threshold = 30 - buffer

    if rsi_value > upper_threshold:
        suggestion = f'🔴 _(RSI: {rsi_value:.2f})_'
        tag = 'Sell'
    elif rsi_value < lower_threshold:
        suggestion = f'🟢 _(RSI: {rsi_value:.2f})_'
        tag = 'Buy'
    else:
        suggestion = f'🟡 _(RSI: {rsi_value:.2f})_'
        tag = 'Hold'

    return (suggestion, tag)

#OBV
def OBV(klines):
    obv_values = []
    prev_obv = 0
    
    for kline in klines:
        close = float(kline[4])
        volume = float(kline[5])
        
        if close > float(kline[1]):  # Close > Open: Bullish
            obv = prev_obv + volume
        elif close < float(kline[1]):  # Close < Open: Bearish
            obv = prev_obv - volume
        else:  # Close = Open: Neutral
            obv = prev_obv
        
        obv_values.append(obv)
        prev_obv = obv

    obv_diff = obv_values[-1] - obv_values[-4]

    if obv_diff > 0:
        suggestion = '🟢 _(OBV)_'
        tag = 'Buy'
    elif obv_diff < 0:
        suggestion = '🔴 _(OBV)_'
        tag = 'Sell'
    else:
        suggestion = '🟡 _(OBV)_'
        tag = 'Hold'

    return (suggestion, tag)

#MACD
def calculate_macd(data, periods_short=config.macd_short, periods_long=config.macd_long, periods_signal=config.macd_signal):
    ha_close = heikin_ashi_close(data)
    ema_short = ha_close.ewm(span=periods_short, adjust=False).mean()
    ema_long = ha_close.ewm(span=periods_long, adjust=False).mean()
    macd_line = ema_short - ema_long
    signal_line = macd_line.ewm(span=periods_signal, adjust=False).mean()

    # Get the latest MACD and signal line values
    latest_macd = macd_line.iloc[-1]
    latest_signal = signal_line.iloc[-1]

    # Determine trade decision based on MACD crossover
    if latest_macd > latest_signal:
        suggestion = '🟢 _(MACD)_'
        tag = 'Buy'
    elif latest_macd < latest_signal:
        suggestion = '🔴 _(MACD)_'
        tag = 'Sell'
    else:
        suggestion = '🟡 _(MACD)_'
        tag = 'Hold'
    
    return (suggestion, tag)

#Bayesian prediction
def bayesian_pred(klines_df_full, mkt):
    debug(f"[START] bayesian_pred called for {mkt}")
    df = pred.fetch_binance_ohlcv(klines_df_full, extra_columns=['fgi'])
    debug(f"[DEBUG] Rows after fetching: {len(df)}")
    debug(f'[DEBUG] Example fetch DB for {mkt}:\n')
    debug(f'{df.head(20)}')
    df = pred.add_features(df)
    debug(f"[DEBUG] Rows after feature generation: {len(df)}")
    debug(f'[DEBUG] Example after add features for {mkt}:\n')
    debug(f'{df.head(20)}')
    df = pred.discretize(df, mkt)
    debug(f"[DEBUG] Rows after full discretization: {len(df)}")
    debug(f'[DEBUG] Example after discretize for {mkt}:\n')
    debug(f'{df.head(20)}')
    if df.empty:
        print(f"[WARN] Empty DataFrame after binning for {mkt}")
        return None, '🟡 _(No data)_', 'Hold', 0.0
    lookup, lookup_array, lookup_keys_list = pred.train_lookup(df)
    debug(f"[DEBUG] Lookup keys learned: {len(lookup)}")
    if not lookup:
        print(f"[WARN] No patterns learned for {mkt}")
        return None, '🟡 _(No data)_', 'Hold', 0.0
    last = df.iloc[-1]

    prob_dist = pred.predict_return_distribution(lookup, lookup_array, lookup_keys_list, last)
    if prob_dist:
        formatted_probs = ', '.join(f"{b}: {p:.2f}" for b, p in sorted(prob_dist.items()))
        debug(f"[DEBUG] {mkt} predicted bin probabilities → {formatted_probs}")
    else:
        debug(f"[DEBUG] {mkt} prediction distribution is empty")

    if not prob_dist:
        print("[INFO] No matching return distribution found.")
        return None, '🟡 _(No data)_', 'Hold', 0.0
    else:
        predicted_price, bin_returns = pred.estimate_price_from_distribution(prob_dist, last['close'])
        last_price = last['close']
        change = ((predicted_price-last_price)/last_price) * 100

        prob_buy = sum(prob for b, prob in prob_dist.items() if bin_returns.get(b, 0) > config.return_threshold)
        prob_sell = sum(prob for b, prob in prob_dist.items() if bin_returns.get(b, 0) < -config.return_threshold)

        # Tag decision directly from probabilities
        prob_hold = 1.0 - prob_buy - prob_sell

        if change > config.tolerance and prob_buy >= config.probability:
            tag = 'Buy'
        elif change < -config.tolerance and prob_sell >= config.probability:
            tag = 'Sell'
        else:
            tag = 'Hold'

        # Format suggestion based on the probabilities
        emoji_map = {'Buy': '🟢', 'Sell': '🔴', 'Hold': '🟡'}
        if tag == 'Buy':
            prediction_prob = prob_buy
        elif tag == 'Sell':
            prediction_prob = prob_sell
        else:
            prediction_prob = prob_hold

        suggestion = f"{emoji_map[tag]} _(Prob: {prediction_prob:.2f})_"


        return predicted_price, suggestion, tag, prediction_prob

#Buy and trade strategy
def margin(orders, current_price):
    suggestion = '🟡 _(Margin)_'
    tag = 'Hold'
    
    if len(orders) > 0:
        last_order = orders[0]
        last_order_type = last_order['side']  # Get the last order type (BUY or SELL)
        last_order_price = float(last_order['price'])  # Get the last order price
        upper_limit = last_order_price * config.margin_sell
        lower_limit = last_order_price * config.margin_buy
        middle_value = last_order_price * config.eq_margin

        if current_price >= upper_limit:
            suggestion = '🔴 _(Margin)_'
            tag = 'Sell'
            difference = (current_price - upper_limit) / upper_limit * 100
        elif current_price <= lower_limit:
            suggestion = '🟢 _(Margin)_'
            tag = 'Buy'
            difference = (current_price - lower_limit) / lower_limit * 100
        else:
            difference = (current_price - middle_value) / middle_value * 100
    else:
        # If there's no last order, suggest buying
        last_order_type = 'n/a'
        difference = 0

    return (suggestion, tag, last_order_type, difference)

#Fear and greed index (0-100)
def get_fear_greed_index():
    try:
        response = requests.get("https://api.alternative.me/fng/")
        if response.status_code == 200:
            data = response.json()
            fgi_value = int(data['data'][0]['value'])
            fgi_label = data['data'][0]['value_classification']
            return fgi_value, fgi_label
    except Exception as e:
        print(f"[ERROR] Failed to fetch Fear & Greed Index: {e}")

    # Fallback
    return None, 'unknown'

def fgi(fgi_value, fgi_label, profile):
    thresholds = config.fgi_thresholds[profile]
    if fgi_value is not None:
        if fgi_value <= thresholds['panic_sell']:
            suggestion = f'🔴 _(FGI: {fgi_value} → {fgi_label})_'
            tag = 'Sell'
        elif fgi_value < thresholds['buy']:
            suggestion = f'🟢 _(FGI: {fgi_value} → {fgi_label})_'
            tag = 'Buy'
        elif fgi_value > thresholds['sell']:
            suggestion = f'🔴 _(FGI: {fgi_value} → {fgi_label})_'
            tag = 'Sell'
        else:
            suggestion = f'🟡 _(FGI: {fgi_value} → {fgi_label})_'
            tag = 'Hold'
    else:
        suggestion = f'🟡 _(FGI: {fgi_value} → {fgi_label})_'
        tag = 'Hold'
    return suggestion, tag

#Get historical FGI indexes
def get_fgi_history(n_days=84):
    url = "https://api.alternative.me/fng/?limit=0&format=json"
    try:
        response = requests.get(url)
        data = response.json()['data']

        df = pd.DataFrame(data)
        df['timestamp'] = pd.to_datetime(df['timestamp'], unit='s')

        # Make both tz-naive
        df['timestamp'] = df['timestamp'].dt.tz_localize(None)
        cutoff = datetime.now().astimezone().replace(tzinfo=None) - timedelta(days=n_days)

        df['fgi'] = df['value'].astype(int)
        df = df.sort_values('timestamp')
        df = df[df['timestamp'] >= cutoff]

        return df[['timestamp', 'fgi']].set_index('timestamp')
    except Exception as e:
        print(f"[ERROR] Failed to fetch FGI history: {e}")
        return pd.DataFrame({'fgi': []})

def align_fgi_history(candle_df, fgi_df):
    # Ensure timestamp is datetime index
    if candle_df.index.name != 'timestamp':
        candle_df = candle_df.copy()
        candle_df['timestamp'] = pd.to_datetime(candle_df['timestamp'])
        candle_df = candle_df.set_index('timestamp')

    fgi_df = fgi_df.sort_index().ffill()
    merged_df = candle_df.join(fgi_df, how='left')

    merged_df['fgi'] = merged_df['fgi'].fillna(method='ffill')
    return merged_df.reset_index()

#Strong trends detection
def strong_trend(trend_tag, ema_tag, crossover_tag, macd_tag, boll_tag, rsi_tag, obv_tag, pred_tag, fgi_tag):
    
    tags = [trend_tag, ema_tag, crossover_tag, macd_tag, obv_tag, pred_tag]
    rev_tags = [boll_tag, rsi_tag, fgi_tag]

    if all(tag == 'Buy' for tag in tags) and 'Sell' not in rev_tags:
        overall_trend = 'Strong bullish 🐂'
        alert = True
    elif all(tag == 'Sell' for tag in tags) and 'Buy' not in rev_tags:
        overall_trend = 'Strong bearish 🐻'
        alert = True
    else:
        overall_trend = ''
        alert = False
    return alert, overall_trend

#Volatitilty calculation and trading profile
def calculate_volatility(df, pred_confidence, window):
    close_prices = df['close'].astype(float)
    df['log_return'] = np.log(close_prices/close_prices.shift(1))
    df.dropna(inplace=True)
    vol = df['log_return'].rolling(window).std().iloc[-1]
    if vol > config.high_volatility:
        weights = adjust_weights_by_prediction_confidence(config.weights_aggressive, pred_confidence)
        profile = 'aggressive'
        tag = '⚡'
    elif vol < config.low_volatility:
        weights = adjust_weights_by_prediction_confidence(config.weights_conservative, pred_confidence)
        profile = 'conservative'
        tag = '💤'
    else:
        weights = adjust_weights_by_prediction_confidence(config.weights_balanced, pred_confidence)
        profile = 'balanced'
        tag = '🔋'
    return weights, profile, tag, vol

#Adjuts weights based on profile and probability
def adjust_weights_by_prediction_confidence(base_weights, pred_confidence, pred_key='Pred', min_pred=5, max_pred=25):
    # Clamp prediction confidence to [0.0, 1.0]
    conf = max(0.0, min(1.0, pred_confidence))

    # Scale Pred weight linearly
    dynamic_pred_weight = int(min_pred + conf * (max_pred - min_pred))

    adjusted_weights = base_weights.copy()
    adjusted_weights[pred_key] = dynamic_pred_weight

    # Recalculate total weight of others
    total_other = sum(v for k, v in base_weights.items() if k != pred_key)
    target_other = 100 - dynamic_pred_weight

    # Rescale other weights proportionally
    for k in adjusted_weights:
        if k != pred_key:
            original = base_weights[k]
            adjusted_weights[k] = round(original / total_other * target_other)

    # Adjust for rounding error
    diff = 100 - sum(adjusted_weights.values())
    adjusted_weights[pred_key] += diff  # fix overflow/underflow

    return adjusted_weights

# Get trade decision
def combined_trade_decision(trend_tag, ema_tag, cross_tag, macd_tag, boll_tag, rsi_tag, obv_tag, margin_tag, pred_tag, fgi_tag, profile, weights):
  
    buy_threshold = config.thresholds[profile]['buy']
    sell_threshold = config.thresholds[profile]['sell']

    signals = [trend_tag, ema_tag, cross_tag, macd_tag, boll_tag, rsi_tag, obv_tag, pred_tag, margin_tag, fgi_tag]
    # Count tag votes
    buy_count = sum(1 for tag in signals if tag == 'Buy')
    sell_count = sum(1 for tag in signals if tag == 'Sell')

    mapping = {'Buy': 1, 'Sell': -1, 'Hold': 0}
    integer_list = [mapping[signal] for signal in signals]
    combined_index = [x * y for x, y in zip(integer_list, weights.values())]
    combined_decision = sum(combined_index)
    decision_index = combined_decision/sum(weights.values()) * 100
    
    if decision_index > buy_threshold and buy_count >= config.min_agreement[profile]:
        suggestion = '🟢'
    elif decision_index < sell_threshold and sell_count >= config.min_agreement[profile]:
        suggestion = '🔴'
    else:
        suggestion = '🟡'

    return (suggestion, decision_index)
