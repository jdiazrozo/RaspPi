#!/usr/bin/env python

import numpy as np

def calculate_slope(x, y):
    x_mean = np.mean(x)
    y_mean = np.mean(y)
    numerator = np.sum((x - x_mean) * (y - y_mean))
    denominator = np.sum((x - x_mean) ** 2)
    slope = numerator / denominator
    return slope

def forecast_cross_time(klines):
    short_mid_slope = calculate_slope(np.arange(len(klines)), 
                                      klines['ema_short'] - klines['ema_mid'])
    short_long_slope = calculate_slope(np.arange(len(klines)), 
                                       klines['ema_short'] - klines['ema_long'])
    cross_time_mid = -short_mid_slope * 6 if short_mid_slope < 0 else np.inf
    cross_time_long = -short_long_slope * 6 if short_long_slope < 0 else np.inf
    return (cross_time_mid, cross_time_long)

def get_percentage_diff(ema_long, ema_mid, ema_short):
    percentage_diff_long = ((ema_short.iloc[-1] - ema_long.iloc[-1]) / ema_long.iloc[-1]) * 100
    percentage_diff_mid = ((ema_short.iloc[-1] - ema_mid.iloc[-1]) / ema_mid.iloc[-1]) * 100
    return (percentage_diff_long, percentage_diff_mid)