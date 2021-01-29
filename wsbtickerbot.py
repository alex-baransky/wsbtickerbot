from ftplib import FTP
from datetime import datetime, timedelta
from praw.models import MoreComments
from bs4 import BeautifulSoup
from helper import get_stonks_email_df
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
import re
import sys
import praw
import time
import json
import operator
import requests
import pandas as pd
import csv
import smtplib
import ssl

# Set the path to the project directory
abs_path = '/home/pi/Desktop/Projects/wsbtickerbot/'

# to add the path for Python to search for files to use my edited version of vaderSentiment
sys.path.insert(0, abs_path+'vaderSentiment/vaderSentiment')
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
      "VHS", "HCFC", "VIX", "BECKY", "CELG", "NIOGANG", "URSELF", "HOLD",
      "MOON", "EV", "PUMP", "EOD", "ARE", "FOR", "OPEN", "OR", "JUST",
      "CAN", "ON", "GO", "AM", "NOW", "RE", "SO", "BIG", "OUT", "SEE",
      "HAS", "MUST", "LOVE", "HE", "BY", "NEW", "ONE", "UK", "NEXT",
      "FREE"
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
    with open(abs_path+'nasdaqlisted.txt', 'wb') as f:
        nasdaq.retrbinary('RETR nasdaqlisted.txt', f.write)
    with open(abs_path+'otherlisted.txt', 'wb') as f:
        nasdaq.retrbinary('RETR otherlisted.txt', f.write)

    # Open files and merge them
    with open(abs_path+'nasdaqlisted.txt', 'r') as f:
        total_stocks = f.readlines()
    with open(abs_path+'otherlisted.txt', 'r') as f:
        # Discard the header row
        f.readline()
        total_stocks.extend(f.readlines())

    total_stocks = [line.split('|') for line in total_stocks]
    df = pd.DataFrame(total_stocks[1:], columns=total_stocks[0])
    valid_symbols = df['Symbol'][df['Symbol'].apply(str.isalpha)]
    
    return dict.fromkeys(list(valid_symbols), 1)

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

    # Load Reddit API credentials (need to make this json with your own credentials)
    with open(abs_path+"config.json") as json_data_file:
        data = json.load(json_data_file)

    # create a reddit instance
    reddit = praw.Reddit(client_id=data["login"]["client_id"], client_secret=data["login"]["client_secret"],
                                username=data["login"]["username"], password=data["login"]["password"],
                                user_agent=data["login"]["user_agent"])
    # create an instance of the subreddit
    subreddit = reddit.subreddit(sub)
    return subreddit

def run(sub, num_submissions):
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
            print_progress_bar(num, num_submissions, suffix = 'posts')

    # Open csv file for saving and write header row
    timestr = time.strftime("%Y%m%d")
    csvfile = open(abs_path+f'data/{timestr}-stonks.csv', 'w', newline='', encoding='utf-8')
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
        except Exception as e:
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

def change_text_color(val):
    """
    Changes font color to green or red, based on whether there is a positive or negative change.
    """
    val = str(val)
    if val[-1] == '%':
        if val[0] == '-':
            return f'<span style="color:red">{val}</span>'
        elif val[0] == '+':
            return f'<span style="color:green">{val}</span>'
    else:
        if val[0] == '-':
            return f'<span style="color:red">{val}</span>'
        elif float(val) != 0:
            return f'<span style="color:green">{val}</span>'

    return f'<span>{val}</span>'

def find_dominant_sentiment(df):
    """
    Change color and bold the value the column if
    the sentiment is greater for one of the three
    categories. MUTATING!
    """
    df['dominant'] = ['bull' if bull == max(bull, neut, bear) else
                      'bear' if bear == max(bull, neut, bear) else
                      'neut' if neut == max(bull, neut, bear) else 'tie'
                      for bull, neut, bear in zip(df['Bullish (%)'], df['Neutral (%)'], df['Bearish (%)'])]
    # Reset the index
    df.reset_index(drop=True, inplace=True)

    for i in range(df.shape[0]):
        if df.loc[i, 'dominant'] == 'bull':
            df.loc[i, 'Bullish (%)'] = f'<b><span style="color:green">{df.loc[i, "Bullish (%)"]}</span></b>'
        elif df.loc[i, 'dominant'] == 'bear':
            df.loc[i, 'Bearish (%)'] = f'<b><span style="color:red">{df.loc[i, "Bearish (%)"]}</span></b>'
        elif df.loc[i, 'dominant'] == 'neut':
            df.loc[i, 'Neutral (%)'] = f'<b><span>{df.loc[i, "Neutral (%)"]}</span></b>'
    df.drop('dominant', axis=1, inplace=True)

