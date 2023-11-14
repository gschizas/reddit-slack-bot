import io
import os

import click
import requests

from commands import gyrobot
from commands.extended_context import ExtendedContext
from state_file import state_file

COLS = 180
ROWS = 100
CHAR_WIDTH = 8
CHAR_HEIGHT = 14
FONT_SIZE = 13


def render_ansi(text, options=None):
    """Render `text` (terminal sequence) in a PNG file
    paying attention to passed command line `options`.

    Return: file content
    """
    import pyte.modes
    from PIL import Image, ImageFont, ImageDraw

    def _color_mapping(color):
        """Convert pyte color to PIL color

        Return: tuple of color values (R,G,B)
        """

        if color == 'default':
            return 'lightgray'

        if color in ['green', 'black', 'cyan', 'blue', 'brown']:
            return color
        try:
            return (
                int(color[0:2], 16),
                int(color[2:4], 16),
                int(color[4:6], 16))
        except (ValueError, IndexError):
            # if we do not know this color, and it can not be decoded as RGB,
            # print it and return it as it is (will be displayed as black)
            # print color
            return color

    def _strip_buf(buf):
        """Strips empty spaces from behind and from the right side.
        (from the right side is not yet implemented)
        """

        def empty_line(line):
            """Returns True if the line consists from spaces"""
            return all(x.data == ' ' for x in line)

        def line_len(line):
            """Returns len of the line excluding spaces from the right"""

            last_pos = len(line)
            while last_pos > 0 and line[last_pos - 1].data == ' ':
                last_pos -= 1
            return last_pos

        number_of_lines = 0
        for line in buf[::-1]:
            if not empty_line(line):
                break
            number_of_lines += 1

        if number_of_lines:
            buf = buf[:-number_of_lines]

        max_len = max(line_len(x) for x in buf)
        buf = [line[:max_len] for line in buf]

        return buf

    def _gen_term(buf):
        """Renders rendered pyte buffer `buf` and list of workaround `graphemes`
        to a PNG file, and return its content
        """

        current_grapheme = 0

        buf = _strip_buf(buf)
        cols = max(len(x) for x in buf)
        rows = len(buf)

        h_padding = 8
        v_padding = 8

        bg_color = 0
        image = Image.new('RGB', (2 * h_padding + cols * CHAR_WIDTH, 2 * v_padding + rows * CHAR_HEIGHT), color=bg_color)

        buf = buf[-ROWS:]

        draw = ImageDraw.Draw(image)
        font = ImageFont.truetype(os.environ.get('WEATHER_FONT'), FONT_SIZE)

        y_pos = 0
        for line in buf:
            x_pos = 0
            for char in line:
                current_color = _color_mapping(char.fg)
                if char.bg != 'default':
                    draw.rectangle(
                        ((h_padding + x_pos, v_padding + y_pos),
                         (h_padding + x_pos + CHAR_WIDTH, v_padding + y_pos + CHAR_HEIGHT)),
                        fill=_color_mapping(char.bg))

                data = char.data

                draw.text(
                    (h_padding + x_pos, v_padding + y_pos),
                    data,
                    font=font,
                    fill=current_color)

                x_pos += CHAR_WIDTH
            y_pos += CHAR_HEIGHT

        img_bytes = io.BytesIO()
        image.save(img_bytes, format="png")
        return img_bytes.getvalue()

    screen = pyte.screens.Screen(COLS, ROWS)
    screen.set_mode(pyte.modes.LNM)
    stream = pyte.Stream(screen)

    # text, graphemes = _fix_graphemes(text)
    stream.feed(text)

    buf = sorted(screen.buffer.items(), key=lambda x: x[0])
    buf = [[x[1] for x in sorted(line[1].items(), key=lambda x: x[0])] for line in buf]

    return _gen_term(buf)


@gyrobot.command('weather', aliases=['w'])
@click.argument("place", nargs=-1, required=False)
@click.pass_context
def weather(ctx: ExtendedContext, place):
    """Display the weather in any place.

    Syntax: weather PLACE

    if PLACE is skipped, the location from the last query is used.
    """
    place_full = ' '.join(place)

    with state_file('weather') as pref_cache:
        if place_full:
            pref_cache[ctx.chat.user_id] = place_full
        else:
            place_full = pref_cache.get(ctx.chat.user_id, '')

    if place_full == 'macedonia' or place_full == 'makedonia':
        place_full = 'Thessaloniki'
    if place_full == '':
        ctx.chat.send_text(
            ('You need to first set a default location\n'
             f'Try `{ctx.chat.bot_name} weather LOCATION`'), is_error=True)
        return
    place_full = place_full.replace("?", "")
    if place_full in ('brexit', 'pompeii'):
        title = 'the floor is lava'
        with open('img/weather/lava.png', 'rb') as f:
            file_data = f.read()
    else:
        if wego_exec := os.environ.get('WEGO_EXE'):
            import subprocess
            wego_output = subprocess.check_output([wego_exec, place_full])
            wego_output_text = wego_output.decode('utf-8')
            wego_output_text_lines = wego_output_text.split('\n')[:7]
            wego_output_text = '\n'.join(wego_output_text_lines)
            file_data = render_ansi(wego_output_text)
        else:
            weather_url = os.environ.get('WEATHER_URL', 'http://wttr.in/')
            weather_page = requests.get(weather_url + place_full + '_p0.png?m')
            file_data = weather_page.content
        title = place_full
    ctx.chat.send_file(file_data, title=title)
