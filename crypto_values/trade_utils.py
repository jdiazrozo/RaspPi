import os
import math
import pickle
import time
import trade_config as config

DEBUG_MODE = False  # Global debug flag
bin_cache = {}  # Shared bin definitions across all assets
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
BIN_CACHE_PATH = os.path.join(BASE_DIR, 'bin_cache.pkl')

def debug(msg):
    if DEBUG_MODE:
        print(msg)

def save_bin_cache():
    try:
        with open(BIN_CACHE_PATH, 'wb') as f:
            pickle.dump({'bin_cache': bin_cache, 'timestamp': time.time()}, f)
        debug("[DEBUG] bin_cache saved to disk.")
    except Exception as e:
        print(f"[WARN] Failed to save bin_cache: {e}")

def load_bin_cache():
    if os.path.exists(BIN_CACHE_PATH):
        try:
            with open(BIN_CACHE_PATH, 'rb') as f:
                data = pickle.load(f)
                age = time.time() - data.get('timestamp', 0)
                if age < config.BIN_CACHE_TTL:
                    bin_cache.clear()
                    bin_cache.update(data['bin_cache'])  # ✅ merge into global dict
                    debug("[DEBUG] bin_cache loaded from disk.")
                else:
                    debug("[DEBUG] bin_cache expired after 24h. Rebuilding.")
                    bin_cache.clear()
        except Exception as e:
            print(f"[WARN] Failed to load bin_cache: {e}")

def flush_bin_cache():
    """Remove bin_cache from disk."""
    if os.path.exists(BIN_CACHE_PATH):
        os.remove(BIN_CACHE_PATH)
        debug("Bin_cache flushed from disk.")
    else:
        debug("No bin_cache found to flush.")

def get_required_fgi_days(interval, pred_horizon):
    if interval.endswith('h'):
        hours_per_candle = int(interval.rstrip('h'))
    elif interval.endswith('d'):
        hours_per_candle = int(interval.rstrip('d')) * 24
    else:
        raise ValueError(f"Unsupported interval format: {interval}")

    total_hours = hours_per_candle * pred_horizon
    return math.ceil(total_hours / 24)  # return full days
