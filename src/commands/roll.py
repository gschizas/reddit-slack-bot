import random
import re

import click

from commands import gyrobot, DefaultCommandGroup
from commands.extended_context import ExtendedContext

MAGIC_8_BALL_OUTCOMES = [
    "It is certain.",
    "It is decidedly so.",
    "Without a doubt.",
    "Yes - definitely.",
    "You may rely on it.",
    "As I see it, yes.",
    "Most likely.",
    "Outlook good.",
    "Yes.",
    "Signs point to yes.",
    "Reply hazy, try again.",
    "Ask again later.",
    "Better not tell you now.",
    "Cannot predict now.",
    "Concentrate and ask again.",
    "Don't count on it.",
    "My reply is no.",
    "My sources say no.",
    "Outlook not so good.",
    "Very doubtful."]
DICE_REGEX = r'^(?P<Times>\d{1,2})?d(?P<Sides>\d{1,2})\s*(?:\+\s*(?P<Bonus>\d{1,2}))?$'


@gyrobot.group('roll', cls=DefaultCommandGroup)
def roll():
    """Roll a dice. Optional sides argument (e.g. roll 1d20+5, roll 1d6+2, d20 etc.)"""
    pass


@roll.command(default_command=True,
              context_settings={
                  'ignore_unknown_options': True,
                  'allow_extra_args': True})
@click.argument('specs', nargs=-1, required=False)
@click.pass_context
def roll_default(ctx: ExtendedContext, specs=None):
    """Roll a dice. Optional sides argument (e.g. roll 1d20+5, roll 1d6+2, d20 etc.)"""
    if specs is None:
        specs = ['1d6+0']

    for spec in specs:
        dice_spec = re.match(DICE_REGEX, spec)
        sides = times = bonus = 0
        if dice_spec:
            if dice_spec.group('Times'):
                times = int(dice_spec.group('Times'))
            if dice_spec.group('Bonus'):
                bonus = int(dice_spec.group('Bonus'))
            if dice_spec.group('Sides'):
                sides = int(dice_spec.group('Sides'))
        if sides < 2: sides = 6
        if times < 1: times = 1
        rolls = []
        for roll_index in range(times):
            rolls.append(random.randint(1, sides))
        final_roll = sum(rolls) + bonus
        roll_text = ', '.join(map(str, rolls))
        times_text = 'time' if times == 1 else 'times'
        ctx.chat.send_text((
            f"You rolled a {sides}-sided dice {times} {times_text} with a bonus of +{bonus}."
            f" You got {roll_text}. Final roll: *{final_roll}*"))


@roll.command('magic8',
              context_settings={
                  'ignore_unknown_options': True,
                  'allow_extra_args': True})
@click.pass_context
def roll_magic8(ctx: ExtendedContext):
    result = random.choice(MAGIC_8_BALL_OUTCOMES)
    ctx.chat.send_text(result)


@roll.command('statline')
@click.argument('spec', nargs=1, required=False)
@click.pass_context
def roll_statline(ctx: ExtendedContext, spec=None):
    min_roll = 2 if spec == 'drop1' else 1
    ability_text = ""
    for roll_line in range(6):
        ability_line = []
        for roll_dice in range(4):
            dice = random.randint(min_roll, 6)
            ability_line.append(dice)
        ability_line_sorted = sorted(ability_line)[1:]
        ability_text += (
            f"You rolled 4d6: {', '.join([str(a) for a in ability_line])}."
            f" Keeping {', '.join([str(a) for a in ability_line_sorted])},"
            f" for a sum of *{sum(ability_line_sorted)}*.\n")
    ctx.chat.send_text(ability_text)
