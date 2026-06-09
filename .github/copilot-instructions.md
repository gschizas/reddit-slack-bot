# Copilot Instructions

## Project Overview

A multi-platform chat bot (Slack/Mattermost) that integrates with Reddit for subreddit moderation. Commands are implemented as Click CLI subcommands and dispatched from incoming chat messages.

## Running and Building

**Install dependencies** (uses [uv](https://docs.astral.sh/uv/)):
```sh
git submodule update --init   # bot_framework is a submodule
uv sync
```

**Run locally** (loads `.env.d/<name>.env`):
```sh
python src/__main__.py <env-name>
```

**Docker build and run:**
```sh
docker build . --tag eurobot
./run.sh <env-file>         # Linux/macOS
./run.ps1 <EnvironmentFile> # Windows
```

There is no test suite.

## Architecture

```
src/
  __main__.py          # Entry point: loads env, init chat + Reddit, dispatches commands
  chat/                # Chat platform abstraction
    chat_wrapper.py    # Abstract base: ChatWrapper, Conversation, Message
    slack.py           # Slack implementation
    mattermost.py      # Mattermost implementation
    __init__.py        # Platform selection via env vars
  commands/            # Click command definitions (all auto-imported at startup)
    __init__.py        # Defines `gyrobot` root group + ClickAliasedGroup, DefaultCommandGroup
    extended_context.py  # Typed click.Context subclass
    reddit/            # Reddit moderation commands
    openshift/         # OpenShift/Kubernetes deployment commands
    generic/           # Utility commands (binary, unicode, version, etc.)
    github/            # GitHub integration (empty — not yet implemented)
  bot_framework/       # Shared utilities — GIT SUBMODULE (../bot_framework.git)
    common.py          # Logging setup, normalize_text
    praw_wrapper.py    # Reddit OAuth wrapper
    yaml_wrapper.py    # Configured ruamel.yaml instance
  backend/
    configuration.py   # Config/credentials/permissions loading; check_security decorator
    github_sdk.py      # GitHub API client
  state_file.py        # Persistent YAML state context manager
```

**Command dispatch flow:** Chat message → `handle_message()` → `parse_shortcuts()` → `handle_line()` → `click.testing.CliRunner.invoke(gyrobot, args)` (in a thread pool, `max_workers=10`).

**CWD requirement:** Must be run from the **repo root** (not from `src/`). `do_imports()` globs `src/commands/**/*.py` and commands read config from `config/`, `data/`, etc. relative to CWD.

**`help` keyword rewriting:** When the first argument after the trigger word is `help`, it is moved to the end as `--help`. So `bot help command` is equivalent to `bot command --help`.

**Platform selection** (`chat/__init__.py`): Based on env vars — `SLACK_APP_TOKEN`+`SLACK_BOT_TOKEN` for Slack, `MATTERMOST_API_TOKEN` for Mattermost.

**Command self-registration:** `do_imports()` in `__main__.py` dynamically imports every `src/commands/**/*.py`, which triggers module-level `@gyrobot.command(...)` decorators to register each command.

## Key Conventions

### Writing a new command

Register a command by decorating a function with `@gyrobot.command(...)` in any `commands/**/*.py` file. It is auto-discovered at startup.

```python
from commands import gyrobot
from commands.extended_context import ExtendedContext
import click

@gyrobot.command('mycommand', aliases=['mc'])
@click.argument('arg1')
@click.pass_context
def my_command(ctx: ExtendedContext, arg1: str):
    """Short description shown in help"""
    ctx.chat.send_text(f"Result: {arg1}")
```

Use `ExtendedContext` (not plain `click.Context`) for typed access:

| Property | Type | Description |
|---|---|---|
| `ctx.chat` | `Conversation` | Current channel — use for sending responses |
| `ctx.chat.channel_id` | `str` | Channel ID (use for routing responses) |
| `ctx.chat.channel_name` | `str` | Channel display name (used by `check_security`) |
| `ctx.chat.user_id` | `str` | Triggering user's ID |
| `ctx.message` | `Message` | Triggering message (`.text`, `.permalink`, `.timestamp`) |
| `ctx.logger` | `Logger` | Standard Python logger |
| `ctx.subreddit` | `praw.reddit.Subreddit` | Reddit subreddit (may be `None`) |
| `ctx.reddit_session` | `praw.Reddit` | Mod account Reddit session |
| `ctx.bot_reddit_session` | `praw.Reddit` | Alt Reddit account session |

### Sending responses

```python
ctx.chat.send_text("message")                        # plain text
ctx.chat.send_text("error", is_error=True)           # error styling
ctx.chat.send_file(data_bytes, filename="f.txt")     # file upload
ctx.chat.send_table("Title", list_of_dicts)          # table (auto-formats)
ctx.chat.send_tables("Title", {"Sheet": list_of_dicts}, send_as_excel=True)
ctx.chat.send_fields("header", [{"color": "#f00", "text": "..."}])
```

Output written to `stdout` (e.g., `print()`) is automatically sent back as a code block.

### Optional command modules (env-gated)

Modules that require specific env vars should raise `ImportError` at module level to skip gracefully:

```python
if 'SUBREDDIT_NAME' not in os.environ:
    raise ImportError('SUBREDDIT_NAME not found in environment')
```

### Persistent state

Use the `state_file` context manager for per-bot-instance YAML persistence (stored at `data/{path}-{LOG_NAME}.yml`):

```python
from state_file import state_file

with state_file('my-feature') as data:
    data['key'] = 'value'
```

### YAML

Always use `from bot_framework.yaml_wrapper import yaml` (a pre-configured `ruamel.yaml` safe-load instance). Do not instantiate `YAML()` directly unless building new infrastructure.

### Security / permissions

Use the `check_security` decorator from `backend.configuration` to gate commands by user/channel permissions read from `config/*.permissions.yml`.

### Command groups and aliases

- Use `cls=ClickAliasedGroup` for groups that need aliased subcommands.
- Use `cls=DefaultCommandGroup` for groups with a fallback default command.
- Pass `aliases=[...]` to `@group.command(...)` to register shorthand names.

## Reddit Commands (`commands/reddit/`)

Requires `SUBREDDIT_NAME` in env (modules raise `ImportError` at load time otherwise).

### Key helpers (`commands/reddit/common.py`)

Always use these when accepting user input — they handle Slack's link formatting (e.g. `<https://reddit.com/u/foo|foo>`) automatically:

```python
from commands.reddit.common import extract_username, extract_real_thread_id

username = extract_username(raw_arg)       # returns bare username or None if invalid
thread_id = extract_real_thread_id(raw_arg)  # returns bare Reddit base-36 ID
```

`extract_real_thread_id` also resolves Reddit share URLs (`/s/`) by following the redirect.

### Reddit command catalogue

| Command / Group | Env guard | Description |
|---|---|---|
| `modqueue [posts\|comments\|grouped\|length]` | `SUBREDDIT_NAME` | Inspect modqueue; `length` is default subcommand |
| `usernotes <user> [short\|long]` | `SUBREDDIT_NAME` | Show Toolbox usernotes (reads `wiki/usernotes` + `wiki/toolbox`) |
| `nuke thread <id>` | `SUBREDDIT_NAME` | Remove all non-distinguished comments + lock post; stores undo state in `state_file('nuke_thread')` |
| `nuke thread_undo <id>` | `SUBREDDIT_NAME` | Approve comments saved by `nuke thread` |
| `nuke user <username> [timeframe] [-s]` | `SUBREDDIT_NAME` | Remove user's recent comments; uses `bot_reddit_session`; `-s`/`-p` includes posts |
| `nuke ghosts <thread_id>` | `SUBREDDIT_NAME` | Remove comments from deleted accounts |
| `archive <username>` | `SUBREDDIT_NAME` | Submit user profile + all posts/comments to archive.is |
| `history <username>` | `SUBREDDIT_NAME` | Fetch comment history from Pushshift |
| `comment_source <id_or_url>` | `SUBREDDIT_NAME` | Return raw Markdown source of a comment |
| `deleted_comment_source <id...>` | `SUBREDDIT_NAME` | Return source of deleted comments via Pushshift |
| `configure_enhanced_crowd_control` (`order66`) | `SUBREDDIT_NAME` | Manage monitored threads list (`config/enhanced_crowd_control.yml`) |
| `add_domain_tag <url> <#color>` | `SUBREDDIT_NAME` | Tag a domain in Toolbox wiki |
| `add_policy <title>` | `SUBREDDIT_NAME` | Append policy change to mod policy wiki page |
| `youtube_post_info <url>` | `SUBREDDIT_NAME` | Get YouTube channel from a Reddit post |
| `unicode_post <thread_id>` | `SUBREDDIT_NAME` | Dump Unicode codepoints of a post title |
| `make post <thread_id\|NEW> <wiki_page>` | `REDDIT_ALT_USER` | Create/update a post from a wiki page using the alt account |
| `make sticky <thread_id> <wiki_page>` | `REDDIT_ALT_USER` | Create/update a stickied mod comment from a wiki page |
| `too_many_posts` | `GYROBOT_DATABASE_URL` | Users with >2 submissions in the last 24h (queries `public.submissions` table) |
| `survey <query>` | `QUESTIONNAIRE_DATABASE_URL` | Query survey results from PostgreSQL (psycopg3) |

### Reddit-specific patterns

- **Always use `bot_reddit_session`** (alt account) for actions taken *as a mod* on user content (e.g. `nuke user`). Use `reddit_session` (primary mod account) for read-only modqueue/usernote access.
- **Toolbox usernotes** are stored in `wiki/usernotes` as base64-encoded zlib-compressed JSON. The `wiki/toolbox` page holds the color/label config.
- **`configure_enhanced_crowd_control`** stores its state in `config/enhanced_crowd_control.yml` (not `state_file`), keyed by subreddit name. The group's body sets up `ctx.obj['monitored_threads']` for subcommands.
- **`make post`/`make sticky`** wiki page format: first line must be `# Title`, second line blank, rest is body.

---

## OpenShift / Kubernetes Commands (`commands/openshift/`)

### `KubernetesConnection` (`commands/openshift/api.py`)

The standard context manager for all K8s operations. Supports both OpenShift (static bearer token) and Azure AKS (service-principal OAuth2 flow):

```python
from commands.openshift.api import KubernetesConnection

with KubernetesConnection(ctx, namespace) as k8s:
    k8s.apps_v1_api    # AppsV1Api
    k8s.batch_v1_api   # BatchV1Api
    k8s.core_v1_api    # CoreV1Api
    k8s.project_name   # project/namespace name (may differ from env key)
    k8s.port_forward() # context manager for pod port-forwarding
```

Config is read from `ctx.obj['config']['environments'][namespace]`. Set `url: azure` to use AKS auth; otherwise a static bearer token in `credentials` is used. The cert CA file is in `config/<cert>` if `cert` key is present.

### `OpenShiftNamespace` param type (`commands/openshift/common.py`)

Use as `type=` on namespace arguments to validate and normalise against config:

```python
from commands.openshift.common import OpenShiftNamespace

@mygroup.command('do')
@click.argument('namespace', type=OpenShiftNamespace(my_config))
```

Strips `omni-` prefix automatically. Returns lowercase (or uppercase if `force_upper=True`).

### Security pattern for K8s commands

Every secured command follows this exact pattern — set `security_text` in the group body, then decorate the leaf command:

```python
@gyrobot.group('mygroup')
@click.pass_context
def mygroup(ctx: ExtendedContext):
    ctx.ensure_object(dict)
    ctx.obj['config'] = _my_config          # loaded at module level via read_config('MY_ENV_VAR')
    ctx.obj['security_text'] = {'do': 'do the thing', 'list': 'list things'}

@mygroup.command('do')
@click.argument('namespace', type=OpenShiftNamespace(_my_config))
@click.pass_context
@check_security                             # MUST come after @click.pass_context
def do_the_thing(ctx: ExtendedContext, namespace):
    with KubernetesConnection(ctx, namespace) as k8s:
        ...
```

### OpenShift/K8s command catalogue

| Command / Group | Env guard | Description |
|---|---|---|
| `deployment list\|pause\|resume <ns>` | `OPENSHIFT_DEPLOYMENT` | List/pause/resume all Deployments in a namespace |
| `cronjob list\|pause\|resume\|disable\|enable <ns> [name]` | `OPENSHIFT_CRONJOB` | Manage CronJobs; `pause`/`resume` use a stack in `data/cronjob-stack-<ns>.yml` |
| `scaledown [do] <ns>` | `OPENSHIFT_SCALEDOWN` | Scale all Deployments + StatefulSets to 0 replicas |
| `deploy <ms> <ver> <src> <tgt> <dry>` | `DOCKER_DEPLOY_CONFIGURATION` | Docker image promotion (stub — currently returns "Not implemented") |

### Cronjob pause/resume stack

`cronjob pause` pushes the list of currently-running cronjob names onto a YAML stack at `data/cronjob-stack-<namespace>.yml`. `cronjob resume` pops the most recent entry and re-enables only those. This preserves pre-existing suspensions.

### Cron descriptor localisation

`cronjob.py` patches `cron_descriptor.ExpressionDescriptor.get_month_description` to support Greek accusative month names. Cron descriptions use 24-hour time. Locale is detected from `locale.getlocale()`.

### `rangify` utility (`commands/openshift/common.py`)

Merges sorted lists of indexed Kubernetes resource names into range notation (e.g. `pod[0], pod[1], pod[2]` → `pod[0-2]`). Useful when reporting batch results.

### OpenShift `mock` command (`commands/openshift/mock.py`)

Manages microservice mock status by running `oc set env` via subprocess. Config (`MOCK_CONFIGURATION`) defines environments, valid status names, env-var shortcuts, and `vartemplate` string-substitution variables. Uses `api_obsolete_3.do_login/do_logout` for OpenShift CLI auth (not `KubernetesConnection`). Passwords in env-var output are automatically masked.

### OpenShift `actuator` command (`commands/openshift/refresh_actuator.py`)

Reaches Spring Boot Actuator endpoints inside pods via Kubernetes port-forward (using the `<pod-name>.pod.<project>.kubernetes` DNS trick from `KubernetesConnection.PortForward`). Calls `/actuator/env` before and after `/actuator/refresh` and diffs the results. Requires `OPENSHIFT_ACTUATOR_REFRESH`.

---

## Generic Commands (`commands/generic/`)

No env guards — always loaded.

| Command | Description |
|---|---|
| `binary` (`b`) | Decode space-separated 8-bit binary strings to text |
| `unicode <text>` | Dump Unicode codepoints of text to a file |
| `version` | Show `git describe --all --long` output |
| `path` | Show `PATH` environment variable |
| `uptime` | Show server and process uptime via `psutil` |
| `disk_space` | Show disk usage with a Unicode block progress bar |
| `disk_space_ex` | Show disk usage via `duf` (must be installed) |
| `fortune` | Run `/usr/games/fortune` |
| `joke` | Fetch a dad joke from icanhazdadjoke.com (respects `ALT_PROXY` env var) |
| `urban_dictionary` (`ud`) | Look up first Urban Dictionary definition |
| `youtube_info <url>` | Fetch YouTube oEmbed metadata |
| `covid` (`covid19`, `covid_19`) | COVID-19 stats from local `data/owid-covid-data.json`; country lookup via `countries.json` |
| `stocks` (`stock`, `stonk`) | Stock info via `yfinance`; uses Slack mid-dot `·` for ticker dots |
| `crypto <symbol...>` | Crypto price from cryptocompare.com |

---

## Other Commands

### `weather` / `w` (`commands/weather.py`)

Env guard: `WEGO_EXE` or `WEATHER_URL` (raises `ImportError` if neither present).

Remembers last location per user in `state_file('weather')`. Two rendering modes:
- **`WEGO_EXE`**: runs the `wego` binary, captures ANSI terminal output, renders it to a PNG via `pyte` (terminal emulator) + Pillow. Requires `WEATHER_FONT` env var pointing to a TTF font file.
- **`WEATHER_URL`** (default `http://wttr.in/`): fetches a pre-rendered PNG directly.

Easter eggs: `brexit`/`pompeii` → sends `img/weather/lava.png`.

### `convert <value> <from> to <to>` (`commands/convert.py`)

Unit conversions use `convert.json` (ratio table relative to a standard unit). Currency conversions fall through to cryptocompare.com. Handles feet/inches shorthand (`5'10"` → inches).

### `roll` group (`commands/roll.py`)

Dice rolling with NdS+B notation (e.g. `roll 2d6+3`). Subcommands: `magic8` (Magic 8-Ball), `statline [drop1]` (4d6 drop-lowest × 6 for RPG stats). `cointoss` is a separate top-level command.

### `kudos` group (`commands/kudos.py`)

Env guard: `KUDOS_DATABASE_URL` (PostgreSQL via psycopg3).

- **`kudos @user [reason]`** (default): records kudos in DB, randomly appends an emoji gift (75% chance). Parses Slack `<@USER_ID|name>` mentions via `EXTRACT_SLACK_ID` regex.
- **`kudos view [days] [channel] [-g] [-t|-x|-v|-i]`**: leaderboard for last N days (default 14). Output formats: text table, Excel, PNG image, or MP4 video (retro arcade high-score animation using imageio + Pillow + Amstrad CPC464 font from `img/kudos/`).

Assets required: `img/kudos/wallpaper.jpg`, `img/kudos/amstrad_cpc464.ttf`.

### `cheese` group (`commands/cheese.py`)

Env guard: `CHEESE_DATABASE_URL` (PostgreSQL via psycopg3). Config from `data/cheese_agent.yml`. Manages remote machines (ngrok/Citrix status, remote restart, message dispatch) via a job-queue table. `ngrok status` and `citrix status` use `send_ephemeral` (only visible to the requesting user). Machine access is gated by matching `ctx.chat.user_id` against `slack_ids` in config.

### `survey` group (`commands/reddit/survey.py`)

Env guard: `QUESTIONNAIRE_DATABASE_URL`. Questionnaire definition loaded from `data/$QUESTIONNAIRE_FILE` (multi-document YAML). Question types: `radio`, `checkbox`, `tree`, `checktree`, `text`, `textarea`, `scale-matrix`. Subqueries: `count`, `questions`, `questions_full`, `mods`, `votes_per_day`, `q_N`, `full_replies [json]`.

### Approval queue (`backend/approval.py`, `commands/onboarding.py`, `commands/approvals.py`)

Env guard: `APPROVAL_DATABASE_URL` (PostgreSQL via psycopg3; schema auto-created on first use).

A generic **command-approval queue**. Decorate any command with `@requires_approval` (placed *below* `@click.pass_context`) to make invoking it enqueue a pending request instead of running. Designated approvers act on the queue via the `approvals` group; approval re-invokes the original command body.

```python
from backend.approval import requires_approval

@gyrobot.command('onboard')
@click.argument('name')
@click.pass_context
@requires_approval(summarize=my_summary_fn, validate=my_validate_fn)
def onboard(ctx, name):
    ...  # only runs after approval
```

- The decorator sets `ctx.obj['_approved_execution']` during approved re-invocation; otherwise it serializes `ctx.params` (must be **JSON-serializable**) into the `approval_requests` table.
- `summarize(params) -> str` builds the human-readable one-liner; `validate(params) -> str|None` rejects bad requests before queuing.
- `execute_approved(approver_ctx, row)` rebuilds a `click.Context` for the stored command and invokes the real body, returning a result string stored on the request.

| Command / Group | Description |
|---|---|
| `onboard "<name>" <email> [--github] [--jetbrains] [--crowd]` | Queue provisioning of any of: GitHub Copilot licence, JetBrains IntelliJ IDEA licence, Crowd entry (≥1 flag required) |
| `offboard "<name>" <email>` | Queue removal of all licences/entries **and** Slack deactivation |
| `approvals list` | List pending requests (approvers only) |
| `approvals show <id>` | Full detail of one request |
| `approvals approve <id...>` / `approvals approve all` | Approve + execute requests (self-approval blocked unless `APPROVAL_ALLOW_SELF`) |
| `approvals reject <id...> [-r reason]` / `approvals reject all` | Reject pending requests |

Provisioning is delegated to the **stub** providers in `backend/providers/` (`github_copilot`, `jetbrains`, `crowd`, `slack_provision`), each exposing `provision/deprovision` (or `deactivate`) with a `# TODO` marking the real API integration point. `PROVIDERS` maps resource keys (`github`/`jetbrains`/`crowd`) to provider modules; `RESOURCE_LABELS` holds display names. Approver/requester permissions reuse `user_allowed` against `APPROVAL_APPROVERS` / `APPROVAL_REQUESTERS`.

---

## Backend (`backend/`, `bot_framework/`)

### `backend/configuration.py` — config loading and security

`read_config(env_var)` is called at **module load time** (not per-request), so config is cached for the process lifetime. Restart the bot to pick up config file changes.

`read_config(env_var)` loads a composite config from four sources and merges them into one dict:

| Source | Path pattern | Contents |
|---|---|---|
| Core config | `config/$ENV_VAR` or absolute path | `environments:` dict keyed by env name |
| Credentials | `<config>.credentials.yml` | Per-environment credentials |
| Permissions | `<config>.permissions.yml` | Per-environment `users:` and `channels:` lists |
| Kubernetes servers | `config/kubernetes_servers.yml` | Per-environment `url:`, `cert:`, `project_name:` |

`user_allowed(team_name, user_id, allowed_users)` checks against:
- `'*'` — allow all
- Literal user ID — direct match
- `@group` prefix — checks membership in `data/crowd_users.yml` (loaded lazily, re-read when file mtime changes)

`check_security` decorator reads `ctx.obj['security_text'][ctx.command.name]` for the human-readable action name, then validates both user and channel before calling the wrapped function.

### `backend/github_sdk.py` — GitHub API client

Lazy-initialised `requests.Session` using `GITHUB_TOKEN`. Provides paginated helpers:
- `get_org_members(org)` — all members of a GitHub org
- `get_org_teams(org)` — all teams
- `get_org_team_members(org, team_slug)` — members of a specific team
- `get_sso_identity(org_name, username)` — org membership + SSO login

All return full response objects from the GitHub REST API (v2022-11-28).

### `bot_framework/praw_wrapper.py` — Reddit OAuth

Handles the OAuth2 authorization-code flow on first run, then persists the refresh token to `.refreshtoken/<user_agent_key>.refresh_token`. On subsequent runs it loads the token from file and constructs an authenticated `praw.Reddit` instance without prompting. The key is derived from the second `:`-delimited segment of the user-agent string.

Env vars: `REDDIT_CLIENT_ID`, `REDDIT_CLIENT_SECRET`. First-run requires interactive browser visit.

### `bot_framework/common.py` — logging and text utilities

`setup_logging(extra_name, when)` creates two rotating log handlers (`.log` at INFO, `.debug.log` at DEBUG) under `logs/`, plus a coloured stdout handler when running in a TTY. Log level per-logger is overridden by `LOGGING.<logger_name>` env vars.

`normalize_text(text)` applies Unicode NFKD normalisation, strips combining diacritics (U+0300–U+0380), then applies the Unicode confusables table (downloaded from `ftp.unicode.org` on first use to `confusables.txt`) to map lookalike characters to their ASCII equivalents. Used in trigger-word matching so that Unicode lookalike characters can't be used to bypass the bot prefix.

### `bot_framework/yaml_wrapper.py`

A single shared `ruamel.yaml` YAML (safe, Unicode, non-flow) instance exported as `yaml`. **Always import this** rather than creating a new `YAML()` instance — unless you're writing infrastructure code that needs different settings (e.g. `cronjob.py` and `mock.py` use their own instances for round-trip preservation).

### `commands/openshift/api_obsolete_3.py` — legacy OC CLI auth

Used only by `mock.py`. Invokes the `oc` and `az` CLI binaries via `subprocess` instead of the Kubernetes Python client. `do_login` returns `(is_azure, prefix, project_name, result_text, should_exit)`. Always call `do_logout` after to clean up the oc session.

---

## Chat Platform Implementations (`chat/`)

### `chat/slack.py` — Slack (production)

Uses `slack-bolt` with Socket Mode (`SLACK_APP_TOKEN` + `SLACK_BOT_TOKEN`). The `app` object is module-level — imported once at startup.

**In-process caches** (module-level dicts, not invalidated):
- `users_cache[user_id]` — user info from `users.info`
- `teams_cache[team_id]` — team info from `team.info`
- `channels_cache[team_id][channel_id]` — channel display name

Channel names are prefixed: `#` for public, `🔒` for private, `🧑` for DMs (with full participant list).

**`send_table`**: sends as Excel if `send_as_excel=True` **or** if `SEND_TABLES_AS_EXCEL` env var is truthy — a global override for environments where file uploads of `.txt` are unwanted.

**`send_ephemeral`**: only visible to the triggering user. Used by `cheese` commands for private status info.

**`send_fields`**: uses Slack legacy `attachments` API (colored sidebar blocks). Used by `usernotes` for color-coded notes.

**Filtered event subtypes**: `message_deleted`, `message_replied`, `file_share`, `bot_message`, `slackbot_response` are silently ignored.

### `chat/mattermost.py` — Mattermost (partial)

Uses `mattermostdriver` with WebSocket event loop (`init_websocket`). Requires `MATTERMOST_API_URL` + `MATTERMOST_API_TOKEN`.

**Incomplete implementation** — `send_file`, `send_fields`, `send_blocks`, `get_user_info`, `get_team_info` are stubs (`pass`). Tables are sent as Markdown pipe format inline (not as file uploads). `send_ephemeral` uses the Mattermost ephemeral post API (text only, no blocks). Permalink is always empty string.

The hardcoded `"eurobot test"` message triggers a test table response (development artifact, not a real command).

---

## Configuration Files

All runtime config lives outside the repo under mounted volumes:

| Path | Purpose |
|---|---|
| `config/<name>.yml` | Main config (environments, etc.) |
| `config/<name>.credentials.yml` | Credentials per environment |
| `config/<name>.permissions.yml` | User/channel permissions per environment |
| `config/kubernetes_servers.yml` | Kubernetes cluster URLs |
| `data/crowd_users.yml` | User directory for group-based permissions |
| `.env.d/<name>.env` | Environment variables for a bot instance |

## Environment Variables

**Core / startup:**

| Variable | Purpose |
|---|---|
| `BOT_NAME` | Trigger word(s) (space-separated; first is primary) |
| `LOCALE` | Locale string passed to `locale.setlocale` at startup (e.g. `el_GR.UTF-8`) |
| `LOG_NAME` | Suffix for log filenames and `state_file` paths |
| `LOG_ROLLOVER` | Log rotation interval passed to `TimedRotatingFileHandler` (default `W0`) |
| `SHORTCUT_WORDS` | YAML filename under `data/` with command shortcuts |
| `DEBUG` | Show full tracebacks in chat error responses |
| `PERSONAL_DEBUG` | Channel ID to DM full error tracebacks to |
| `LOGGING.<name>` | Override log level for a named logger (e.g. `LOGGING.kubernetes=WARNING`) |

**Chat platforms:**

| Variable | Purpose |
|---|---|
| `SLACK_APP_TOKEN` + `SLACK_BOT_TOKEN` | Activates Slack platform |
| `SEND_TABLES_AS_EXCEL` | If truthy, all `send_table` calls send `.xlsx` instead of `.txt` |
| `MATTERMOST_API_TOKEN` + `MATTERMOST_API_URL` | Activates Mattermost platform |

**Reddit:**

| Variable | Purpose |
|---|---|
| `REDDIT_CLIENT_ID` + `REDDIT_CLIENT_SECRET` | Reddit OAuth app credentials |
| `SUBREDDIT_NAME` | Subreddit to moderate (enables all `commands/reddit/` modules) |
| `REDDIT_ALT_USER` | Enables alt mod account (`bot_reddit_session`); used for `make post/sticky` |
| `REDDIT_POLICY_SUBREDDIT` | Subreddit for `add_policy` (default: `SUBREDDIT_NAME`) |
| `REDDIT_POLICY_PAGE` | Wiki page for `add_policy` (default: `mod_policy_votes`) |
| `GYROBOT_DATABASE_URL` | PostgreSQL DSN for `too_many_posts` (psycopg3) |
| `QUESTIONNAIRE_DATABASE_URL` | PostgreSQL DSN for `survey` (psycopg3) |
| `QUESTIONNAIRE_FILE` | Filename under `data/` for survey questionnaire YAML |

**OpenShift / Kubernetes:**

| Variable | Purpose |
|---|---|
| `OPENSHIFT_DEPLOYMENT` | Config file path for `deployment` commands |
| `OPENSHIFT_CRONJOB` | Config file path for `cronjob` commands |
| `OPENSHIFT_SCALEDOWN` | Config file path for `scaledown` commands |
| `OPENSHIFT_ACTUATOR_REFRESH` | Config file path for `actuator` commands |
| `MOCK_CONFIGURATION` | Config file path for `mock` commands |
| `DOCKER_DEPLOY_CONFIGURATION` | Config file path for `deploy` command |
| `NO_PROXY` | Passed to `kubernetes.client.Configuration.no_proxy` |
| `AZ_CLI_EXECUTABLE` | Path to `az` binary (default: `az`) |

**Other commands:**

| Variable | Purpose |
|---|---|
| `WEGO_EXE` | Path to `wego` binary for `weather` (enables ANSI→PNG rendering) |
| `WEATHER_URL` | Base URL for `weather` PNG fetch (default: `http://wttr.in/`) |
| `WEATHER_FONT` | Path to TTF font file used by the ANSI→PNG renderer |
| `ALT_PROXY` | HTTP proxy for `joke` command |
| `KUDOS_DATABASE_URL` | PostgreSQL DSN for `kudos` (psycopg3) |
| `CHEESE_DATABASE_URL` | PostgreSQL DSN for `cheese` (psycopg3) |
| `GITHUB_TOKEN` | Bearer token for `backend/github_sdk.py` |
| `APPROVAL_DATABASE_URL` | PostgreSQL DSN for the approval queue (psycopg3); enables `onboard`/`offboard`/`approvals` |
| `APPROVAL_APPROVERS` | Who may approve/reject (comma-separated; `user_allowed` syntax: `*`, user IDs, `@group`) |
| `APPROVAL_REQUESTERS` | Who may issue approval-gated commands (default `*`) |
| `APPROVAL_NOTIFY_CHANNEL` | (Optional) channel ID to post new pending requests to |
| `APPROVAL_ALLOW_SELF` | (Optional, default false) allow approving one's own request |
