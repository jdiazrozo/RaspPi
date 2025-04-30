#!/usr/bin/env python

from datetime import datetime
from collections import defaultdict
import telepot # type: ignore
import requests


# Emoji mapping for weather
WEATHER_EMOJIS = {
    "clear": "☀️",
    "clouds": "☁️",
    "rain": "🌧️",
    "drizzle": "🌦️",
    "thunderstorm": "⛈️",
    "snow": "❄️",
    "mist": "🌫️",
    "fog": "🌫️"
}

#Telegram message
def telegram(msg):
    bot = telepot.Bot('1228874624:AAEkMwsunE4BLoFndVIowKlAUnqcCYEeR78')
    bot.sendMessage(chat_id=13981480, text=msg, parse_mode="Markdown")
    return

#External Weather Conditions
def get_forecast():
    api_url="https://api.openweathermap.org/data/2.5/forecast?lat=%f&lon=%f&appid=%s&units=metric"
    api_key="a7bb49dcaa2699e9eb3a04a8bb2583a3"
    lat=43.3128
    lon=-1.975
    query_url = api_url % (lat, lon, api_key)
    data = requests.get(query_url).json()
    return data['list']

def parse_forecast(forecast_data):
    daily_data = defaultdict(lambda: {"morning": [], "evening": [], "min": [], "max": [], "rain": [], "wind": []})

    for item in forecast_data:
        dt_txt = item['dt_txt']
        date = dt_txt.split(" ")[0]
        hour = int(dt_txt.split(" ")[1].split(":")[0])
        temp = item['main']['temp']
        temp_min = item['main']['temp_min']
        temp_max = item['main']['temp_max']
        weather = item['weather'][0]['description'].capitalize()
        weather_main = item['weather'][0]['main'].lower()
        emoji = WEATHER_EMOJIS.get(weather_main, "")
        rain_prob = item.get('pop', 0) * 100  # probability of precipitation
        wind_speed = item['wind']['speed'] * 3.6  # m/s to km/h
        wind_gust = item['wind'].get('gust', 0) * 3.6

        if 6 <= hour <= 9:
            daily_data[date]["morning"].append(temp)
        if 18 <= hour <= 21:
            daily_data[date]["evening"].append(temp)
        daily_data[date]["min"].append(temp_min)
        daily_data[date]["max"].append(temp_max)
        daily_data[date]["rain"].append(rain_prob)
        daily_data[date]["wind"].append((wind_speed, wind_gust))
        daily_data[date]["weather"] = f"{emoji} {weather}"

    return daily_data

def create_forecast_message(parsed_data):
    message = "📍 Donostia, ES\n🌤️ *Weather forecast:*\n"
    dates = list(parsed_data.keys())[:3]  # next 3 days

    for date in dates:
        morning = f"{sum(parsed_data[date]['morning'])/len(parsed_data[date]['morning']):.1f}°C" if parsed_data[date]['morning'] else "N/A"
        evening = f"{sum(parsed_data[date]['evening'])/len(parsed_data[date]['evening']):.1f}°C" if parsed_data[date]['evening'] else "N/A"
        min_temp = f"{min(parsed_data[date]['min']):.1f}°C"
        max_temp = f"{max(parsed_data[date]['max']):.1f}°C"
        rain = f"{sum(parsed_data[date]['rain'])/len(parsed_data[date]['rain']):.0f}%" if parsed_data[date]['rain'] else "0%"
        wind_speeds = [w[0] for w in parsed_data[date]['wind']]
        wind_gusts = [w[1] for w in parsed_data[date]['wind']]
        avg_wind = f"{sum(wind_speeds)/len(wind_speeds):.1f} km/h" if wind_speeds else "N/A"
        avg_gust = f"{sum(wind_gusts)/len(wind_gusts):.1f} km/h" if wind_gusts else "N/A"
        weather = parsed_data[date]['weather']

        formatted_date = datetime.strptime(date, "%Y-%m-%d").strftime("%d/%m/%Y")
        message += (
            f"\n📅 *{formatted_date}: {weather}*\n"
            f"🌡️ Min: {min_temp}, Max: {max_temp}\n"
            f"🌅 Morning: {morning}, 🌇 Evening: {evening}\n"
            f"🌧️ Rain Prob: {rain}\n"
            f"💨 Wind: {avg_wind} (Gusts: {avg_gust})\n"
        )
    return message

def send_forecast():
    forecast_data = get_forecast()
    parsed_data = parse_forecast(forecast_data)
    message = create_forecast_message(parsed_data)
    telegram(message)

if __name__ == "__main__":
    send_forecast()