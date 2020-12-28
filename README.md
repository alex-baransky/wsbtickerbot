# wsbtickerbot

wsbtickerbot is a Reddit bot, developed utilizing the Reddit PRAW API, that scrapes all posts on r/wallstreetbets over a 24 hour period, collects all the tickers mentioned, and then performs sentiment analysis on the context. The sentiment analysis is used to classify the stocks into three categories: bullish, neutral, and bearish. The script also scrapes the price information for the stocks. This data is written to a csv file.

After the data is collected, the script will send an email (to all participants) with the top 25 mentioned stocks and their price and sentiment information.

This script will be scheduled to run daily. After significant data is collected, I plan to start analyzing stock trends in relation to discussions on r/wallstreetbets.

This code was adapted from another project written by RyanElliott10. The original code can be found [here](https://github.com/RyanElliott10/wsbtickerbot).
