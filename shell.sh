#!/usr/bin/env sh

docker run -it \
    -v "$(realpath .refreshtoken):/app/.refreshtoken" \
    -v "$(realpath config):/app/config" \
    -v "$(realpath data):/app/data" \
    -v "$(realpath logs):/app/logs" \
    --entrypoint /bin/bash \
    --env-file $1 \
    eurobot