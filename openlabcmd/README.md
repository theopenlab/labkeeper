# OpenLab management tool

This is the command line tool for OpenLab management.

## How to use

You can install from source or just use `pip install openlabcmd`.

Before use `openlabcmd`, you should create or update the config file
`openlab.conf`. Use `-c` to specified one. The tool will try to find
the file in paths `/etc/openlab/openlab.conf`, `~/openlab.conf` and
`/usr/local/etc/openlab/openlab.conf` if it's not provided by user.

## Supported features

### check
Health check tool for checking OpenLab CI infrastructures.

```
usage: openlab check [-h] [--type TYPE] [--cloud CLOUD] [--nocolor]
                     [--recover]

optional arguments:
  -h, --help     show this help message and exit
  --type TYPE    Specify a plugin type, like 'nodepool', 'jobs'. Default is
                 'all'.
  --cloud CLOUD  Specify a cloud provider, like 'otc', 'vexxhost'. Default is
                 'all'.
  --nocolor      Enable the no color mode.
  --recover      Enable the auto recover mode.
```

### ha
OpenLab HA cluster management commands.

#### node

CRUD for node

* openlab ha node list
* openlab ha node get
  ```
  usage: openlab ha node get [-h] name
  positional arguments:
    name        The node hostname.
  ```
* openlab ha node init
  ```
  usage: openlab ha node init [-h] --type {nodepool,zuul,zookeeper-only}
                              --role {master,slave} --ip IP name

  positional arguments:
    name                  The new node hostname, it should be global unique.
                          Format: {cloud-provider}-openlab-{type}

  optional arguments:
    -h, --help            show this help message and exit
    --type {nodepool,zuul,zookeeper-only}
                          The new node type. Choose from 'nodepool', 'zuul' and
                          'zookeeper-only'
    --role {master,slave}
                          The new node role. It should be either 'master' or
                          'slave'.
    --ip IP               The new node's public IP.
  ```
* openlab ha node set
  ```
  usage: openlab ha node set [-h] [--maintain {yes, no}] [--role {master,slave}] name

  positional arguments:
    name                  The node hostname.

  optional arguments:
    -h, --help            show this help message and exit
    --maintain MAINTAIN   Set the node to maintained status.
    --role {master,slave}
                          Update node role. It should be either 'master' or
                          'slave'. Be careful to update the role, you should
                          not update role except emergency situations, because
                          it will impact checking scope of HA monitor , HA
                          monitor will check and update it with built-in policy
                          automatically.

  ```
* openlab ha node delete
  ```
  usage: openlab ha node delete [-h] name

  positional arguments:
    name        The node hostname.
  ```

#### service

Get or list the service running in cluster.

* openlab ha service list
* openlab ha service get
  ```
  usage: openlab ha service get [-h] [--role {master,slave,zookeeper}] name

  positional arguments:
    name                  service name.

  optional arguments:
    -h, --help            show this help message and exit
    --role {master,slave,zookeeper}
                          The role of the node where the service run. It must be
                          sepcified if the service is 'mysql' or 'zookeeper'.
  ```
