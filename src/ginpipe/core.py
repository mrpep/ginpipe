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

logger.remove()
logger.add(sys.stderr, format="{time} {level} {message}", filter="my_module", level="WARNING", colorize=True)

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
        str_parts = k.split('.')
        module = '.'.join(str_parts[:-1])
        module = importlib.import_module(module)
        fn_name = str_parts[-1]
        fn = getattr(module, fn_name)
        imported_objs = {fn_name: fn}
    else:
        raise Exception(f'Could not find module {k}')

    return module, imported_objs
    
def gin_configure_externals(flags):
    module_list = flags['module_list']
    ms = {}
    log_str = '\nAvailable objects in gin:\n---------------------------------------------\n'
    if 'module_list_str' in flags:
        ms.update({l.split(':')[0].strip(): l.split(':')[1].strip() for l in flags['module_list_str'].split('\n') if ':' in l})
    else:
        module_list = flags['module_list']
        for m in module_list:
            with open(m, 'r') as f:
                ls = f.read().splitlines()
            ms.update({l.split(':')[0].strip(): l.split(':')[1].strip() for l in ls})
        module_list_str = ""
        for k,v in ms.items():
            module_list_str += "{}: {}\n".format(k,v)
        flags['module_list_str'] = module_list_str
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
    list_unfinished=False
    list_acc=''
    unfinished_type = ''
    unfinished_k = ''
    for l in lines:
        if list_unfinished:
            if unfinished_type == '+=':
                lines_to_erase.append(l)
            if ']' not in l:
                list_acc += l.strip()
            else:
                list_acc += l.strip()
                list_unfinished=False
                if unfinished_type == '+=':
                    if unfinished_k in config_as_dict:
                        config_as_dict[unfinished_k] = concat_lists(config_as_dict[unfinished_k], list_acc)
                        append_keys.append(unfinished_k)
                    else:
                        config_as_dict[unfinished_k] = list_acc
                        append_keys.append(unfinished_k)
                        lines_to_erase.append(l)
                elif unfinished_type == '=':
                    config_as_dict[unfinished_k] = list_acc
                list_acc = ''


        elif not (l.isspace() or l == ''):
            indent = n_indent(l)
            if indent == 0:
                prefix = ''
            if '+=' in l:
                k,v = l.split('+=')
                k = add_prefix_to_key(prefix,k)
                if ('[' in v) and (']' not in v):
                    list_unfinished = True
                    list_acc += v
                    unfinished_type = '+='
                    unfinished_k = k
                elif ('[' in v) and (']' in v):
                    if k in config_as_dict:
                        config_as_dict[k] = concat_lists(config_as_dict[k], v)
                    else:
                        config_as_dict[k] = v
                lines_to_erase.append(l)
                append_keys.append(k)
            elif '=' in l:
                k,v = l.split('=')
                k = add_prefix_to_key(prefix,k)
                if ('[' not in v) or (('[' in v) and (']' in v)):
                    config_as_dict[k] = v
                else:
                    list_unfinished = True
                    list_acc += v
                    unfinished_type = '='
                    unfinished_k = k
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

def load_template(block_data, config_path):
    template_path = Path(Path(config_path).parent, block_data['template'][1:-1])
    with open(template_path, 'r') as f:
        template = f.read()
    block_data.pop('template')
    for k,v in block_data.items():
        template = template.replace('{'+k+'}', v[1:-1])
    return [template]

def process_templates(config, config_path):
    lines = config.split('\n')
    block_start = None
    block_data = {}
    i=0
    new_lines = []
    while i < len(lines):
        if lines[i].strip() == '!load_template:':
            block_start = i
        elif block_start is not None:
            if len(lines[i].lstrip()) < len(lines[i]):
                #This means we are in an indented block
                data_i = lines[i].split('=')
                block_data[data_i[0].strip()] = data_i[1].strip()
            else:
                #Out of block, so we have gathered all info regarding the template loading
                new_data = load_template(block_data, config_path)
                new_lines.extend(new_data)
                block_start = None
                block_data = {}
        else:
            new_lines.append(lines[i])
        i+=1
    if block_start is not None:
        new_data = load_template(block_data, config_path)
        new_lines.extend(new_data)

    return '\n'.join(new_lines)

def gin_parse_with_flags(state, flags):
    consolidated_config = ''
    if 'config_str' in flags:
        for c in flags['config_str']:
            consolidated_config += c + '\n'
    else:
        flags['config_str'] = []
        for c in flags['config_path']:
            with open(c,'r') as f:
                config_i = f.read()
            config_i = process_templates(config_i, c)
            flags['config_str'].append(config_i)
            consolidated_config += config_i + '\n'
            
    consolidated_config = apply_mods(consolidated_config, flags['mods'])
    state, consolidated_config = configure_defaults(state, consolidated_config)
    state, consolidated_config = process_appends(state, consolidated_config)
    state,consolidated_config = get_initial_state(state,consolidated_config)
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
    config_log_path = Path(state.output_dir,'config.gin')
    if not config_log_path.parent.exists():
        config_log_path.parent.mkdir(parents=True)
    with open(config_log_path,'w') as f:
        f.write(gin.config_str())

    return state

def save_state(state):
    output_path = Path(state.output_dir,'state.pkl')
    if not output_path.parent.exists():
        output_path.parent.mkdir(parents=True)
    state.operative_config = gin.operative_config_str()
    state.save(output_path)

@gin.configurable
def execute_pipeline(state, tasks=None, execution_order='sequential', output_dir=None, cache=True, is_main=False):
    valid_execution_orders = ['sequential']
    if (Path(state.output_dir,'state.pkl').exists()) and cache and is_main:
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