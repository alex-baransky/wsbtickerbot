from ftplib import FTP
import re
import sys
import praw
import time
import json
import pprint
import operator
import datetime
from praw.models import MoreComments
# from iexfinance.stocks import Stock as IEXStock
from bs4 import BeautifulSoup
import requests
import pandas as pd

# to add the path for Python to search for files to use my edited version of vaderSentiment
sys.path.insert(0, 'vaderSentiment/vaderSentiment')
from vaderSentiment import SentimentIntensityAnalyzer

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

	try:
		price_change_net, price_change_pct = prices[1].replace('(', '').replace(')', '').split()
	except:
		print(f'The replace error string is: {prices[1]}')
	
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
      "GG", "ELON"
    ]
	if '$' in body:
		index = body.find('$') + 1
		word = extract_ticker(body, index)
	  
		if word and (word in valid_symbols) and (word not in blacklist_words):
			try:
				if word in ticker_dict:
					ticker_dict[word].count += 1
					ticker_dict[word].bodies.append(body)
				else:
					ticker_dict[word] = Ticker(word)
					ticker_dict[word].count = 1
					ticker_dict[word].bodies.append(body)
					price_info = get_price_info(word)
			   
					if price_info:
						ticker_dict[word].price = price_info[0]
						ticker_dict[word].price_change_net = price_info[1]
						ticker_dict[word].price_change_pct = price_info[2]
						ticker_dict[word].price_time = price_info[3]
					
			except Exception as e:
				print()
				print(type(e), e)
				print(f'\nError in parse_section! Word is {word}')
				# pass
   
	# checks for non-$ formatted comments, splits every body into list of words
	word_list = re.sub("[^\w]", " ", body).split()
	for word in word_list:
		# initial screening of words
		if word.isupper() and len(word) != 1 and (word in valid_symbols) and len(word) <= 5 and word.isalpha() and (word not in blacklist_words):
			# Use BeautifulSoup to scrape Yahoo stock page to see if ticker is valid,
			# if not then continue to next word.
			try:
				price_info = get_price_info(word)
			except Exception as e:
				print(f'\n{type(e)} {e}')
				print(word)
				continue
		 
			if not price_info:
				continue
	  
			# add/adjust value of dictionary
			if word in ticker_dict:
				ticker_dict[word].count += 1
				ticker_dict[word].bodies.append(body)
			else:
				ticker_dict[word] = Ticker(word)
				ticker_dict[word].count = 1
				ticker_dict[word].bodies.append(body)
				ticker_dict[word].price = price_info[0]
				ticker_dict[word].price_change_net = price_info[1]
				ticker_dict[word].price_change_pct = price_info[2]
				ticker_dict[word].price_time = price_info[3]
			
	return ticker_dict

def get_url(key, value, total_count):
	# determine whether to use plural or singular
	mention = ("mentions", "mention") [value == 1]
	if int(value / total_count * 100) == 0:
			perc_mentions = "<1"
	else:
			perc_mentions = int(value / total_count * 100)
		 
	return f"${key} | [{value} {mention} ({perc_mentions}% of all mentions)](https://finance.yahoo.com/quote/{key}?p={key})"

def final_post(subreddit, text):
	# finding the daily discussion thread to post
	title = str(get_date()) + " | Today's Top 25 WSB Tickers"

	print("\nPosting...")
	print(title)
	subreddit.submit(title, selftext=text)

def get_date():
	now = datetime.datetime.now()
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
	total_count = 0
	within24_hrs = False

	subreddit = setup(sub)
	new_posts = subreddit.new(limit=num_submissions)

	for count, post in enumerate(new_posts):
		# if we have not already viewed this post thread
		if not post.clicked:
			# parse the post's title's text
			ticker_dict = parse_section(ticker_dict, post.title)

			# to determine whether it has gone through all posts in the past 24 hours
			if "Daily Discussion Thread - " in post.title:
				if not within24_hrs:
					within24_hrs = True
				else:
					print(f"\nTotal posts searched: {str(count)}\nTotal ticker mentions: {str(total_count)}")
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
			sys.stdout.write(f"\rProgress: {count+1} / {num_submissions} posts")
			sys.stdout.flush()

	text = "To help you YOLO your money away, here are all of the tickers mentioned at least 10 times in all the posts within the past 24 hours (and links to their Yahoo Finance page) along with a sentiment analysis percentage:"
	text += "\n\nTicker | Mentions | Price | Price Change ($) | Price Change (%) | Bullish (%) | Neutral (%) | Bearish (%)\n:- | :- | :- | :- | :- | :- | :- | :-"

	total_mentions = 0
	ticker_list = []
	for key in ticker_dict:
		# print(key, ticker_dict[key].count)
		total_mentions += ticker_dict[key].count
		ticker_list.append(ticker_dict[key])

	ticker_list = sorted(ticker_list, key=operator.attrgetter("count"), reverse=True)

	for ticker in ticker_list:
		Ticker.analyze_sentiment(ticker)

	# will break as soon as it hits a ticker with fewer than 5 mentions
	for count, ticker in enumerate(ticker_list):
		if count == 25:
			break
	  
		url = get_url(ticker.ticker, ticker.count, total_mentions)
		# setting up formatting for table
		text += f"\n{url} | {ticker.price} | {ticker.price_change_net} | {ticker.price_change_pct} | {ticker.bullish} | {ticker.bearish} | {ticker.neutral}"

	text += "\n\nCheck out the original [source code](https://github.com/RyanElliott10/wsbtickerbot) by RyanElliott10 or check out my [source code](https://github.com/alex-baransky/wsbtickerbot)."

	# post to the subreddit if it is in bot mode (i.e. not testing)
	if not mode:
		final_post(subreddit, text)
	# testing
	else:
		print("\nNot posting to reddit because you're in test mode\n\n*************************************************\n")
		print(text)

class Ticker:
	def __init__(self, ticker):
		self.ticker = ticker
		self.count = 0
		self.bodies = []
		self.pos_count = 0
		self.neg_count = 0
		self.bullish = 0
		self.bearish = 0
		self.neutral = 0
		self.sentiment = 0 # 0 is neutral
		self.price = None
		self.price_change_net = None
		self.price_change_pct = None
		self.price_time = None

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

if __name__ == "__main__":
	# USAGE: wsbtickerbot.py [ subreddit ] [ num_submissions ]
	mode = 1
	num_submissions = 500
	sub = "wallstreetbets"

	if len(sys.argv) > 2:
		mode = 1
		num_submissions = int(sys.argv[2])

	valid_symbols = get_valid_symbols()
	run(mode, sub, num_submissions)