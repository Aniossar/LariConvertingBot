from decimal import Decimal, ROUND_CEILING, InvalidOperation
from datetime import datetime
from telebot import types
from telebot_calendar import Calendar, CallbackData, RUSSIAN_LANGUAGE
from bot_config import TELEGRAM_TOKEN
import json
import re
import math
import requests
import telebot
import logging

class FutureDateError(Exception):
	def __init__(self, date, message="Future Date Error!"):
		self.date = date
		self.message = message
		super().__init__(self.message)

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logging.info("Ready Steady Go!")

user_sessions = {}
currency_cache = {}
months_ru = {
    1: "января", 2: "февраля", 3: "марта", 4: "апреля",
    5: "мая", 6: "июня", 7: "июля", 8: "августа",
    9: "сентября", 10: "октября", 11: "ноября", 12: "декабря"
}

bot = telebot.TeleBot(TELEGRAM_TOKEN)

calendar = Calendar(language=RUSSIAN_LANGUAGE)
calendar_callback = CallbackData("calendar", "action", "year", "month", "day")

def send_currency_keyboard(chat_id, text='Выбери валюту'):
	markup = types.ReplyKeyboardMarkup(resize_keyboard=True, one_time_keyboard=True)
	markup.add(types.KeyboardButton('USD'), types.KeyboardButton('EUR'))
	bot.send_message(chat_id, text, reply_markup=markup)


@bot.message_handler(commands=['start'])
def start(message):
	bot.send_message(message.chat.id, 'Выбери валюту')
	send_currency_keyboard(message.chat.id, 'Пожалуйста, используй встроенную клавиатуру для выбора валюты.')


@bot.message_handler(func=lambda message: True)
def message_handler(message):
	if message.text == 'USD' or message.text == 'EUR':
		get_currency(message)
	else:
		bot.send_message(message.chat.id, "Пожалуйста, используй встроенную клавиатуру для выбора валюты.")

@bot.callback_query_handler(func=lambda call: call.data.startswith(calendar_callback.prefix))
def callback_inline(call: types.CallbackQuery):
	name, action, year, month, day = call.data.split(calendar_callback.sep)
	date_obj = calendar.calendar_query_handler(
		bot=bot,
		call=call,
		name=name,
		action=action,
		year=year,
		month=month,
		day=day
	)
	try:
		if action == "DAY":
			message = call.message
			chat_id = message.chat.id
			today = datetime.now().date()
			if date_obj.date() > today:
				raise FutureDateError("Введенная дата не может быть позже сегодняшнего дня.")
			date_str = date_obj.strftime('%Y-%m-%d')
			if chat_id not in user_sessions:
				user_sessions[chat_id] = {'date_str': date_str}
			else:
				user_sessions[chat_id]['date_str'] = date_str
			calculate_gel_summ(message)
		elif action == "CANCEL":
			bot.send_message(call.from_user.id, "Выбор даты отменен")
			start(call.message)
			return
	except FutureDateError as fde:
		logging.error(f"Ошибка: {fde} Было введено {message.text}")
		bot.send_message(chat_id, 'Будущее не написано, его можно изменить. Введенная дата не может быть позже сегодняшнего дня.')
		send_calendar(call.message)


def get_currency(message: types.Message):
	chosen_currency = message.text
	chat_id = message.chat.id
	if chat_id not in user_sessions:
		user_sessions[chat_id] = {'chosen_currency': chosen_currency}
	else:
		user_sessions[chat_id]['chosen_currency'] = chosen_currency
	msg = bot.send_message(chat_id, f'Напиши сумму дохода в {chosen_currency}')
	bot.register_next_step_handler(msg, get_amount)


def get_amount(message: types.Message):
	chat_id = message.chat.id
	try:
		message_text_normalized = message.text.replace(',', '.')
		if math.isinf(float(message_text_normalized)):
			raise ValueError("Значение не может быть бесконечностью")
		amount = Decimal(message_text_normalized)
		if chat_id not in user_sessions:
			user_sessions[chat_id] = {'amount': amount}
		else:
			user_sessions[chat_id]['amount'] = amount
		send_calendar(message)
	except (ValueError, InvalidOperation) as e:
		logging.error(f"Ошибка при получении введённой суммы: {e}. Вместо суммы ввели это: {message.text}")
		msg = bot.send_message(chat_id, f'Используй _цифры_, например _123.45_', parse_mode='Markdown')
		bot.register_next_step_handler(msg, get_amount)


def send_calendar(message):
    chat_id = message.chat.id
    now = datetime.now()
    markup = calendar.create_calendar(
        name=calendar_callback.prefix,
        year=now.year,
        month=now.month
    )
    bot.send_message(chat_id, "Выбери дату:", reply_markup=markup)


def calculate_gel_summ(message):
	chat_id = message.chat.id
	if chat_id in user_sessions:
		amount = user_sessions[chat_id]['amount']
		date_str = user_sessions[chat_id]['date_str']
		chosen_currency = user_sessions[chat_id]['chosen_currency']
	currency_rate = request_currency_rate(date_str, chosen_currency)
	if currency_rate is None:
		bot.send_message(chat_id, 'Произошла ошибка при получении курса валют. Скоро всё починим!')
	else:
		date_obj = datetime.strptime(date_str, "%Y-%m-%d")
		final_summ_lari = currency_rate*amount
		rounded_final_summ_lari = final_summ_lari.quantize(Decimal("1.00"), rounding=ROUND_CEILING)
		local_date = f'{date_obj.day} {months_ru[date_obj.month]} {date_obj.year}'
		bot.send_message(message.chat.id, f'• Курс {chosen_currency} на {local_date} составлял {currency_rate} \n• Сумма дохода в лари составила *{rounded_final_summ_lari}*', parse_mode='Markdown')
		send_currency_keyboard(message.chat.id, 'Хочешь посчитать для другой даты или суммы? Просто выбери валюту.')
		logging.info(f'Размер user_sessions: {len(user_sessions)}, размер кеша: {len(currency_cache)}')


def request_currency_rate(date, chosen_currency):
	cache_key = f"{chosen_currency}_{date}"
	if cache_key in currency_cache:
		return currency_cache[cache_key]

	url = f"https://nbg.gov.ge/gw/api/ct/monetarypolicy/currencies/ka/json/?date={date}" #Национальный Банк Грузии
	try:
		response = requests.get(url)
		if response.status_code == 200:
			data = response.json()
			currency_rate = parse_json_for_currency(data, chosen_currency)
			if currency_rate is None:
				return None
			currency_cache[cache_key] = currency_rate
			return currency_rate
		else:
			logging.error(f"Ошибка запроса к API: HTTP статус {response.status_code}")
			return None
	except requests.RequestException as e:
		logging.error(f"Ошибка запроса к API: {e}, URL: {url}")
		return None


def parse_json_for_currency(data, chosen_currency):
	if data and isinstance(data, list) and data[0].get('currencies'):
		for currency in data[0]['currencies']:
			if currency['code'] == chosen_currency:
				try:
					currency_rate = Decimal(str(currency['rate']))
					return currency_rate
				except InvalidOperation:
					logging.error(f"Невозможно преобразовать курс валюты {chosen_currency} в Decimal.")
					return None
	logging.error("Данные от API пришли в некорректном формате.")
	return None

bot.infinity_polling()