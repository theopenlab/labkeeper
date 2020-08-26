#!/bin/bash -x
github_token=$1
login_key=$2
target_ip=$3

function post_issue()
{
    if [ ! -d ~/badge_check/ ];then
        mkdir ~/badge_check
    fi

    if [ ! -d ~/badge_check/openlab/ ];then
        hub clone https://github.com/theopenlab/openlab ~/badge_check/openlab
    fi

    cd ~/badge_check/openlab/
    if [ -f ~/badge_check/badge_check.issue ];then
        exit 0
    fi
    issue_header="[Labcheck] "`date +%Y%m%d%H%M`" OpenLab Badge Check Failed"
    issue_content="Check report as below:\n\`\`\`"
    echo -e $issue_header"\n\n"$issue_content > ~/badge_check/badge_check.issue
    echo -e "OpenLab Badge Service can not be recovered after tried. Please go to check the env manually." \
    >> ~/badge_check/badge_check.issue
    echo -e "\`\`\`\n\ncc: @bzhaoopenstack">> ~/badge_check/badge_check.issue
    export GITHUB_TOKEN=${github_token}
    hub issue create -F ~/badge_check/badge_check.issue
}

function try_to_recover()
{
    ssh -o StrictHostKeyChecking=no -o ConnectTimeout=10 -o PasswordAuthentication=no -i $login_key \
    zuul@$target_ip "cd; ./setup-openlab-badge.sh &"
    if [ $? -eq 0 ]; then
            echo "======== RECOVER SUCCESS ========"
            break;
    else
            echo "======== RECOVER ERROR ========"
            post_issue
    fi

}

try_count=1
max_try_count=6
echo "======== Health Check START  ========"
while [ 0 -eq 0 ]
do
  if [ $try_count -gt $max_try_count ]; then
          echo "======== Check ERROR ========"
          try_to_recover
          break;
  fi
  echo "======== Try ${try_count} ========"
  ans=`curl http://openlabtesting.org:15000/badge-health`

  if [ $ans == "Alive" ]; then
          echo "======== Check SUCCESS ========"
          break;
  else
          echo "======== ERROR OCCUR, retry in 10 seconds ========"
          try_count=$[${try_count}+1]
          sleep 10
  fi
done
