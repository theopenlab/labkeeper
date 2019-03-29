=========
labkeeper
=========

A tool developed by Ansible for deploying and managing OpenLab CI infrastructures

* License: Apache License, Version 2.0
* Source: https://github.com/liu-sheng/labkeeper

Description
-----------

Labkeeper is a collection of Ansible playbooks and roles used to deploy and manager
OpenLab CI infrastructures.

This project is initially forked from the `OpenStack Windmill project`_, and
modified for specific `OpenLab`_ CI system deployment.

.. _OpenStack Windmill project: https://github.com/openstack/windmill
.. _OpenLab: https://github.com/theopenlab

Steps to deploy a CI system by this tool
----------------------------------------
1. Check the configuration files under the `config/` directory and the `inventory` files, maybe
   need to modify some fields:

   - Modify the `nodepool` and `zuul` servers IP address if needed
   - Replace the `github_acc_token` field with github personal access token, which need to be
     manually generated in `Github token`_
   - Check the `github_app_key_file`, `zuul_tenant_name`, `zuul_public_ip`, etc.

.. _Github token: https://github.com/settings/tokens

2. Create an `openlab.pem` file with SSH private key to access servers to deploy CI services,
   and `vault-password.txt`  file with ansible vault password as content.

3. Select one type of deployment: `allinone`, `openlab`(refer to the inventory in `/inventory`),
   the `allinone` is default choice. Then run following script to start deployment::

    $ export DEFAULT_REMOTE_USER=ubuntu
    $ export DPLOY_TYPE=openlab
    $ ./deploy.sh

4. After finishing deploying Change the github app webhook URL, e.g. modify the `allinoneopenlab app`_
   or `theopenlab app`_ webhook URL.

.. _allinoneopenlab app: https://github.com/settings/apps/liu-openlab-ci
.. _theopenlab app: https://github.com/organizations/theopenlab/settings/apps/theopenlab-ci

5. Update the log server `fqdn` and host key(`secrets.yaml`) in the jobs config repo (`openlab-zuul-jobs`).

TODO items
----------

* Fix some workaround approaches and make more variables in playbooks configurable.

* Add support for monitoring and heath check functions.
