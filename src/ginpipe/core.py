import gin
import datetime
import joblib
import importlib
import inspect
from pathlib import Path
import time
from loguru import logger
import sys
import ast

def get_objs_from_module(m):
    imported_objs = {}
    for fn in inspect.getmembers(m, inspect.isfunction):
        imported_objs[fn[1].__name__] = fn[1]
    for c in inspect.getmembers(m, inspect.isclass):
        imported_objs[c[1].__name__] = c[1]
    return imported_objs

def import_module(k):
    if Path(k.replace('.','/')+'/__init__.py').exists():
        spec = importlib.util.spec_from_file_location(k,k.replace('.','/')+'/__init__.py')
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        sys.modules[module.__name__] = module
        parent_module_path = module.__file__.replace('/'+k.replace('.','/')+'/__init__.py','')
        if parent_module_path not in sys.path:
            sys.path.append(parent_module_path)
        imported_objs = get_objs_from_module(module)
    elif importlib.util.find_spec(k) is not None:
        module = importlib.import_module(k)
        imported_objs = get_objs_from_module(module)
    elif importlib.util.find_spec('.'.join(k.split('.')[:-1])) is not None:
        try:
            str_parts = k.split('.')
            module = '.'.join(str_parts[:-1])
            module = importlib.import_module(module)
            fn_name = str_parts[-1]
            fn = getattr(module, fn_name)
            imported_objs = {fn_name: fn}
        except:
            from IPython import embed; embed()
    else:
        raise Exception(f'Could not find module {k}')

    return module, imported_objs
    
def gin_configure_externals(flags):
    module_list = flags['module_list']
    ms = {}
    log_str = '\nAvailable objects in gin:\n---------------------------------------------\n'
    if 'module_list_str' in flags:
        ms.update({l.split(':')[0].strip(): l.split(':')[1].strip() for l in flags['module_list_str'].split('\n')})
    else:
        module_list = flags['module_list']
        for m in module_list:
            with open(m, 'r') as f:
                ls = f.read().splitlines()
            ms.update({l.split(':')[0].strip(): l.split(':')[1].strip() for l in ls})

    for k, v in ms.items():
        module, imported_objs = import_module(k)
        log_str += f'{v}\n'
        for obj_name, obj in imported_objs.items():
            log_str += f'\t{obj_name}\n'
            gin.config.external_configurable(obj, module=v)
    logger.debug(log_str)

def configure_defaults(state, config):
    def find_macro(key, config, mods):
        val = [x.split('=')[-1] for x in config.split() if x.startswith(key)]
        if len(val)>0:
            val = val[-1]
        else:
            val = None
        if (mods is not None) and (key in mods):
            val = mods[key]
        return val

    exp_name = state.flags.get('experiment_name',datetime.datetime.now().strftime('%y-%d-%m-%H%M%S'))
    proj_name = state.flags.get('project_name','features2wav')
    config_from_flags = {
        'EXPERIMENT_NAME': exp_name,
        'PROJECT_NAME': proj_name,
        'OUTPUT_DIR': 'experiments/{}/{}'.format(proj_name,exp_name)
    }
    mods = state.flags.get('mods', [])
    mods = {k.split('=')[0]: k.split('=')[1] for k in mods}
    for k,v in config_from_flags.items():
        already_exists = find_macro(k, config, mods)
        print('{}: {}'.format(k, already_exists))
        if already_exists is None:
            if isinstance(v,str) and not v.startswith('%'):
                v = "'{}'".format(v)
            config += "{}={}\n".format(k,v)
        if k == 'OUTPUT_DIR':
            state.output_dir = config_from_flags['OUTPUT_DIR'] if already_exists is None else already_exists.replace("'","")
    
    return state, config

def apply_mods(config, mods):
    for m in mods:
        config += m + '\n'
    return config

def n_indent(x):
    return [xi == ' ' for xi in x].index(False)

def concat_lists(x,y):
    return x.strip()[:-1] + ',' + y.strip()[1:]

def add_prefix_to_key(prefix, k):
    k = k.strip()
    if prefix != '':
        return prefix + '.' + k
    else:
        return k

