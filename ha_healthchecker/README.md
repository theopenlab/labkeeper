# OpenLab HA HealthChecker

OpenLab HA HealthChecker(ha_healthchecker) is a daemon service which is used for monitor and control OpenLab CI environment.

## Concept

First of all, let's introduce some concepts.

1. Master/Slave/Zookeeper Role

    There are three cluster roles in OpenLab HA development.
    
    `Master` is the cluster that OpenLab runs on.
    
    `Slave` is the cluster for backup, once Master is down, `ha_healthchecker` will switch OpenLab staff from Master to Slave and treat the Slave as the new Master to ensure OpenLab continue works.

    `Zookeeper` is the node that only runs zookeeper service which is required by zookeeper cluster deployment mode.

2. Zuul/Nodepool/Zookeeper Type

    There are three node types in OpenLab HA development.

    `Zuul` is the node that runs zuul related services.

    `Nodepool` is the node that runs nodepool related services.

    `Zookeeper `is the node that only runs zookeeper service. It's role is `zookeeper` as well.

3. Necessary/Unnecessary Service.
  
    There are many services run on OpenLab nodes.
    
    A necessary service is a service that must be always ran. Once it's down, OpenLab will be down and won't work any more. 

    An unnecessary service can be down for a period of time. (Default is 2 days). After that time, if it's still down, OpenLab will be treat as down.
    
    The service mapping is shown as below.
    ```
    service_mapping = {
        'master': {
            'zuul': {
                'necessary': ['zuul-scheduler', 'zuul-executor', 'zuul-web',
                              'gearman-job-server', 'mysql', 'apache2'],
                'unnecessary': ['zuul-merger', 'zuul-fingergw', 'zuul-timer-tasks']
            },
            'nodepool': {
                'necessary': ['nodepool-launcher'],
                'unnecessary': ['nodepool-timer-tasks', 'nodepool-builder',
                                'zookeeper']
            }
        },
        'slave': {
            'zuul': {
                'necessary': [],
                'unnecessary': ['mysql', 'rsyncd']
            },
            'nodepool': {
                'necessary': [],
                'unnecessary': ['zookeeper', 'rsyncd']
            }
        },
        'zookeeper': {
            'zookeeper': {
                'necessary': [],
                'unnecessary': ['zookeeper']
            }
        },
    }
    ```
## Status Matrix

Both `node` and `service` object have a property called `status`. There are some cases for it.

1. Node Status

    Node status contains:

    * `initializing`: It means that the node is new created and `ha_healthchecker` doesn't start working.

    * `up`: It means that the node works well, Both network and heartbeat are OK.

    * `down`: It means that the node's heartbeat is timeout and network is not pingable.

    * `maintaining`: It means that the node is under operation's force control. In this status, `ha_healthchecker` will be paused and operator can do anything for the node.

    ```
    +--------------+      +----+           +-------------+
    | Initializing +----->+ up +<--------->+ maintaining |
    +--------------+      +-+--+           +-------------+
                            ^
                            |
                            v
                         +--+---+
                         | down |
                         +------+
    ```
2. Service Status

    Service status contains:

    * `up`: It means the service works well. The process status in systemd is `running`.

    * `restarting`: It means the service hits error and `ha_healthchecker` will try to restart it to solve the problem.

    * `down`: It means the service hits error. `ha_healthchecker` can't solve the problem by restarting the service. The process status in systemd is not `running`. It may be caused by many cases, operator should debug by hand.

    ```
                         +----+
               +-------->+ up +<-----+
               |         +----+      |
               |                     |
               |                     |
               |                     |
               |                     |
               v                     |
         +-----+------+          +---+--+
         | restarting +--------->+ down |
         +------------+          +------+

    ```
## How it works

`ha_healthchecker` now includes **Refresh**, **Fix** and **Switch** functions. More will be added in the future if needed.

* **Refresh**

    `ha_healthchecker` checks OpenLab nodes and the services which run on them every 2 minutes. If everything is OK, the nodes/services' heartbeat will be refreshed. Otherwise the service will be marked as `restarting` or `down`.

