FROM python:3.11.4-bookworm
LABEL MAINTAINER="George Schizas <gschizas@gmail.com>"

VOLUME /app/.refreshtoken
VOLUME /app/config
VOLUME /app/data
VOLUME /app/logs

RUN apt-get update
RUN apt-get clean
RUN apt-get upgrade -y
RUN apt-get install -y curl jq

# install OpenShift CLI
# RUN ver=$(curl https://api.github.com/repos/openshift/origin/releases/latest | jq --raw-output '.tag_name[1:]')
ADD get_oc.sh .
RUN /get_oc.sh
RUN rm oc.json
RUN rm get_oc.sh

# install Azure CLI
RUN apt-get install -y ca-certificates curl apt-transport-https lsb-release gnupg
RUN AZ_REPO=$(lsb_release -cs); \
    echo "deb [arch=`dpkg --print-architecture` signed-by=/etc/apt/keyrings/microsoft.gpg] https://packages.microsoft.com/repos/azure-cli/ $AZ_REPO main" | \
    tee /etc/apt/sources.list.d/azure-cli.list; \
    curl -sL https://packages.microsoft.com/keys/microsoft.asc | gpg --dearmor | \
    tee /etc/apt/keyrings/microsoft.gpg > /dev/null; \
    apt-get update; \
    apt-get install -y azure-cli

# install kubectl+kubelogin
RUN az aks install-cli

SHELL ["/bin/bash", "-c"]
COPY src /app
WORKDIR /app
RUN pip install -r requirements.txt
ENTRYPOINT ["python3", "slack_bot.py"]
