# labkeeper

A tool developed by Ansible for deploying and managing OpenLab CI infrastructures

- License: Apache License, Version 2.0
- Source: https://github.com/theopenlab/labkeeper

## Description

Labkeeper is a collection of Ansible playbooks and roles used to deploy and manage
OpenLab CI infrastructures.

This project is initially forked from the [OpenStack Windmill project](https://github.com/openstack/windmill), and
modified for specific [OpenLab](https://github.com/theopenlab) CI system deployment.

## Steps to deploy a CI system using Labkeeper

1. Choose a deployment mode under the `inventory/` directory. Labkeeper now supports:

   - Production Mode (`openlab`):

     Using two nodes to create a new CI system. One is for nodepool services, the other is for zuul services

   - Production HA Mode (`openlab-ha`)

     Using five nodes to create a new CI system. Two is for Master cluster, the other two is for Slave cluster, the last one is for zookeeper cluster. In this mode, the service on slave cluster won't start. Only the service data will be synced.

   - Production HA Recover Mode (Work In Progress)

     Recovering a new Slave cluster based on the existing Master cluster.

   - All In One Mode (`allinone`)

     Using only one node to create a new CI system. All components will be deployed there.

   - ALL In One HA Mode (`allinone-ha`)

     Using two nodes to  create a new CI system. One is for Master, the other one is for Slave

   - ALL In One HA Recover Mode (Work In Progress)

     Recovering a new Slave node based on the existing Master node.

2. Check and modify the configuration yaml files base one the mode you choose.

   - Modify the `nodepool` and `zuul` servers IP address if needed.
   - Replace the `github_acc_token` field with github personal access token, which need to be
     manually generated in [Github token](https://github.com/settings/tokens).
   - Check the `github_app_key_file`, `zuul_tenant_name`, `zuul_public_ip`, etc.

3. Create an `openlab.pem` file with SSH private key to access servers to deploy CI services,
   and `vault-password.txt`  file with ansible vault password as content.

4. Base on the mode you choose, for example Production Mode, run following script to start deployment:

   ```
   $ export ANSIBLE_REMOTE_USER=ubuntu
   $ export DPLOY_TYPE=openlab
   $ ./deploy.sh
   ```

5. After finishing deploying, please update the github app webhook URL in your github app, e.g. modify the [allinoneopenlab app](https://github.com/settings/apps/liu-openlab-ci) or [theopenlab app](https://github.com/organizations/theopenlab/settings/apps/theopenlab-ci) webhook URL.

6. Update the log server `fqdn` and host key(`secrets.yaml`) in the jobs config repo (`openlab-zuul-jobs`).

## Deploy a new slave of a master of CI system

This situation is used to recover the slave parts of a openlab CI system in HA deployment, in case the
**master** has down and the **slave** becoming the new **master**, we need to supply a new **slave**
for the new **master**.

1. Check andi modify the `inventory/openlab-new-slave.yaml` before deploying, you may need to config the new
   slave `nodepool` and `zuul` hosts, and the old `nodepool` and `zuul` hosts IP, also you can choose to sync
   the old **zuul** database to new slave or not.

2. Run the `deploy_new_slave.sh` script

## TODO items

- Fix some workaround approaches and make more variables in playbooks configurable.
- Add support for monitoring and heath check functions.