* **Fix**

    Once any service hits error(that's said the service status in systemd is not **running**), `ha_healthchecker` will do the fix step. Here are some cases:

    1. If the service is a necessary service.
  
        a. If the service is marked as `restaring`, it'll be restarted max 3 times (by default).

        b. If the service is marked as `down`, `ha_healthchecker` will send a github issue to `openlab` repo and try to start switching Master and Slave.

    2. If the service is an unnecessary service.

        a. If the service is marked as `restarting`, it'll be restarted as well.

        b. If the service is marked as `down` but the the time doesn't hit the switch deadline(48 hours by default), `ha_healthchecker` will only send out a github issue.

        c. If the service is marked as `down` and the the time hits the switch deadline, `ha_healthchecker` will try to start switching Master and Slave.

* **Switch**

    Once **Fix** tell that OpenLab HA deployment need switch Master and Slave, and the configuration `allow_switch` is `True`. `ha_healthchecker` will send a github issue to `openlab` repo and do the switch work.

## Configuration

There are some configurations that used by `ha_healthchecker`. print `openlab ha config list` to get the value.

| Name | Default Value | Description |
| ---- | ------------- | ----------- |
| allow_switch | False | Whether allow switch the HA deployment or not. |
| dns_log_domain | test-logs.openlabtesting.org | The log service domain name. Usually it's `logs.openlabtesting.org`. |
| dns_master_public_ip | None | The IP of the master node that runs zuul-web. |
| dns_provider_account | None | The dns server account  for login. OpenLab use simpleDNS by default. |
| dns_provider_api_url | https://api.dnsimple.com/v2/ | The dns server API url for login. |
| dns_provider_token | None | The dns server token for login. |
| dns_slave_public_ip | None | The IP of the slave node that runs zuul-web.  |
| dns_status_domain | test-status.openlabtesting.org' | The zuul status web domain name. Usually it's `status.openlabtesting.org`. |
| github_app_name | None | The github app that used by openlab CI, Usually it's `theopenlab-ci`. |
| github_repo | None | The github repo that used by openlab CI, Usually it's `theopenlab/openlab`. |
| github_user_name | None | The user name used to login github. |
| github_user_password | None | The password used to login github. |
| github_user_token | None | The token used to login github. |
| heartbeat_timeout_second | 600 | How long the node is treated as down once the heartbeat won't be refreshed. |
| logging_level | DEBUG | The log level for `ha_healthchecker` itself. |
| service_restart_max_times | 3 | How many times that the service will be restarted once it's broken. |
| unnecessary_service_switch_timeout_hour | 48 | How long the switch will be happened once an unnecessary service is down. |

## How to use

Once OpenLab HA deployment is running, print `openlab ha node list` and `openlab ha service list`, you can find the HA cluster's status.

Usually Both nodes and services should be in `up` status. If any is not in `up` status, you should take a look at the github issue to see what's happened.

Then follow the guide in the github [issue](https://github.com/theopenlab/openlab/issues) of which title is prefixed with `[HA]`, you can fix HA cluster by hand.

Sometimes, if you want to maintain the cluster by hand during the `ha_healthchecker` working time, you should first set the related node to `maintaining` status. Print `openlab ha node set {node_name} --maintain yes`. Once you complete your work, don't forget to set it back.

If you want to manage config options, just print `openlab ha config list` or `openlab ha config set`

If you want to mange the cluster, we now provide two actions:

  1. openlab ha cluster repair.
  
      This will fix the cluster related settings, such as security group setting.

  2. openlab ha cluster switch.
  
      If you want to switch master and slave by hand. Use this command. Please note that this's a dangerous action. You should know that what'll happen before typing.

## Upgrade

We usually upgrade OpenLab environment once a month to keep the zuul and nodepool as new as possible. The upgrade workflow relies on `labkeeper` tool. Here is the upgrade step:

1. Execute command `./deploy.py openlab-ha list-change`

    This command will print the newly merged patches during last 31 days from zuul and nodepool community. Operator should read through these changes first. If any change may break current deployment, operator should fix it by hand.

2. Once the check is passed, execute command `./deploy.py openlab-ha upgrade`

    This command will upgrade the zuul and nodepool source code to the newest, re-generate zuul-web page and restart related services. During this action, zuul and nodepoool nodes will be set to `maintaining` status.

3. Once `upgrade` action is done, operator should check the deployment to ensure every service works well. If not, operator should fix it by hand.

4. Once all services work as expect, execute command `./deploy.py openlab-ha upgrade-complete`. This command will set all nodes back to `up` status. Congratulation! OpenLab environment upgrade is finished now.
