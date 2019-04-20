#!/bin/bash -ex
sudo apt update -y
sudo apt install python python-pip python3 python3-pip kpartx qemu-utils curl \
    python-yaml debootstrap libffi-dev libssl-dev -y
sudo pip install -U pip setuptools wheel virtualenv ansible
