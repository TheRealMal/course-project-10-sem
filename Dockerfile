FROM python:3.11-alpine
ENV PYTHONUNBUFFERED 1

RUN apk add --update git build-base wget docker

WORKDIR /

# Install semgrep
RUN python3 -m pip install semgrep
# Install trivy
RUN wget -q https://api.github.com/repos/aquasecurity/trivy/releases/latest -O latest_trivy.json && \
    TRIVY_URL=$(grep -E 'trivy_(.*)_Linux-64bit.tar.gz' latest_trivy.json | cut -d \" -f4 | grep 'https' | awk '/\.gz$/ {print}') && \
    FILE_NAME=$(basename ${TRIVY_URL}) && \
    wget -q "${TRIVY_URL}" && \
    tar zxvf "${FILE_NAME}" && \
    mv trivy /usr/local/bin/ && \
    rm "${FILE_NAME}"
RUN trivy --version && trivy image --download-db-only

# Install vault
# RUN apk add --no-cache libcap coreutils curl jq wget \
#     && apk add --update --no-cache -X http://dl-cdn.alpinelinux.org/alpine/v3.18/community vault \
#     && setcap cap_ipc_lock= /usr/sbin/vault

# Main source code & dependencies
COPY ./config /config
COPY ./src /src
RUN chmod +x /src/main.py
COPY ./scripts /scripts
RUN chmod +x /scripts/db-initialization.py
RUN chmod +x /scripts/db-drop.py
COPY ./requirements.txt /requirements.txt
RUN pip install -r requirements.txt



