# OpenLab management tool

This is the command line tool for OpenLab management.

## How to use

You can install from source or just use `pip install openlabcmd`. 

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
