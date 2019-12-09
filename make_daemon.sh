#!/usr/bin/env sh

git config --file=/etc/systemd/system/slack-bot-$1.service Unit.Description 'Perform various functions as slack bot'
git config --file=/etc/systemd/system/slack-bot-$1.service Unit.After 'multi-user.target'
git config --file=/etc/systemd/system/slack-bot-$1.service Service.Type 'simple'
git config --file=/etc/systemd/system/slack-bot-$1.service Service.ExecStart '/usr/local/bin/pipenv run ./slack_bot.py'
git config --file=/etc/systemd/system/slack-bot-$1.service Service.User $SUDO_USER
git config --file=/etc/systemd/system/slack-bot-$1.service Service.WorkingDirectory $(realpath .)
git config --file=/etc/systemd/system/slack-bot-$1.service Service.Restart 'on-failure'
git config --file=/etc/systemd/system/slack-bot-$1.service Install.WantedBy 'multi-user.target'
mkdir /etc/systemd/system/slack-bot-$1.service.d
git config --file=/etc/systemd/system/slack-bot-$1.service.d/override.conf Service.Environment "PIPENV_DOTENV_LOCATION=$(realpath .)/.env.d/slack-bot-$1.env"
systemctl daemon-reload
