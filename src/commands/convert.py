import json
import pathlib
import re

import click
import requests

from commands import gyrobot
from commands.extended_context import ExtendedContext

_conversions = None


def _read_conversions():
    with (pathlib.Path(__file__).parent / 'convert.json').open() as f:
        return json.load(f)


def _find_unit(unit, search_text):
    if unit['Unit'].casefold() == search_text.casefold():
        return True
    aliases = [a.casefold() for a in unit.get('Aliases', [])]
    if search_text.casefold() in aliases:
        return True
    return False


def _get_conversion_value(unit: str) -> float:
    global _conversions
    if _conversions is None:
        _conversions = _read_conversions()
    result = list(filter(lambda u: _find_unit(u, unit), _conversions))
    if len(result) == 0:
        return None
    elif len(result) == 1:
        return result[0]
    else:
        return None


@gyrobot.command('convert')
@click.argument('words', type=click.STRING, nargs=-1)
@click.pass_context
def convert(ctx: ExtendedContext, words):
    """Convert money from one currency to another.

    Example: convert 100.0 USD to EUR
             convert 5'10" to cm"""

    if len(words) < 3 or len(words) > 5:
        ctx.chat.send_text("Format is convert «number» «from» to «to»", is_error=True)

    if len(words) == 3:
        # Try to find out what the first argument is
        if unit_length := re.match(r"^(?:(?P<feet>\d*\.?\d*?)')?(?:(?P<inches>\d*\.?\d*)\")?$", words[0]):
            unit_feet = int(unit_length.group("feet")) if unit_length.group(1) else 0
            unit_inches = int(unit_length.group("inches")) if unit_length.group(2) else 0
            unit_total_inches = unit_inches + unit_feet * 12
            words = [unit_total_inches, "inch", "to", words[2]]

    [value_text, unit_from, _, unit_to] = words

    try:
        value = float(value_text)
    except ValueError:
        ctx.chat.send_text(f"{value_text} is not a good number", is_error=True)
        return

    if not (re.match(r'^\w+$', unit_from)):
        ctx.chat.send_text(f"{unit_from} is not a real unit or currency", is_error=True)
        return

    if not (re.match(r'^\w+$', unit_to)):
        ctx.chat.send_text(f"{unit_to} is not a real unit or currency", is_error=True)
        return

    if constant_unit_from_conversion := _get_conversion_value(unit_from):
        constant_unit_to_conversion = _get_conversion_value(unit_to)
        standard_value = value * constant_unit_from_conversion['Value']
        converted_value = standard_value / constant_unit_to_conversion['Value']
        text = f"`{unit_from} : {constant_unit_from_conversion} : {constant_unit_to_conversion}`"
        if constant_unit_to_conversion['Unit'].casefold() == "inch":
            converted_feet = int(converted_value // 12)
            converted_inches = round(converted_value % 12)
            text = f"`{value} {unit_from} is {converted_feet}'{converted_inches}\"`"
        else:
            text = f"`{value} {unit_from} is {converted_value} {unit_to}`"
    else:
        # It's currency

        unit_from = unit_from.upper()
        unit_to = unit_to.upper()

        if unit_from == unit_to:
            ctx.chat.send_text("Tautological bot is tautological", is_error=True)
            return

        prices_page = requests.get(
            "https://min-api.cryptocompare.com/data/price",
            params={'fsym': unit_from, 'tsyms': unit_to})
        ctx.logger.info(prices_page.url)
        prices = prices_page.json()
        if prices.get('Response') == 'Error':
            text = prices['Message']
        else:
            price = prices[unit_to]
            new_value = value * price
            text = f"{value:.2f} {unit_from} is {new_value:.2f} {unit_to}"
    ctx.chat.send_text(text)
