FROM ubuntu:24.04
LABEL maintainer="Muhammad Yuga Nugraha"

COPY id_rsa.pub /root/.ssh/authorized_keys
COPY init /usr/local/bin/init

ENV DEBIAN_FRONTEND=noninteractive
RUN echo "root:root" | chpasswd \
    && chmod +x /usr/local/bin/init \
    && apt update -q \
    && apt install -y \
    systemd \
    systemd-sysv \
    lsb-release \
    kmod \
    init \
    net-tools \
    iputils-ping \
    openssh-server \
    file \
    iproute2 \
    curl \
    nano \
    vim \
    ca-certificates \
    gpg \
    dnsutils \
    && touch /root/.hushlogin