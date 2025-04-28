#!/usr/bin/env python

#Keys
api_key = 'C86e5Gz71BpqD5l8CdOsUCn16xblHeMhR3cT2MMGQ7jw3wkffkSXJXR09CtyJqAx'
api_secret = 'S8PWZiyy0TA1zdGjVXu5JsGbKMXSdld2ndNREqJ3ST8P60QJokmXiOfkde4bqg18'
telegram_key = '1228874624:AAEkMwsunE4BLoFndVIowKlAUnqcCYEeR78'

#Paths
path = '/home/pi/personalapp/raspiapp/crypto_values/'
file_ext = 'avg_values.txt'


#Symbols

markets = ['BTCUSDC',
           'ETHUSDC',
 #          'ETHBTC',
           'ADAUSDC',
 #          'ADABTC',
           'AVAXUSDC',
           'BNBUSDC',
           'DOTUSDC',
           'SOLUSDC',
#           'SOLBTC',
           'TRXUSDC',
           'XRPUSDC',
           'LINKUSDC']
 #          'EURUSDC']

'''
markets = ['BTCUSDC']
'''



#Stable coin
stbc = 'USDC'

#Analysis interval
interval = '4h'

#Minimum amounts to trade
min_trade = 6

#Klines columns
columns=["timestamp", "open", "high", "low", "close", "volume", "close_time",  "quote_asset_volume", "number_of_trades", "taker_buy_base_asset_volume", "taker_buy_quote_asset_volume", "ignore"]

#Parameters for trade strategies
pred_horizon = 500
candles = 100
ema_long = 99
ema_mid = 25
ema_short = 7
boll_candles = 20
rsi_period = 9
macd_short = 12
macd_long = 26
macd_signal = 9

#Trade weights
# Conservative Profile – Trend-Driven, Risk-Averse
weights_conservative = {
    'Trend': 22,
    'EMA': 16,
    'EMA Crossover': 5,
    'MACD': 14,
    'Bollinger': 6,
    'RSI': 6,
    'OBV': 10,
    'Pred': 12,
    'Margin': 4,
    'FGI': 5
}

# Balanced Profile – Good Mix of Momentum, Volume & Prediction
weights_balanced = {
    'Trend': 15,
    'EMA': 14,
    'EMA Crossover': 6,
    'MACD': 12,
    'Bollinger': 6,
    'RSI': 8,
    'OBV': 8,
    'Pred': 20,
    'Margin': 6,
    'FGI': 5
}

#Aggressive Profile – Fast-Adaptive, Bayesian-Driven
weights_aggressive = {
    'Trend': 8,
    'EMA': 10,
    'EMA Crossover': 5,
    'MACD': 12,
    'Bollinger': 6,
    'RSI': 9,
    'OBV': 10,
    'Pred': 30,
    'Margin': 5,
    'FGI': 5
}

#Combined decision index
buy_threshold = 15
sell_threshold = -15

#Bayesian tolerance for prediction in %
BIN_CACHE_TTL = 86400  # 24 hours in seconds
desired_bins = 4
tolerance = 0.1 #Value in percentage
return_threshold = 0.001
min_matches = 5

#Prediction probability threshold
probability = 0.6

#Volatility window
volatility = 20

#Volatility criteria
low_volatility = 0.005
high_volatility = 0.015

#Margin
margin = 5
margin_buy = (1 - ((margin/2)/100))
margin_sell = (1 + (margin/100))
eq_margin = (margin_buy + margin_sell)/2

#Trend threshold
trend_buy = 2 #Value in percentage
trend_sell = -2 #Value in percentage

#Fear and greed index threholds
fgi_thresholds = {
    'conservative': {'buy': 15, 'sell': 85, 'panic_sell': 5},
    'balanced':     {'buy': 20, 'sell': 80, 'panic_sell': 10},
    'aggressive':   {'buy': 25, 'sell': 75, 'panic_sell': 10}
}

#Warning threshold information
thresholds = {
    'aggressive':   {'buy': 35, 'sell': -35},
    'balanced':     {'buy': 40, 'sell': -40},
    'conservative': {'buy': 45, 'sell': -45}
}


# Minimum tags that must agree for a decision
min_agreement = {
    'conservative': 6,
    'balanced': 5,
    'aggressive': 4
}

#Debug parameters
'''
min_agreement = {
    'conservative': 1,
    'balanced': 1,
    'aggressive': 1
}

thresholds = {
    'aggressive':   {'buy': 5, 'sell': -5},
    'balanced':     {'buy': 5, 'sell': -5},
    'conservative': {'buy': 5, 'sell': -5}
}
'''
