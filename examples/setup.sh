#!/bin/bash

FC_VERSION="1.12.0"

apt update
apt install -y ca-certificates curl net-tools python3-pip python3-nftables python3-venv

echo "Installing Docker"
install -m 0755 -d /etc/apt/keyrings
curl -fsSL https://download.docker.com/linux/ubuntu/gpg -o /etc/apt/keyrings/docker.asc
chmod a+r /etc/apt/keyrings/docker.asc

echo \
  "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.asc] https://download.docker.com/linux/ubuntu \
  $(. /etc/os-release && echo "${UBUNTU_CODENAME:-$VERSION_CODENAME}") stable" | \
  tee /etc/apt/sources.list.d/docker.list > /dev/null
apt update
apt install -y docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin 

echo "Installing Firecracker"
wget https://github.com/firecracker-microvm/firecracker/releases/download/v${FC_VERSION}/firecracker-v${FC_VERSION}-x86_64.tgz
tar -xzvf firecracker-v${FC_VERSION}-x86_64.tgz
mv release-v${FC_VERSION}-x86_64/firecracker-v${FC_VERSION}-x86_64 /usr/local/bin/firecracker
rm -rf release-v${FC_VERSION}-x86_64

echo "Enabling port forwarding"
sh -c "echo 1 > /proc/sys/net/ipv4/ip_forward"
iptables -P FORWARD ACCEPT
