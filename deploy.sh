#!/bin/bash
ARGS=`getopt -a -o u:d:e:h -l user:,deploy-type:,extra-vars:,help -- "$@"`
eval set -- "${ARGS}"

dep_choice="allinone allinone-ha openlab openlab-ha new-slave"

function usage() {
    echo "Usage: ./deploy.sh [OPTION]..."
    echo "OpenLab deploy tool."
    echo "-u, --user         specify the Ansible remote user performing deployment
                   or using ANSIBLE_REMOTE_USER env to specify, default option is: ubuntu"
    echo "-d, --deploy-type  specify one of: '${dep_choice}'
                   as deployment type, required"
    echo "-e, --extra-vars   extra vars passed to Ansible command"
    echo "-h, --help         display this help and exit"
}

while true
do
    case "$1" in
    -u|--user)
        ansible_user="$2"
        shift
        ;;
    -d|--deploy-type)
        dep_type="$2";
        if ! [[ ${dep_choice} =~ ${dep_type} ]];then
            "please specify one of '${dep_choice}' as deployment type"
            exit 1
        fi
        shift
        ;;
    -e|--extra-vars)
        extra_vars="$2"
        shift
        ;;
    -h|--help)
        usage
        exit 1
        ;;
    --)
        shift
        break
        ;;
    esac
shift
done
[[ "$dep_type" == "" ]] && echo "-d/--deployment option is required" && usage && exit 1

cd $(dirname "$0") && pwd

if [ -f openlab.pem ]; then
    sudo chmod 600 openlab.pem
else
    echo "Please add 'openlab.pem' private key file to access ansible target hosts!"
    exit 1
fi

if [ ! -f vault-password.txt ]; then
    echo "Please add 'vault-password.txt' with ansible vault password as content!"
    exit 1
fi

export ANSIBLE_REMOTE_USER=${ansible_user:-${ANSIBLE_REMOTE_USER:-ubuntu}}
[[ "$extra_vars" != '' ]] && ansible_extra_vars="-e '${extra_vars}'"

sudo apt update -y
sudo apt install python python-pip python3 python3-pip kpartx qemu-utils curl python-yaml debootstrap libffi-dev libssl-dev -y
sudo pip install -U pip setuptools wheel virtualenv ansible
if [[ "$dep_type" == "new-slave" ]];then
    ansible-playbook -i inventory/openlab-ha.yaml -i inventory/openlab-new-slave.yaml -l slave-hosts playbooks/site.yaml  ${ansible_extra_vars}
    ansible-playbook -i inventory/openlab-ha.yaml -i inventory/openlab-new-slave.yaml playbooks/conf-new-slave.yaml  ${ansible_extra_vars}
else
    ansible-playbook -i inventory/${dep_type}.yaml  playbooks/site.yaml ${ansible_extra_vars}
fi
