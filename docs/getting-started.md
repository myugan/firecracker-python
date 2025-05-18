# Getting Started

## Pre-requisites

- **Platform**
  - Major Linux distributions such as Debian, Ubuntu, CentOS, Fedora, and ArchLinux.
- **Python** 3.8+
  - The `python3-nftables` module is required.
- **Firecracker**
  - Ensure that KVM is enabled.
- **Docker**
  - Follow the [Docker installation guide](https://docs.docker.com/engine/install/) for your platform.

### Platform

If you are using a cloud provider to run Firecracker, verify if nested virtualization is supported, as some providers may only support it for specific instance types.

### Python3

The `python3-nftables` module can be installed using a package manager on Debian-based distributions. For other distributions, you may need to check if the package name differs.

### Firecracker

Download the Firecracker binary directly from the [releases page](https://github.com/firecracker-microvm/firecracker/releases) and save it to `/usr/bin` or `/usr/local/bin`, depending on your operating system.

### KVM

To verify your system's compatibility with Firecracker, clone the Firecracker repository and run the environment check tool:

```bash
git clone https://github.com/firecracker-microvm/firecracker
cd firecracker
tools/devtool checkenv
```

Firecracker requires the [KVM Linux kernel module](https://www.linux-kvm.org/) for virtualization and emulation tasks. To check if KVM is enabled, run:

```bash
lsmod | grep kvm
```

You should see output similar to:

```bash
kvm_intel             483328  0
kvm                  1425408  1 kvm_intel
```

For more information, refer to the [KVM section](https://github.com/firecracker-microvm/firecracker/blob/main/docs/getting-started.md#kvm) in the official documentation.

## Building a rootfs Image

According to the [official documentation](https://github.com/firecracker-microvm/firecracker/blob/main/docs/getting-started.md#getting-a-rootfs-and-guest-kernel-image), a Linux kernel binary and an ext4 file system image (to use as rootfs) are required. By default, the module will download the Linux kernel binary if it is not available, so you may need to build your own ext4 file system.

Let's build the file system image using Docker. First, prepare the base **Dockerfile**:

> [!TIP]
> The **init** package must be installed to ensure Ubuntu runs properly once it is created, as the kernel will default to using the init binary as the main process.

```dockerfile
cat > Dockerfile<<EOF
FROM ubuntu:24.04

COPY ubuntu-24.04.pub /root/.ssh/authorized_keys
RUN apt-get update && \
    apt-get install -y systemd systemd-sysv init net-tools iputils-ping openssh-server file iproute2 curl nano vim dnsutils cloud-init && \
    touch /root/.hushlogin
EOF
```

Next, create an SSH key for the rootfs:

```bash
ssh-keygen -q -f ubuntu-24.04 -N ""
```

Build a Docker image and extract a root filesystem into a tarball:

```bash
mkdir -p /var/lib/firecracker/
docker build -t ubuntu-24.04 .
docker create --name extract ubuntu-24.04
docker export extract -o /var/lib/firecracker/rootfs.tar
docker rm -f extract
```

Then, build a root filesystem with 10GB of disk space:

```bash
fallocate -l 10G /var/lib/firecracker/rootfs.img
mkfs.ext4 /var/lib/firecracker/rootfs.img
TMP=$(mktemp -d)
mount -o loop /var/lib/firecracker/rootfs.img $TMP
tar -xvf /var/lib/firecracker/rootfs.tar -C $TMP
```

> [!NOTE]
> **/var/lib/firecracker/** is the default directory used by the SDK.

Before unmounting the filesystem, add DNS resolution configuration to enable the guest host to use package managers for updates:

```bash
echo "nameserver 8.8.8.8" > $TMP/etc/resolv.conf
umount $TMP
rm -rf $TMP
```

The root filesystem is now ready, and you can start using the module.

Remember to enable IP forwarding to ensure the guest VMM can access the internet.

```
sh -c "echo 1 > /proc/sys/net/ipv4/ip_forward"
iptables -P FORWARD ACCEPT
```

## Running Firecracker

Once everything is set up, you can start using the module and run your first microVM with the following script.

Open a Python 3 interpreter and execute the following code:

```
from firecracker import MicroVM

vm = MicroVM()
vm.create()
```

The microVM is now ready. You can SSH into the guest host by exiting the Python interpreter or using the following syntax:

```python
vm.connect(key_path="/path/to/key")
```

If you do not define an ID, a random 8-character ID will be generated, and the function will use this ID automatically.

> [!WARNING]
> The ID you define will be used to create a TAP device. Ensure it does not exceed 12 characters, as the device name will start with **tap_YOUR_ID**.