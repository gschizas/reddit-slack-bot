import re

import click
import requests

from commands import gyrobot
from commands.extended_context import ExtendedContext


@gyrobot.command('stocks', aliases=['stock', 'stonk'])
@click.argument("stock_name")
@click.pass_context
def stocks(ctx: ExtendedContext, stock_name):
    """Show info for a stock"""
    import yfinance as yf

    if '|' in stock_name:
        stock_name = re.findall(r'\|(.*)>', stock_name)[0]
    stock_name = stock_name.replace(MID_DOT, '.')
    stock = yf.Ticker(stock_name)

    change = (((stock.info['ask'] / stock.info['previousClose']) - 1) * 100)  # > 10

    fields = [
        f"Ask Price: {stock.info['ask']}",
        f"Bid: {stock.info['bid']}",
        f"Day High: {stock.info['dayHigh']}",
        f"Last Day: {stock.info['regularMarketPreviousClose']}",
        f"Change: {change:.02f}"
    ]

    blocks = [
        {
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": f"{stock.info['longName']} ({stock.info['symbol'].replace('.', MID_DOT)}) " +
                        f"{stock.info['currency']}"
            },
            "accessory": {
                "type": "image",
                "image_url": stock.info.get('logo_url', EMPTY_IMAGE),
                "alt_text": stock.info['longName']
            },
            "fields": [{"type": "plain_text", "text": field} for field in fields]
        }
    ]
    ctx.chat.send_blocks(blocks)


@gyrobot.command('crypto')
@click.argument('symbol', nargs=-1)
@click.pass_context
def crypto(ctx: ExtendedContext, symbol):
    """Display the current exchange rate of currency"""
    for cryptocoin in symbol:
        cryptocoin = cryptocoin.upper()
        prices = requests.get("https://min-api.cryptocompare.com/data/price",
                              params={'fsym': cryptocoin, 'tsyms': 'USD,EUR'}).json()
        if prices.get('Response') == 'Error':
            ctx.chat.send_text('```' + prices['Message'] + '```\n', is_error=True)
        else:
            ctx.chat.send_text(f"{cryptocoin} price is € {prices['EUR']} or $ {prices['USD']}")


EMPTY_IMAGE = "data:image/gif;base64,R0lGODlhAQABAAAAACH5BAEKAAEALAAAAAABAAEAAAICTAEAOw=="
MID_DOT: str = '\xb7'
