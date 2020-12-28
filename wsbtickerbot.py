from ftplib import FTP
from datetime import datetime, timedelta
from praw.models import MoreComments
from bs4 import BeautifulSoup
import re
import sys
import praw
import time
import json
import operator
import requests
import pandas as pd
import csv

# to add the path for Python to search for files to use my edited version of vaderSentiment
sys.path.insert(0, 'vaderSentiment/vaderSentiment')
from vaderSentiment import SentimentIntensityAnalyzer

blacklist_words = [
	  "YOLO", "TOS", "CEO", "CFO", "CTO", "DD", "BTFD", "WSB", "OK", "RH",
	  "KYS", "FD", "TYS", "US", "USA", "IT", "ATH", "RIP", "BMW", "GDP",
	  "OTM", "ATM", "ITM", "IMO", "LOL", "DOJ", "BE", "PR", "PC", "ICE",
	  "TYS", "ISIS", "PRAY", "PT", "FBI", "SEC", "GOD", "NOT", "POS", "COD",
	  "AYYMD", "FOMO", "TL;DR", "EDIT", "STILL", "LGMA", "WTF", "RAW", "PM",
	  "LMAO", "LMFAO", "ROFL", "EZ", "RED", "BEZOS", "TICK", "IS", "DOW"
	  "AM", "PM", "LPT", "GOAT", "FL", "CA", "IL", "PDFUA", "MACD", "HQ",
	  "OP", "DJIA", "PS", "AH", "TL", "DR", "JAN", "FEB", "JUL", "AUG",
	  "SEP", "SEPT", "OCT", "NOV", "DEC", "FDA", "IV", "ER", "IPO", "RISE"
	  "IPA", "URL", "MILF", "BUT", "SSN", "FIFA", "USD", "CPU", "AT",
	  "GG", "ELON", "ROPE", "GAS", "P", "SEX", "GTFO", "BRK", "KAHOOT",
	  "VHS"
	]

blacklist_words = dict.fromkeys(blacklist_words, 1)

