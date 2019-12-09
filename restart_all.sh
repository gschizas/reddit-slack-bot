#!/bin/sh
find /etc/systemd/system/slack-bot*.service -printf '%f\n' | xargs sudo systemctl restart
