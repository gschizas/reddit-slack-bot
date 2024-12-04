import collections
import ctypes
import datetime
import math
import os
import subprocess

import click
import humanfriendly
import psutil

from commands import gyrobot
from commands.extended_context import ExtendedContext


@gyrobot.command('uptime')
@click.pass_context
def uptime(ctx):
    """Show uptime"""
    now = datetime.datetime.now()
    server_uptime = now - datetime.datetime.fromtimestamp(psutil.boot_time())
    process_uptime = now - datetime.datetime.fromtimestamp(psutil.Process(os.getpid()).create_time())
    ctx.chat.send_text((f"Server uptime: {humanfriendly.format_timespan(server_uptime)}\n"
                        f"Process uptime: {humanfriendly.format_timespan(process_uptime)}"))


DiskUsage = collections.namedtuple('usage', 'total used free')


def _diskfree():
    du = _disk_usage_raw('/')
    du_text = _disk_usage_human()
    return _progress_bar(du.used / du.total, 48) + '\n```\n' + du_text + '\n```\n'


def _disk_usage_raw(path):
    if hasattr(os, 'statvfs'):  # POSIX
        st = os.statvfs(path)
        free = st.f_bavail * st.f_frsize
        total = st.f_blocks * st.f_frsize
        used = (st.f_blocks - st.f_bfree) * st.f_frsize
        return DiskUsage(total, used, free)
    elif os.name == 'nt':  # Windows
        _, total, free = ctypes.c_ulonglong(), ctypes.c_ulonglong(), \
            ctypes.c_ulonglong()
        fun = ctypes.windll.kernel32.GetDiskFreeSpaceExW
        ret = fun(path, ctypes.byref(_), ctypes.byref(total), ctypes.byref(free))
        if ret == 0:
            raise ctypes.WinError()
        used = total.value - free.value
        return DiskUsage(total.value, used, free.value)


def _disk_usage_human():
    if hasattr(os, 'statvfs'):  # POSIX
        disk_usage_command = [
            'df',
            '--total',
            '--exclude-type=tmpfs',
            '--exclude-type=devtmpfs',
            '--exclude-type=squashfs',
            '--human-readable']
        return subprocess.check_output(disk_usage_command).decode()
    elif os.name == 'nt':  # Windows
        disk_usage_command = ['wmic', 'LogicalDisk', 'Where DriveType="3"', 'Get', 'DeviceID,FreeSpace,Size']
        return subprocess.check_output(disk_usage_command).decode()


def _progress_bar(percentage, size):
    filled = math.ceil(size * percentage)
    empty = math.floor(size * (1 - percentage))
    bar = '\u2588' * filled + '\u2591' * empty
    return bar


@gyrobot.command('disk_space')
@click.pass_context
def disk_space(ctx: ExtendedContext):
    """\
    Display free disk space"""
    ctx.chat.send_text(_diskfree())


@gyrobot.command('disk_space_ex')
@click.pass_context
def disk_space_ex(ctx):
    """Display free disk space"""
    ctx.chat.send_text('```' + subprocess.check_output(
        ['duf',
         '-only', 'local',
         '-output', 'mountpoint,size,avail,usage',
         '-style', 'unicode',
         '-width', '120']).decode() + '```')
