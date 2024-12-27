from collections.abc import Mapping
import gin
from pathlib import Path
import torch
from ginpipe.core import gin_configure_externals
import re

def config_to_dict(config):
    with open(config,'r') as f:
        config = f.read()
    config_lines = config.split('\n')
    
    acc_val = ''
    acc_key = ''
    config_d = {}
    for l in config_lines:
        if not l.startswith('#'):
            if '=' in l:
                if acc_key != '':
                    config_d[acc_key]=acc_val
                acc_key=l.split('=')[0].strip()
                acc_val=l.split('=')[1].strip()
                if acc_val == '\\':
                    acc_val=''
            else:
                acc_val+=l.strip()
    config_d[acc_key] = acc_val
        
    return config_d

def fuzzy_get(d, key):
    gathered = []
    for k,v in d.items():
        if k.startswith(key):
            gathered.append((k, v))
        elif k.startswith(key.split('.')[-1]):
            gathered.append((k, v))
        elif '/' in key and k.startswith('{}/{}'.format(key.split('/')[0],key.split('/')[-1].split('.')[-1])):
            gathered.append((k,v))
    return gathered
            
def get_target_d(d, new_d, target):
    gathered = fuzzy_get(d, target)
    for l in gathered:
        target, val = l
        if '@' in val:
            k = re.findall(r'@([^,\s\[\]]+)', val)
        elif '%' in val:
            k = re.findall(r'%([^,\s\[\]]+)', val)
        else:
            k = None
        if k is not None:
            for ki in k:
                get_target_d(d, new_d, ki)
        new_d[target] = val

def get_model_config(config_path, targets, replacements, additions=None):
    d = config_to_dict(config_path)
    if additions is not None:
        for k,v in additions.items():
            d[k]=v
    pruned_config_str = ''
    pruned_config = {}
    for target in targets:
        get_target_d(d, pruned_config, target)
    for k,v in replacements.items():
        if k in pruned_config:
            pruned_config[v] = pruned_config.pop(k)
    for k,v in sorted(pruned_config.items()):
        if '.' not in k:
            pruned_config_str += '\n{}={}'.format(k,v)
    pruned_config_str+='\n'
    for k,v in sorted(pruned_config.items()):
        if '.' in k:
            pruned_config_str += '\n{}={}'.format(k,v)
    return pruned_config_str
