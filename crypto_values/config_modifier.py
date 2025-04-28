#!/usr/bin/env python

import os
import sys

def modify_margin_values(margin_buy_value, margin_sell_value):
    # Path to the config.py file
    config_file_path = '/home/pi/personalapp/raspiapp/crypto_values/trade_config.py'

    try:
        # Open the config.py file for reading
        with open(config_file_path, "r") as file:
            lines = file.readlines()

        # Iterate through the lines and modify the margin_buy and margin_sell values
        modified_lines = []
        for line in lines:
            if line.strip().startswith("margin_buy"):
                modified_lines.append(f"margin_buy = {margin_buy_value}\n")
            elif line.strip().startswith("margin_sell"):
                modified_lines.append(f"margin_sell = {margin_sell_value}\n")
            else:
                modified_lines.append(line)

        # Open the config.py file for writing and overwrite its contents with the modified lines
        with open(config_file_path, "w") as file:
            file.writelines(modified_lines)

        print("Margin values successfully modified.")

    except FileNotFoundError:
        print("config.py file not found.")
    except Exception as e:
        print(f"An error occurred: {e}")