def generate_stonks_report_df(df):
    """
    Takes a df and returns the top 25 mentioned tickers and other relevant information.
    Returns a df.
    """
    df = df.sort_values('num_mentions', ascending=False).head(25)
    
    # Changing format of df for nicer display
    df['Ticker'] = [f'<a href="{url}">{ticker}</a>' for ticker, url in zip(df['ticker'], df['url'])]
    df['Mentions'] = [f'{num_mentions} mentions ({pct_mentions}% of all mentions)' for num_mentions, pct_mentions in zip(df['num_mentions'], df['pct_mentions'])]
    df.rename({'bullish_pct': 'Bullish (%)', 'bearish_pct': 'Bearish (%)', 'neutral_pct': 'Neutral (%)',
               'price': 'Price', 'price_change_net': 'Price Change ($)', 'price_change_pct': 'Price Change (%)'},
               axis = 1, inplace = True)
    # Formats prices so they always display 2 decimal places
    df['Price'] = df['Price'].apply(lambda f: str(f).replace(',', '')).astype(float).apply(lambda f: '$%.2f' % f)
    df['Price Change ($)'] = df['Price Change ($)'].apply(lambda f: str(f).replace(',', '')).astype(float).apply(lambda f: '%.2f' % f).apply(change_text_color)
    df['Price Change (%)'] = df['Price Change (%)'].apply(lambda f: str(f).replace('%','').replace(',', ''))\
                            .astype(float).apply(lambda f: ('%.2f' % f)+'%' if str(f)[0] == '-' else '+'+('%.2f' % f)+'%')\
                            .apply(change_text_color)
    find_dominant_sentiment(df)

    return df[['Ticker', 'Mentions', 'Bullish (%)', 'Neutral (%)', 'Bearish (%)', 'Price', 'Price Change ($)', 'Price Change (%)']]

def send_email(name, receiver_email, df, port = 587, smtp_server = "smtp.gmail.com"):
    # smtp_server = "smtp.gmail.com:587"
    
    # Load email credentials (need to make this json with your own credentials)
    with open(abs_path+"email.json") as f:
        email_creds = json.load(f)

    sender_email = email_creds['login']['email']
    password = email_creds['login']['password']

    html = f"""
    <html><body><p>Hello {name},</p>
    <p>To help you YOLO your money away, here are the top 25 tickers (by number of mentions) within the past 24 hours from r/wallstreetbets along with daily price information and sentiment analysis percentages.</p>
    <p><b>If you believe a ticker shown in this table does not represent a stock, please respond to this email to let me know!</b></p>
    <p>{df.to_html(col_space = 80, justify='center', index=False, render_links=True, escape=False)}</p>
    <p>Check out my <a href="https://github.com/alex-baransky/wsbtickerbot">source code</a> for this project. You can also check out the original <a href="https://github.com/RyanElliott10/wsbtickerbot">source code</a> written by RyanElliott10 that I used to develop this project.</p>
    <br>
    <p>Good luck,</p>
    <p>Señor Stonks</p>
    <br>
    <p><b>Disclaimer</b>: This data is collected for investigational purposes only and is intended to be used as a starting point for further exploration. I am not responsible for losses (or gains) you may realize as a result of this information. Invest at your own risk.<p>
    </body></html>
    """

    message = MIMEMultipart("alternative", None, [MIMEText(html,'html')])

    message['Subject'] = f"Stonks Report - {get_date()}"
    message['From'] = sender_email
    message['To'] = receiver_email

    with smtplib.SMTP(smtp_server, port) as server:
        server.ehlo()
        server.starttls()
        server.login(sender_email, password)
        server.sendmail(sender_email, receiver_email, message.as_string())

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
    num_submissions = 2000
    sub = "wallstreetbets"

    if len(sys.argv) > 2:
        num_submissions = int(sys.argv[2])

    start_time = datetime.now()
    valid_symbols = get_valid_symbols()
    run(sub, num_submissions)
    print(f'It took {(datetime.now() - start_time)} to run!')

    print('Sending emails...')

    # Get the list of names and emails to send the report to
    stonks_email_df = get_stonks_email_df()
    names = stonks_email_df.Name
    emails = stonks_email_df.Email

    # Load the report df
    stonks_report_df = pd.read_csv(abs_path+f'data/{time.strftime("%Y%m%d")}-stonks.csv')
    stonks_report_df = generate_stonks_report_df(stonks_report_df)
    
    for name, email in zip(names, emails):
        send_email(name, email, stonks_report_df)
        