#!/bin/bash

cd $(dirname "$0") && pwd

if [ -f openlab.pem ]; then
    sudo chmod 600 openlab.pem
else
    echo "Please add 'openlab.pem' private key file to access ansible target hosts!"
    eixt 1
fi

if [ ! -f vault-password.txt ]; then
    echo "Please add 'vault-password.txt' with ansible vault password as content!"
    eixt 1
fi

echo "Checking private key and user, here we assume localhost is also one of the ansible target host, otherwise, please modify here!"
if ! ssh -o "StrictHostKeyChecking no" -i openlab.pem localhost 'pwd'; then
    echo "Please ensure you have created correct 'openlab.pem' and switched to the user which can access with this key!"
    exit 1
fi

sudo apt update -y
sudo apt install python python-pip python3 python3-pip kpartx qemu-utils curl python-yaml debootstrap libffi-dev libssl-dev -y
sodu pip install ansible
ansible-playbook playbooks/site.yaml -i inventory/allinone.yaml
