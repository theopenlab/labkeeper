========
windmill
========

A tool developed by Ansible used to deploy OpenLab CI environment.

* License: Apache License, Version 2.0
* Source: https://github.com/liu-sheng/windmill

Description
-----------

Windmill is a collection of Ansible playbooks and roles used to deploy OpenLab
Continuous Integration (CI) tools.

Steps to use
------------

1. update packages cache::

   $ apt update -y && apt upgrade -y

2. Install pip by apt command::

   $ apt-get update python-pip -y

3. Install ansible by pip command::

   $ pip install ansible

4. Create a `vault-password.txt` file with ansible vault password as content.

5. Create an `openlab.pem` file with SSH private key to access servers to deploy CI services,
   the key file should have right `600` permission, and the owner should be the user to run
   ansible playbooks.

6. Check the configuration files under the `config/` directory and the inventory files, maybe
   need to modify some fields:

   - the `github_acc_token` need to be a github personal access token, need manually generate
     the ``github_token``.
   - TODO

7. Run ansible playbooks with specific inventory and enjoy::

  $ ansible-playbook playbooks/allinone.yaml -i inventory/allinone.yaml


.. _github_token: https://github.com/settings/tokens