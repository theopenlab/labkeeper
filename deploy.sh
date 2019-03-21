#!/bin/bash

cd $(dirname "$0") && pwd

if [ -f openlab.pem ]; then
    sudo chmod 600 openlab.pem
else
    echo "Please add 'openlab.pem' private key file to access ansible target hosts!"
    exit 1
fi

if [ ! -f vault-password.txt ]; then
    echo "Please add 'vault-password.txt' with ansible vault password as content!"
    exit 1
fi

export ANSIBLE_REMOTE_USER=${ANSIBLE_REMOTE_USER:-ubuntu}
export DPLOY_TYPE=${DPLOY_TYPE:-allinone}

echo "Checking key and user access, 'ubuntu' user as default, you can set 'ANSIBLE_REMOTE_USER' to override!"
if ! ssh -o "StrictHostKeyChecking no" -i openlab.pem ${ANSIBLE_REMOTE_USER}@localhost 'pwd'; then
    echo "Please ensure you have created correct 'openlab.pem' and switched to the user which can access with this key!"
    exit 1
fi

sudo apt update -y
sudo apt install python python-pip python3 python3-pip kpartx qemu-utils curl python-yaml debootstrap libffi-dev libssl-dev -y
sudo pip install -U pip setuptools wheel virtualenv ansible
ansible-playbook playbooks/site.yaml -i inventory/${DPLOY_TYPE}.yaml
