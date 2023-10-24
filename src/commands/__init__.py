import logging

import click
import praw

from chat.chat_wrapper import ChatWrapper


class DefaultCommandGroup(click.Group):
    """allow a default command for a group"""

    def command(self, *args, **kwargs):
        default_command = kwargs.pop('default_command', False)
        if default_command and not args:
            kwargs['name'] = kwargs.get('name', '<>')
        decorator = super().command(*args, **kwargs)

        if default_command:
            def new_decorator(f):
                cmd = decorator(f)
                self.default_command = cmd.name
                return cmd

            return new_decorator

        return decorator

    def resolve_command(self, ctx, args):
        try:
            # test if the command parses
            return super().resolve_command(ctx, args)
        except click.UsageError:
            # command did not parse, assume it is the default command
            args.insert(0, self.default_command)
            return super().resolve_command(ctx, args)


class ClickAliasedGroup(click.Group):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._commands = {}
        self._aliases = {}

    def command(self, *args, **kwargs):
        aliases = kwargs.pop('aliases', [])
        decorator = super(ClickAliasedGroup, self).command(*args, **kwargs)
        if not aliases:
            return decorator

        def _decorator(f):
            cmd = decorator(f)
            if aliases:
                self._commands[cmd.name] = aliases
                for alias in aliases:
                    self._aliases[alias] = cmd.name
            return cmd

        return _decorator

    def group(self, *args, **kwargs):
        aliases = kwargs.pop('aliases', [])
        decorator = super(ClickAliasedGroup, self).group(*args, **kwargs)
        if not aliases:
            return decorator

        def _decorator(f):
            cmd = decorator(f)
            if aliases:
                self._commands[cmd.name] = aliases
                for alias in aliases:
                    self._aliases[alias] = cmd.name
            return cmd

        return _decorator

    def resolve_alias(self, cmd_name):
        if cmd_name in self._aliases:
            return self._aliases[cmd_name]
        return cmd_name

    def get_command(self, ctx, cmd_name):
        cmd_name = self.resolve_alias(cmd_name)
        command = super(ClickAliasedGroup, self).get_command(ctx, cmd_name)
        if command:
            return command

    def format_commands(self, ctx, formatter):
        rows = []

        sub_commands = self.list_commands(ctx)

        for sub_command in sub_commands:
            cmd = self.get_command(ctx, sub_command)
            if cmd is None:
                continue
            if hasattr(cmd, 'hidden') and cmd.hidden:
                continue
            if sub_command in self._commands:
                aliases = ','.join(sorted(self._commands[sub_command]))
                sub_command = '{0} ({1})'.format(sub_command, aliases)
            cmd_help = cmd.short_help or ''
            rows.append((sub_command, cmd_help))

        if rows:
            with formatter.section('Commands'):
                formatter.write_dl(rows)


# class Environment:
#     def __init__(self):
#         pass
#
#     def send_text(self):
#         pass
#
#
# pass_environment = click.make_pass_decorator(Environment, ensure=True)


@click.group(cls=ClickAliasedGroup,
             context_settings={
                 'help_option_names': ['-h', '-?', '/?', '--help'],
                 'ignore_unknown_options': True,
                 'allow_extra_args': True})
# @pass_environment
@click.pass_context
def gyrobot(ctx: click.Context):
    pass


def chat(ctx: click.Context) -> ChatWrapper:
    return ctx.obj['chat']


def logger(ctx: click.Context) -> logging.Logger:
    return ctx.obj['logger']


def subreddit(ctx: click.Context) -> praw.reddit.Subreddit:
    return ctx.obj['subreddit']


def reddit_session(ctx: click.Context) -> praw.reddit.Reddit:
    return ctx.obj['reddit_session']


def bot_reddit_session(ctx: click.Context) -> praw.reddit.Reddit:
    return ctx.obj['bot_reddit_session']
