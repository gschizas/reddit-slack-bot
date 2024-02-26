#!/usr/bin/env python3
import textwrap
from pathlib import Path

import jwt
from ruamel.yaml import YAML, scalarstring, comments

literal = scalarstring.LiteralScalarString

yaml = YAML()
wrapper = textwrap.TextWrapper()
wrapper.width = 64
wrapper.break_on_hyphens = False


# filename = Path(sys.argv[1])

def wrap_text(data):
    global wrapper
    if type(data) in (str, scalarstring.LiteralScalarString) and len(data) > wrapper.width:
        data = data.replace('\n', '')
        result = literal('\n'.join(wrapper.wrap(data)))
        try:
            token = jwt.decode(data, options={'verify_signature': False})
            secret_name = token.get('kubernetes.io/serviceaccount/secret.name')
            account_name = token.get('kubernetes.io/serviceaccount/service-account.name')
            namespace = token.get('kubernetes.io/serviceaccount/namespace')
            if secret_name and account_name and namespace:
                result.comment = f" # {account_name}@{namespace} ({secret_name})"
        except jwt.exceptions.DecodeError as e:
            result.comment = f" # {e!r}"
        return result
    elif type(data) in (dict, comments.CommentedMap):
        for x in data:
            data[x] = wrap_text(data[x])
            if type(data[x]) is scalarstring.LiteralScalarString and data[x].comment:
                # this shouldn't work, but it does
                data.yaml_set_comment_before_after_key(key=x, before='?')
                data.yaml_key_comment_extend(key=x, comment='?')
        return data
    else:
        return data


def main():
    for filename in Path('config').glob('*.credentials.yml'):
        # with filename.open() as f:
        #     data = json.load(f)

        with filename.open(mode='r') as f:
            data = yaml.load(f)

        data = wrap_text(data)

        new_filename = filename.with_suffix('.yml')

        with new_filename.open(mode='w') as f:
            yaml.dump(data, f)
        # yaml.dump(data, sys.stdout)

        with new_filename.open(mode='r') as f:
            data2 = yaml.load(f)


if __name__ == '__main__':
    main()
