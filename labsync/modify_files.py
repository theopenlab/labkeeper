import commands
from ruamel.yaml import comments
from ruamel.yaml import YAML

yaml = YAML()
clouds_temp_file =  'clouds_temp.yaml'
secrets_temp_file =  'secrets_temp.yaml'
nodepool_temp_file =  'nodepool_temp.yaml'
old_secrets_decrypted_file =  'old_secrets_decrypted.yaml'

def get_tagged_scalar_object(ansible_encrypt_string):
    tag = comments.Tag()
    tag.value = '!vault'
    tagscalar = comments.TaggedScalar()
    tagscalar._yaml_tag = tag
    tagscalar.style = '|'
    tagscalar.value = ansible_encrypt_string
    return tagscalar

def ansible_encrypt_string(value):
    cmd = 'ansible-vault encrypt_string ' + value
    encrypt_string = commands.getoutput(cmd)
    # encrypt_string format like:
    # '!vault |\n          $ANSIBLE_VAULT;1.1;AES256\n          63386262356339373437316264616362386535623664316163386339643732623362613230636362\n          3165343361623631343436303961333938616337346261340a643564313434626466666161643732\n          64313337396662646663653437633934386438383039666664343437363666383737646664373239\n          6634663834653464330a326462373735636135313765656432303631633764663733313134393833\n          3533'
    # get string from $ANSIBLE_VAULT
    encrypt_value = unicode(encrypt_string[encrypt_string.find('$ANSIBLE_VAULT'):] + '\n')
    # remove the spaces
    encrypt_value = encrypt_value.replace(' ', '')
    return encrypt_value


def update_file_clouds_yaml():
    local_secrets = dict()
    # sync the update for file clouds.yaml, to hidden username and password, like {{ otc_username }}
    with open(clouds_temp_file) as f:
        content = yaml.load(f)
        cloud_names = content['clouds'].keys()
        for cloud in cloud_names:
            cloud_username = cloud + '_username'
            cloud_password = cloud + '_password'
            local_secrets[cloud_username] = content['clouds'][cloud]['auth']['username']
            local_secrets[cloud_password] = content['clouds'][cloud]['auth']['password']
            content['clouds'][cloud]['auth']['username'] = '{{ ' + cloud_username + ' }}'
            content['clouds'][cloud]['auth']['password'] = '{{ ' + cloud_password + ' }}'

    with open(clouds_temp_file, 'w') as nf:
        yaml.dump(content, nf)

    return local_secrets

def handle_key_new_added(new_secrets, old_secrets):
    keys_added = [item for item in new_secrets.keys() if item not in old_secrets.keys()]
    for key in keys_added:
        value = new_secrets[key]
        encrypt_value = ansible_encrypt_string(value)
        secrets_encrypted[key] = get_tagged_scalar_object(encrypt_value)

def handle_key_removed(new_secrets, old_secrets):
    keys_removed = [item for item in old_secrets.keys() if item not in new_secrets.keys()]
    for key in keys_removed:
        secrets_encrypted.pop(key)

def handle_key_diff(new_secrets, old_secrets):
    for k,v in old_secrets.items():
        if k in new_secrets:
            new_value = new_secrets[k]
            if v != new_value:
                encrypt_value = ansible_encrypt_string(new_value)
                secrets_encrypted[k] = get_tagged_scalar_object(encrypt_value)

def update_nodepool_yaml():
    with open(nodepool_temp_file) as lf:
        data = yaml.load(lf)

    # set pause: true for diskimages
    diskimages = data['diskimages']
    for index, val in enumerate(diskimages):
        val['pause'] = True

    with open(nodepool_temp_file, 'wb') as ntf:
        yaml.dump(data, ntf)

if __name__ == '__main__':
    yaml.preserve_quotes = True
    yaml.indent(mapping=2, sequence=4, offset=2)

    # update the nodepool.yaml
    update_nodepool_yaml()

    # update the clouds.yaml and get the local decrypted secrets
    local_secrets_decrypted = update_file_clouds_yaml()

    with open(secrets_temp_file) as secret_f:
        secrets_encrypted = yaml.load(secret_f)

    with open(old_secrets_decrypted_file) as f:
        old_secrets_decrypted = yaml.load(f)

    handle_key_diff(local_secrets_decrypted, old_secrets_decrypted)
    handle_key_new_added(local_secrets_decrypted, old_secrets_decrypted)
    handle_key_removed(local_secrets_decrypted, old_secrets_decrypted)

    # set explicit_start = True, then the yaml file will start with ---
    yaml.explicit_start = True
    with open(secrets_temp_file, 'w') as nf:
        yaml.dump(secrets_encrypted, nf)
