========
windmill
========

A tool developed by Ansible used to deploy OpenLab CI environment.

* License: Apache License, Version 2.0
* Source: https://github.com/liu-sheng/windmill

Description
-----------

Windmill is a collection of Ansible playbooks and roles used to deploy and operate
OpenLab Continuous Integration (CI) tools.

This project is initially forked from the `OpenStack Windmill project`_, and
modified for specific `OpenLab`_ CI system deployment.

.. _OpenStack Windmill project: http://git.openstack.org/cgit/openstack/windmill/
.. _OpenLab: https://github.com/theopenlab

Steps to use
------------

1. Update the packages list and upgrade on the ansible running server::

   $ apt update -y && apt upgrade -y

2. Install pip by apt command::

   $ apt-get install python-pip -y

3. Install ansible by pip command::

   $ pip install ansible

4. Switch to the user to run deployment (`ubuntu` as usual), the user should match the access
   key `openlab.pem`, and then clone this project. The following 5~7 steps also need to run
   with this user.

5. Create a `vault-password.txt` file with ansible vault password as content under this project
   root directory.

6. Create an `openlab.pem` file with SSH private key to access servers to deploy CI services,
   the key file should have right `600` permission, and the owner should be the user to run
   ansible playbooks.

7. Check the configuration files under the `config/` directory and the `inventory` files, maybe
   need to modify some fields:

   - Replace the `github_acc_token` field with github personal access token, which need to be
     manually generated in `Github token`_
   - And the `github_app_key_file`, `zuul_tenant_name`, `zuul_public_ip`, etc.

.. _Github token: https://github.com/settings/tokens

8. Run ansible playbooks with specific inventory and enjoy, for an example::

    $ ansible-playbook playbooks/site.yaml -i inventory/allinone.yaml

9. Change the github app webhook URL, e.g. modify the `allinoneopenlab app`_ webhook URL.

.. _allinoneopenlab app: https://github.com/settings/apps/liu-openlab-ci

10. Update the log server `fqdn` and host key in the jobs config repo (`openlab-zuul-jobs`).

TODO items
----------

* Fix some workaround approaches and make more variables in playbooks configurable.

* Add support for monitoring and heath check functions.
