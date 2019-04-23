#!/bin/bash -ex
# Copyright 2015 Red Hat, Inc.
#
# Licensed under the Apache License, Version 2.0 (the "License"); you may
# not use this file except in compliance with the License. You may obtain
# a copy of the License at
#
#      http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS, WITHOUT
# WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied. See the
# License for the specific language governing permissions and limitations
# under the License.

github_username=$1
github_useremail=$2
github_token=$3

set -e

function pull_and_config_labkeeper()
{
    if [ ! -d ~/inotify/ ];then
        mkdir inotify
    fi
    if [ ! -d ~/inotify/labkeeper/ ];then
        echo "pull labkeeper repo"
        hub clone https://github.com/theopenlab-ci/labkeeper ~/inotify/labkeeper
        echo "clone labkeeper repo success!"
        cd ~/inotify/labkeeper
        hub config user.name ${github_username}
        hub config user.email ${github_useremail}
        hub remote add upstream  https://github.com/theopenlab/labkeeper
        echo "pull and config labkeeper success!"
    fi
    echo "The repo labkeeper is already there!"
}

# to avoid being prompted username and password when exec git commands
touch ~/.git-credentials
echo "https://${github_username}:${github_token}@github.com" > ~/.git-credentials
hub config --global credential.helper store

pull_and_config_labkeeper

cd ~/inotify/labkeeper/
hub checkout master

# maybe some errors happened last time, the branch wont be clean
is_clean="`hub status |grep clean`"
if [[ -n $is_clean ]];then
    echo 'branch is clean!'
else
    echo 'branch is not clean!!'
    hub reset --hard HEAD
fi
