#!/usr/bin/env sh
pipenv requirements > src/requirements.txt
docker build . --tag eurobot
rm src/requirements.txt
