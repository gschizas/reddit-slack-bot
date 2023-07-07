FROM python:3.11.4-bookworm
LABEL MAINTAINER="George Schizas <gschizas@gmail.com>"

VOLUME /app/.refreshtoken
VOLUME /app/config
VOLUME /app/data
VOLUME /app/logs

COPY src /app
WORKDIR /app
RUN pip install -r requirements.txt
ENTRYPOINT ["python3", "slack_bot.py"]
