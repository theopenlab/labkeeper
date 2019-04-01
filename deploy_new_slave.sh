#!/bin/bash

echo "Before deploying a new salve env, please check the 'inventory/openlab-new-slave.yaml' file!"
ansible-playbook -i inventory/openlab-ha.yaml -i inventory/openlab-new-slave.yaml -l slave-hosts playbooks/site.yaml
ansible-playbook -i inventory/openlab-ha.yaml -i inventory/openlab-new-slave.yaml playbooks/conf-new-slave.yaml
