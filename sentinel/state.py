import json
import os


def load(path):
    try:
        with open(path) as f:
            return json.load(f)
    except (FileNotFoundError, ValueError):
        return {}


def dumps(data):
    return json.dumps(data, sort_keys=True, separators=(',', ':'))


def save(path, text):
    tmp = path + '.tmp'
    with open(tmp, 'w') as f:
        f.write(text)
    os.replace(tmp, path)
