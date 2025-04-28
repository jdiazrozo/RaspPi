import pandas as pd # type: ignore
import numpy as np
import trade_config as config
from collections import defaultdict, Counter
from trade_utils import debug, DEBUG_MODE, save_bin_cache, load_bin_cache, bin_cache



def get_global_bins(df, market):
    global bin_cache

    # Load cache once if empty
    if not bin_cache:
        load_bin_cache()

    if market not in bin_cache:
        print(f"[INFO] Initializing bin cache for {market}")
        bin_cache[market] = {}
        bin_cache[market]['return'] = auto_quantile_bins(df['return'], desired_bins=config.desired_bins)
        bin_cache[market]['lag'] = bin_cache[market]['return']
        bin_cache[market]['volatility'] = auto_quantile_bins(df['volatility'], desired_bins=config.desired_bins)
        bin_cache[market]['ma5'] = auto_quantile_bins(df['ma5'], desired_bins=config.desired_bins)
        bin_cache[market]['ma_slope'] = auto_quantile_bins(df['ma_slope'], desired_bins=config.desired_bins)
        bin_cache[market]['volume'] = auto_quantile_bins(df['volume_ma'], desired_bins=config.desired_bins)
        bin_cache[market]['fgi']= auto_quantile_bins(df['fgi'], desired_bins=config.desired_bins)
        save_bin_cache()

    for name, b in bin_cache[market].items():
        debug(f"[DEBUG] {market} bin edges for {name}: {b}")
    return bin_cache[market]

def auto_quantile_bins(series, desired_bins=4, min_bins=2, max_bins=6):
    clean = series.dropna()
    unique_vals = clean.nunique()
    n_bins = min(max(min(unique_vals, desired_bins), min_bins), max_bins)

    # Create evenly spaced quantiles
    quantiles = np.linspace(0, 1, n_bins + 1)  # e.g. 5 edges → 4 bins
    return safe_bins(clean, quantiles)

def fetch_binance_ohlcv(df, extra_columns=None):
    df = df.copy()
    df[['open', 'high', 'low', 'close', 'volume']] = df[['open', 'high', 'low', 'close', 'volume']].astype(float)
    columns = ['open', 'high', 'low', 'close', 'volume']
    if extra_columns:
        for col in extra_columns:
            if col in df.columns and col not in columns:
                columns.append(col)
    return df[columns]

def add_features(df):
    df = df.copy()
    df['return'] = df['close'].pct_change()
    df['lag1'] = df['return'].shift(1)
    df['lag2'] = df['return'].shift(2)
    df['lag3'] = df['return'].shift(3)
    df['ma5'] = df['close'].rolling(5).mean()
    df['volatility'] = df['return'].rolling(5).std()
    df['ma_slope'] = df['ma5'].diff()
    df['volume_ma'] = df['volume'].rolling(5).mean()
    return df

def discretize_column(series, bins, colname="unknown"):
    try:
        result = pd.cut(series, bins=bins, labels=False, include_lowest=True)
        nan_count = result.isna().sum()
        if nan_count > 0:
            debug(f"[WARN] {colname} has {nan_count} out-of-bin values")
            debug(f"[DEBUG] {colname} range: min={series.min()}, max={series.max()}")
            debug(f"[DEBUG] {colname} bin range: {bins}")
        return result
    except Exception as e:
        print(f"[ERROR] discretize_column failed for '{colname}': {e}")
        return pd.Series([np.nan] * len(series), dtype='float')

def safe_bins(series, quantiles):
    try:
        if series.dropna().empty:
            raise ValueError("Series is empty")

        # Use quantiles if in [0, 1]
        if all(0 <= q <= 1 for q in quantiles):
            bins = np.quantile(series.dropna(), quantiles)
            bins[0] -= 1e-9  # pad lower edge
            bins[-1] += 1e-9 # pad upper edge
        else:
            bins = quantiles  # use thresholds directly

        bins = np.unique(bins)
        if len(bins) < 2:
            bins = [series.min() - 1e-6, series.max() + 1e-6]

        return bins
    except Exception as e:
        print(f"[WARN] safe_bins fallback for series: {e}")
        min_val = series.min()
        max_val = series.max()
        if pd.isna(min_val) or pd.isna(max_val):
            return [0, 1]  # fallback
        return [min_val - 1e-6, max_val + 1e-6]

