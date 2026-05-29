import re

import click

from commands.extended_context import ExtendedContext

all_users = []
all_users_last_update = 0


class OpenShiftNamespace(click.ParamType):
    _force_upper: bool
    name = 'namespace'
    _config = {}

    def __init__(self, config, force_upper: bool = None) -> None:
        super().__init__()
        self._config = config
        self._force_upper = force_upper or False

    def convert(self, value, param, ctx) -> str:
        valid_environments = [e.lower() for e in self._config['environments']]
        valid_environments_text = ', '.join(valid_environments)
        if value.lower().startswith('omni-'):
            value = value[5:]
        if value.lower() not in valid_environments:
            self.fail(
                f"{value} is not a valid namespace. Try one of those: {valid_environments_text}",
                param,
                ctx)
        return value.upper() if self._force_upper else value.lower()


def rangify(original_input_list, consolidate=True):
    REGEX = r'^(?P<prefix>[\w\.]+)(?:(?:\[(?P<index>\d+)\])(?P<suffix>[\w\.]*))?$'

    def _extract_index(an_item):
        """Extract actual name and index from a list item"""
        matches = re.match(REGEX, an_item)
        if not matches:
            return an_item, 0
        kind_prefix, index_text, kind_suffix = matches.groups()
        an_index = int(index_text or 0)
        a_kind = kind_prefix + (kind_suffix or '')
        return a_kind, an_index

    def _merge_consecutive_items(input_list):
        """Merge list items with the same kind and consecutive indexes"""
        output_list = []
        current_kind = ""
        current_start = None
        current_end = None
        for item in input_list:
            if "[" in item:
                # This is a kind with an index
                kind, index = _extract_index(item)
                if kind == current_kind and index == current_end + 1:
                    # This is part of an existing range
                    current_end = index
                    output_list[-1] = f"{kind}[{current_start}-{current_end}]"
                else:
                    # This is a new kind or a new range for the current kind
                    current_kind = kind
                    current_start = index
                    current_end = index
                    output_list.append(item)
            else:
                # This is a kind without an index
                current_kind = ""
                current_start = None
                current_end = None
                output_list.append(item)
        return output_list

    item_list = sorted(original_input_list, key=lambda line: _extract_index(line))
    if consolidate:
        return _merge_consecutive_items(item_list)
    else:
        return item_list


def env_config(ctx: ExtendedContext, namespace):
    return ctx.obj['config']['environments'][namespace]
