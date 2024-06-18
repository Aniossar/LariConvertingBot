# from telegram.ext import Updater
# from bot_config import TELEGRAM_TOKEN
# from asyncio import Queue
# import logging

# logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO)

# my_queue = Queue()

# updater = Updater(TELEGRAM_TOKEN, my_queue)
# updater.start_polling()

import os
import signal
from bot_config import TELEGRAM_TOKEN
from asyncio import Queue
import time
from telegram.ext import Updater, CommandHandler

def restart(update, context):
	update.message.reply_text('Bot is restarting...')
	time.sleep(1)
	os.kill(os.getpid(), signal.SIGINT)

def main():
	my_queue = Queue()
	updater = Updater(TELEGRAM_TOKEN, my_queue)
	dp = updater.dispatcher()
	dp.add_handler(CommandHandler('restart', restart))
	updater.start_polling()
	updater.idle()

if __name__ == '__main__':
	main()