def discretize(df, market):
    debug(f"[DEBUG] Pre-binning row count: {len(df)}")
    debug(f"[DEBUG] Columns before binning: {df.columns.tolist()}")
    # Calculate features
    df['return'] = df['close'].pct_change()
    df['lag1'] = df['return'].shift(1)
    df['lag2'] = df['return'].shift(2)
    df['lag3'] = df['return'].shift(3)
    df['ma5'] = df['close'].rolling(5).mean()
    df['volatility'] = df['return'].rolling(5).std()
    df['ma_slope'] = df['ma5'].diff()
    df['volume_ma'] = df['volume'].rolling(5).mean()
    
    df = df.dropna(subset=[
        'return', 'lag1', 'lag2', 'lag3',
        'ma5', 'volatility', 'ma_slope', 'volume_ma'
    ]).copy()
    debug(f"[DEBUG] Post-feature dropna row count: {len(df)}")

    # Use per-market bins
    bins = get_global_bins(df, market)

    needs_refresh = False
    for col in ['return', 'lag1', 'lag2', 'lag3', 'ma5', 'ma_slope', 'volume_ma', 'fgi']:
        if col in df.columns and col in bins:
            col_min, col_max = df[col].min(), df[col].max()
            bin_min, bin_max = min(bins[col]), max(bins[col])
            tolerance = 1e-6
            if col_min < bin_min - tolerance or col_max > bin_max + tolerance:
                debug(f"[WARN] {col} out of bin range — refreshing bin_cache for {market}")
                debug(f"[DEBUG] {col} min={col_min:.6f}, max={col_max:.6f}, bin_min={bin_min:.6f}, bin_max={bin_max:.6f}")
                needs_refresh = True
                break

    if needs_refresh:
        bin_cache.pop(market, None)
        bins = get_global_bins(df, market)

    try:
        check_cols = ['fgi', 'ma5', 'volume_ma']
        for col in check_cols:
            if col in df.columns and col in bins:
                if df[col].min() < min(bins[col]) or df[col].max() > max(bins[col]):
                    print(f"[WARN] {col} values exceed cached bin range — resetting bin_cache for {market}")
                    bin_cache.pop(market, None)
                    bins = get_global_bins(df, market)
                    break
    except Exception as e:
        print(f"[ERROR] Bin range validation failed: {e}")

    # Discretize all required features using bins
    df['return_bin'] = discretize_column(df['return'], bins['return'], 'return')
    df['lag1_bin'] = discretize_column(df['lag1'], bins['lag'], 'lag1')
    df['lag2_bin'] = discretize_column(df['lag2'], bins['lag'], 'lag2')
    df['lag3_bin'] = discretize_column(df['lag3'], bins['lag'], 'lag3')
    df['volatility_bin'] = discretize_column(df['volatility'], bins['volatility'], 'volatiliy')
    df['ma5_bin'] = discretize_column(df['ma5'], bins['ma5'], 'ma5')
    df['ma_slope_bin'] = discretize_column(df['ma_slope'], bins['ma_slope'], 'ma_slope')
    df['volume_bin'] = discretize_column(df['volume_ma'], bins['volume'], 'volume_ma')
    df['fgi_bin'] = discretize_column(df['fgi'], bins['fgi'], 'fgi')

    # Drop rows with missing binned values
    required_bins = [
        'return_bin', 'lag1_bin', 'lag2_bin', 'lag3_bin',
        'volatility_bin', 'ma5_bin', 'ma_slope_bin',
        'volume_bin', 'fgi_bin'
    ]

    bin_columns = [col for col in df.columns if col.endswith('_bin')]
    debug(f"[DEBUG] Bin distribution per feature:")
    for col in bin_columns:
        counts = df[col].value_counts().sort_index()
        debug(f"  {col}: {counts.to_dict()}")
        
    df = df.dropna(subset=required_bins)
    debug(f"[DEBUG] Rows ready for prediction: {len(df)}")
    
    df = df.astype({bin: int for bin in required_bins})

    if df.empty:
        print(f"[WARN] Binned DataFrame for {market} is empty — refreshing bin_cache and retrying.")
        #bin_cache.pop(market, None)  # Clear this market's cache
        #bins = get_global_bins(df, market)  # Recompute
        #return discretize(df, market)  # Retry

    debug(f"[DEBUG] Rows after binning for {market}: {len(df)}")
    return df