def process_appends(state, config):
    lines = config.split('\n')
    config_as_dict = {}
    append_keys = []
    lines_to_erase = []
    prefix = ''
    for l in lines:
        if not (l.isspace() or l == ''):
            indent = n_indent(l)
            if indent == 0:
                prefix = ''
            if '+=' in l:
                k,v = l.split('+=')
                k = add_prefix_to_key(prefix,k)
                if k in config_as_dict:
                    config_as_dict[k] = concat_lists(config_as_dict[k], v)
                    append_keys.append(k)
                else:
                    config_as_dict[k] = v
                    append_keys.append(k)
                lines_to_erase.append(l)
            elif '=' in l:
                print(l)
                k,v = l.split('=')
                k = add_prefix_to_key(prefix,k)
                config_as_dict[k] = v
            elif ':' in l:
                prefix = l.split(':')[0]
    for l in lines_to_erase:
        lines.remove(l)
    for a in set(append_keys):
        new_line = '{}={}'.format(a,config_as_dict[a])
        lines.append(new_line)
    config = '\n'.join(lines)

    return state, config

def get_initial_state(state,config):
    inits_keys = [l for l in config.split('\n') if l.startswith('$')]
    for k in inits_keys:
        key, val = k[1:].split('=')
        try:
            val = ast.literal_eval(val)
        except:
            pass
        state[key] = val
        config = config.replace(k,'')

    return state, config

def gin_parse_with_flags(state, flags):
    consolidated_config = ''
    if 'config_str' in flags:
        for c in flags['config_str']:
            consolidated_config += c + '\n'
    else:
        for c in flags['config_path']:
            with open(c,'r') as f:
                config_i = f.read()
            consolidated_config += config_i + '\n'
    state,consolidated_config = get_initial_state(state,consolidated_config)
    consolidated_config = apply_mods(consolidated_config, flags['mods'])
    state, consolidated_config = configure_defaults(state, consolidated_config)
    state, consolidated_config = process_appends(state, consolidated_config)
    gin.parse_config(consolidated_config)
    state.operative_config = gin.operative_config_str()
    state.config_str = consolidated_config
    return state

class State(dict):
    __getattr__ = dict.__getitem__
    __setattr__ = dict.__setitem__
    __delattr__ = dict.__delitem__

    def __getstate__(self):
        return self.__dict__
    
    def __setstate__(self,d):
        self.__dict__ = d

    def save(self, output_path):
        d = {k:v for k,v in self.items() if k not in self.get('keys_not_saved',[])}
        #To avoid corrupted saved artifacts, first save it to a temp and then rename:
        temp_path = output_path.with_name('state_temp.pkl')
        joblib.dump(d,temp_path)
        if output_path.exists():
            output_path.unlink()
        temp_path.rename(output_path)


def setup_gin(flags):
    state = State()
    state.flags = flags
    gin_configure_externals(flags)
    state = gin_parse_with_flags(state, flags)

    return state

def save_state(state):
    output_path = Path(state.output_dir,'state.pkl')
    if not output_path.parent.exists():
        output_path.parent.mkdir(parents=True)
    state.operative_config = gin.operative_config_str()
    state.save(output_path)

@gin.configurable
def execute_pipeline(state, tasks=None, execution_order='sequential', output_dir=None, cache=True):
    valid_execution_orders = ['sequential']
    if (Path(state.output_dir,'state.pkl').exists()) and cache:
        state_ = joblib.load(Path(state.output_dir,'state.pkl'))
        for k,v in state_.items():
            if (k not in state) and (k != 'execution_times'):
                state[k] = v
    if execution_order == 'sequential':
        for t in tasks:
            logger.info('Running {}'.format(t.__name__))
            pt = time.process_time()
            wt = time.time()
            state = t(state)
            pt = time.process_time() - pt
            wt = time.time() - wt
            _ = state.setdefault('execution_times', {})
            i=0
            while True:
                name = '{}_{}'.format(t.__name__, i)
                if name in state['execution_times']:
                    i+=1
                else:
                    state['execution_times'][name] = {'wall_time': wt, 'process_time': pt}
                    break
            save_state(state)
    else:
        raise Exception('Execution order not recognized: {}. The following values are allowed: {}'.format(execution_order, valid_execution_orders))