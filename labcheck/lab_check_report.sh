github_token=$1

set -e

# the default path of cron is /usr/bin:/bin, add hub/openlab path to PATH
export PATH=/usr/local/bin:$PATH

if [ ! -d ~/labcheck/ ];then
    mkdir ~/labcheck
fi

if [ ! -d ~/labcheck/openlab/ ];then
    echo "[Labcheck] Start to clone openlab repo"
    hub clone https://github.com/theopenlab/openlab ~/labcheck/openlab
    echo "[Labcheck] Clone openlab repo success!"
fi

cd ~/labcheck/openlab/
issue_header="[Labcheck] "`date +%Y%m%d%H%M`" OpenLab Environment Check Failed"
issue_content="Check report as below:\n\`\`\`"
echo -e $issue_header"\n\n"$issue_content > ~/labcheck/labcheck.issue

if ! openlab check --nocolor >> ~/labcheck/labcheck.issue; then
    echo -e "\`\`\`\n\ncc: @theopenlab/ops">> ~/labcheck/labcheck.issue
    echo "[Labcheck] Check failed, report to openlab issue."
    export GITHUB_TOKEN=${github_token}
    hub issue create -F ~/labcheck/labcheck.issue
fi

echo `date +%Y-%m-%d-%H:%M`" [Labcheck] Labcheck completed!"
