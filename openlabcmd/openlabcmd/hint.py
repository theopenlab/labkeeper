from openlabcmd import exceptions


HINTS = {
    "resource": [
        "export OS_CLOUD=vexxhost",
        "openstack router list -f value -c Name | grep openlab",
        "openstack subnet list -f value -c Name | grep openlab",
        "openstack network list -f value -c Name | grep openlab",
        "openstack keypair list -f value -c Name | grep openlab",
        "openstack server list -f value -c Name | grep openlab"
    ],
    "redundant": [
        "export OS_CLOUD=vexxhost",
        "echo $OS_CLOUD':'",
        "nodepool image-list | grep $OS_CLOUD | awk -F'|' '{print $6}' | sed 's/ //g' > file1",
        "openstack image list -f value -c Name | grep openlab-ubuntu > file2",
        "sort file1 file2 | uniq -u",
        "rm file1 file2"
    ]
}


class Hint(object):

    def __init__(self, htype):
        self.hints = HINTS
        self.htype = htype

    def print_hints(self):
        if self.htype == 'all':
            for h in HINTS:
                print("\n- Hint of %s:" % h)
                for hint in HINTS.get(h):
                    print(hint)
        elif self.htype in HINTS:
            print("\n- Hint of %s:" % self.htype)
            for hint in HINTS.get(self.htype):
                print(hint)
        else:
            raise exceptions.ClientError("No hints founded.")