def print_progress_bar(iteration, total, prefix = '', suffix = '', decimals = 1, length = 50, fill = '█', printEnd = "\r"):
    """
    Call in a loop to create terminal progress bar
    @params:
        iteration   - Required  : current iteration (Int)
        total       - Required  : total iterations (Int)
        prefix      - Optional  : prefix string (Str)
        suffix      - Optional  : suffix string (Str)
        decimals    - Optional  : positive number of decimals in percent complete (Int)
        length      - Optional  : character length of bar (Int)
        fill        - Optional  : bar fill character (Str)
        printEnd    - Optional  : end character (e.g. "\r", "\r\n") (Str)
    """
    percent = ("{0:." + str(decimals) + "f}").format(100 * (iteration / float(total)))
    filledLength = int(length * iteration // total)
    bar = fill * filledLength + '-' * (length - filledLength)
    bar = bar[:len(bar)//2] + f'{percent}%' + bar[len(bar)//2:]

    print(f'\r{prefix} |{bar}| {iteration} / {total} {suffix}', end = printEnd)
    # Print New Line on Complete
    if iteration == total: 
        print()

def get_valid_symbols():
	"""
	Utilizes nasdaq FTP server to find valid ticker symbols. Returns
	dictionary with the symbols as keys for fast symbol lookup. Dictionary
	values are meaningless.
	"""
	# Log in to FTP server to get stock symbols
	nasdaq = FTP('ftp.nasdaqtrader.com')
	nasdaq.login()
	nasdaq.cwd('SymbolDirectory')

	# Write stock symbols to two files
	with open('nasdaqlisted.txt', 'wb') as f:
		nasdaq.retrbinary('RETR nasdaqlisted.txt', f.write)
	with open('otherlisted.txt', 'wb') as f:
		nasdaq.retrbinary('RETR otherlisted.txt', f.write)

	# Open files and merge them
	with open('nasdaqlisted.txt', 'r') as f:
		total_stocks = f.readlines()
	with open('otherlisted.txt', 'r') as f:
		# Discard the header row
		f.readline()
		total_stocks.extend(f.readlines())

	total_stocks = [line.split('|') for line in total_stocks]
	df = pd.DataFrame(total_stocks[1:], columns=total_stocks[0])
	valid_symbols = df['Symbol'][df['Symbol'].apply(str.isalpha)]
	
	return dict.fromkeys(list(valid_symbols), 1)

def get_price_info(ticker):
	"""
	Given a ticker string, scrape the Yahoo ticker page to get the price,
	price change (both net and percent), and time of last update.
	"""
	response = requests.get(f'https://finance.yahoo.com/quote/{ticker}?p={ticker}')
	text = BeautifulSoup(response.text, 'html.parser')

	exists = text.find('div', attrs={'class': 'D(ib) Mend(20px)'})

	if not exists:
		return None

	prices = exists.find_all('span')
	prices = [val.string for val in prices]

	price_change_net, price_change_pct = prices[1].replace('(', '').replace(')', '').split()

	return [prices[0], price_change_net, price_change_pct, prices[2]]

def extract_ticker(body, start_index):
	"""
	Given a starting index and text, this will extract the ticker, return None if it is incorrectly formatted.
	"""
	count  = 0
	ticker = ""

	for char in body[start_index:]:
		# if it should return
		if not char.isalpha():
			# if there aren't any letters following the $
			if (count == 0):
				return None

			return ticker.upper()
		else:
			ticker += char
			count += 1

	return ticker.upper()

def parse_section(ticker_dict, body):
	""" Parses the body of each comment/reply """

	if '$' in body:
		index = body.find('$') + 1
		word = extract_ticker(body, index)

		if word and (word not in blacklist_words):
			if word in ticker_dict:
				ticker_dict[word].count += 1
				ticker_dict[word].bodies.append(body)
			else:
				ticker_dict[word] = Ticker(word)
				ticker_dict[word].count = 1
				ticker_dict[word].bodies.append(body)

	# checks for non-$ formatted comments, splits every body into list of words
	word_list = re.sub("[^\w]", " ", body).split()
	for word in word_list:
		# initial screening of words
		if word.isupper() and len(word) != 1 and (word in valid_symbols) and len(word) <= 5 and word.isalpha() and (word not in blacklist_words):
			if word in ticker_dict:
				ticker_dict[word].count += 1
				ticker_dict[word].bodies.append(body)
			else:
				ticker_dict[word] = Ticker(word)
				ticker_dict[word].count = 1
				ticker_dict[word].bodies.append(body)

	return ticker_dict

def get_mentions(key, value, total_count):
	# determine whether to use plural or singular
	mention = ("mentions", "mention")[value == 1]
	if int(value / total_count * 100) == 0:
			pct_mentions = "<1"
	else:
			pct_mentions = int(value / total_count * 100)

	return value, pct_mentions

def get_date():
	now = datetime.now()
	return now.strftime("%b %d, %Y")

def setup(sub):
	if sub == "":
		sub = "wallstreetbets"

	with open("config.json") as json_data_file:
		data = json.load(json_data_file)

	# create a reddit instance
	reddit = praw.Reddit(client_id=data["login"]["client_id"], client_secret=data["login"]["client_secret"],
								username=data["login"]["username"], password=data["login"]["password"],
								user_agent=data["login"]["user_agent"])
	# create an instance of the subreddit
	subreddit = reddit.subreddit(sub)
	return subreddit

def run(mode, sub, num_submissions):
	ticker_dict = {}
	text = ""
	total_mentions = 0

	subreddit = setup(sub)
	new_posts = subreddit.new(limit=num_submissions)

	print('Retrieving Reddit post data...')
	for num, post in enumerate(new_posts, 1):
		# if we have not already viewed this post thread
		if not post.clicked:
			# parse the post's title's text
			ticker_dict = parse_section(ticker_dict, post.title)

			# to determine whether this post is within 24 hrs
			post_time = datetime.fromtimestamp(post.created)
			if start_time-timedelta(hours=24) > post_time:
				for key in ticker_dict:
					total_mentions += ticker_dict[key].count
				print(f"\nLess than {num_submissions} posts!\nTotal posts searched: {str(num)}\nTotal ticker mentions: {str(total_mentions)}")
				break

			# search through all comments and replies to comments
			comments = post.comments
			for comment in comments:
				# without this, would throw AttributeError since the instance in this represents the "load more comments" option
				if isinstance(comment, MoreComments):
					continue
				ticker_dict = parse_section(ticker_dict, comment.body)

				# iterate through the comment's replies
				replies = comment.replies
				for rep in replies:
					# without this, would throw AttributeError since the instance in this represents the "load more comments" option
					if isinstance(rep, MoreComments):
						continue
					ticker_dict = parse_section(ticker_dict, rep.body)

			# update the progress count
			# sys.stdout.write(f"\rProgress: {count+1} / {num_submissions} posts")
			print_progress_bar(num, num_submissions, suffix = 'posts')
			# sys.stdout.flush()

	# Open csv file for saving and write header row
	timestr = time.strftime("%Y%m%d")
	csvfile = open(f'{timestr}-stonks.csv', 'w', newline='', encoding='utf-8')
	csvwriter = csv.writer(csvfile)
	csvwriter.writerow(['ticker', 'date', 'url', 'num_mentions', 'pct_mentions', 'pos_count',
						'neg_count', 'bullish_pct', 'bearish_pct', 'neutral_pct', 'price', 'price_change_net',
						'price_change_pct', 'time_of_price'])
	# If the script didn't end early because it hit a post > 24hrs old, find total_mentions
	if not total_mentions:
		for key in ticker_dict:
			total_mentions += ticker_dict[key].count

	# Analyze the sentiment for each ticker, find what percentage of mentions, and find stock price info.
	# Then write row to csv.
	total_tickers = len(ticker_dict.keys())
	print('\nStarting sentiment analysis, price fetching, and CSV writing...')

	for num, key in enumerate(ticker_dict, 1):
		print_progress_bar(num, total_tickers, suffix = 'tickers')
		curr_ticker = ticker_dict[key]

		# Scrape ticker price info. If information is not available, continue to next ticker.
		try:
			curr_ticker.get_price_info()
		except Exeption as e:
			print('\n',type(e), e)
			print(f'Error getting price for ticker {curr_ticker.ticker}!')
			continue

		# Perform sentiment analysis on text bodies for the current ticker
		curr_ticker.analyze_sentiment()

		# Retrieve mentions info
		num_mentions, pct_mentions = get_mentions(curr_ticker.ticker, curr_ticker.count, total_mentions)

		# Write ticker data to csv row
		csvwriter.writerow([curr_ticker.ticker, get_date(), curr_ticker.url, num_mentions, pct_mentions,
							curr_ticker.pos_count, curr_ticker.neg_count, curr_ticker.bullish, curr_ticker.bearish, curr_ticker.neutral,
							curr_ticker.price, curr_ticker.price_change_net, curr_ticker.price_change_pct, curr_ticker.time_of_price])
		
		# sys.stdout.flush()

class Ticker:
	def __init__(self, ticker):
		self.ticker = ticker
		self.url = f'https://finance.yahoo.com/quote/{ticker}?p={ticker}'
		self.count = 0
		self.bodies = []
		self.pos_count = 0
		self.neg_count = 0
		self.bullish = 0
		self.bearish = 0
		self.neutral = 0
		self.price = None
		self.price_change_net = None
		self.price_change_pct = None
		self.time_of_price = None

	def analyze_sentiment(self):
		analyzer = SentimentIntensityAnalyzer()
		neutral_count = 0
		for text in self.bodies:
			sentiment = analyzer.polarity_scores(text)
			if (sentiment["compound"] > .005) or (sentiment["pos"] > abs(sentiment["neg"])):
				self.pos_count += 1
			elif (sentiment["compound"] < -.005) or (abs(sentiment["neg"]) > sentiment["pos"]):
				self.neg_count += 1
			else:
				neutral_count += 1

		self.bullish = int(self.pos_count / len(self.bodies) * 100)
		self.bearish = int(self.neg_count / len(self.bodies) * 100)
		self.neutral = int(neutral_count / len(self.bodies) * 100)

	def get_price_info(self):
		"""
		Given a ticker string, scrape the Yahoo ticker page to get the price,
		price change (both net and percent), and time of last update.
		"""
		response = requests.get(f'https://finance.yahoo.com/quote/{self.ticker}?p={self.ticker}')
		text = BeautifulSoup(response.text, 'html.parser')

		exists = text.find('div', attrs={'class': 'D(ib) Mend(20px)'})

		if not exists:
			return None

		prices = exists.find_all('span')
		prices = [val.string for val in prices]

		try:
			price_change_net, price_change_pct = prices[1].replace('(', '').replace(')', '').split()
		except:
			raise Exception(f'Error in method get_price_info() for ticker: {self.ticker}!')

		self.price = prices[0]
		self.price_change_net = price_change_net
		self.price_change_pct = price_change_pct
		self.time_of_price = prices[2]

if __name__ == "__main__":
	# USAGE: wsbtickerbot.py [ subreddit ] [ num_submissions ]
	mode = 1
	num_submissions = 500
	sub = "wallstreetbets"

	if len(sys.argv) > 2:
		mode = 1
		num_submissions = int(sys.argv[2])

	start_time = datetime.now()
	valid_symbols = get_valid_symbols()
	run(mode, sub, num_submissions)
	print(f'It took {(datetime.now() - start_time)/60} minutes to run!')