def hamming_distance(key1, key2):
    return sum(a != b for a, b in zip(key1, key2))

def train_lookup(df):
    """
    Builds the lookup dictionary, lookup_array, and lookup_keys_list.
    """
    lookup = defaultdict(list)

    # Automatically detect *_bin columns
    feature_cols = [col for col in df.columns if col.endswith('_bin')]

    # Drop NaNs early
    df_filtered = df.dropna(subset=feature_cols + ['return_bin'])

    # Vectorized key extraction
    keys_matrix = df_filtered[feature_cols].astype(np.int32).values
    return_bins = df_filtered['return_bin'].astype(np.int32).values

    # Build lookup dict
    for key, target in zip(keys_matrix, return_bins):
        lookup[tuple(key)] += [target]

    lookup_keys_list = [tuple(k) for k in keys_matrix]
    lookup_array = keys_matrix

    debug(f"[DEBUG] Finished training — total full keys: {len(lookup)}")
    return lookup, lookup_array, lookup_keys_list

def predict_return_distribution(lookup, lookup_array, lookup_keys_list, row):
    """
    Predict return distribution using KNN with vectorized Hamming distance.
    """

    bin_columns = [col for col in row.index if col.endswith('_bin')]
    bin_indices = [row.index.get_loc(col) for col in bin_columns]

    try:
        key_full = row.values[bin_indices].astype(np.int32)
    except Exception as e:
        debug(f"[WARN] Invalid key for prediction: {e}")
        return None

    if np.isnan(key_full).any():
        debug(f"[WARN] Prediction skipped due to NaN key: {key_full}")
        return None

    debug(f"[DEBUG] KNN prediction key: {tuple(key_full)}")

    total_patterns = len(lookup_array)
    K_NEIGHBORS = min(max(3, int(np.sqrt(total_patterns))), 50)  # Cap at 50 neighbors
    debug(f"[DEBUG] Adaptive K_NEIGHBORS: {K_NEIGHBORS} (from {total_patterns} patterns)")

    # Vectorized Hamming distance calculation
    distances = np.count_nonzero(lookup_array != key_full, axis=1)

    if len(distances) < K_NEIGHBORS:
        debug(f"[WARN] Only {len(distances)} keys available, adjusting KNN to {len(distances)}")
        K_NEIGHBORS = len(distances)

    nearest_indices = np.argpartition(distances, K_NEIGHBORS)[:K_NEIGHBORS]

    counts = Counter()
    total_matches = 0

    for idx in nearest_indices:
        neighbor_key = lookup_keys_list[idx]
        neighbor_returns = lookup[neighbor_key]
        for val in neighbor_returns:
            counts[val] += 1
        total_matches += len(neighbor_returns)

    if total_matches < config.min_matches:
        debug(f"[WARN] KNN total support only {total_matches} — skipping prediction")
        return None

    prob_dist = {k: v / total_matches for k, v in counts.items()}
    debug(f"[DEBUG] KNN prediction used {K_NEIGHBORS} neighbors with total support: {total_matches}")
    return prob_dist



def estimate_price_from_distribution(prob_dist, last_price):
    bin_returns = {
        0: -0.03,
        1: -0.01,
        2:  0.00,
        3:  0.01,
        4:  0.03
    }
    expected_return = 0
    for bin_id, prob in prob_dist.items():
        bin_ret = bin_returns.get(bin_id, 0)
        contribution = bin_ret * prob
        expected_return += contribution
    predicted_price = last_price * (1 + expected_return)
    return predicted_price, bin_returns
