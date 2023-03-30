from .core import setup_gin, execute_pipeline
import datetime
import argparse

def main():
    argparser = argparse.ArgumentParser(description='Execute arbitrary pipelines from gin configs')
    argparser.add_argument('config_path', nargs='+', default=[], help='Path to gin config files')
    argparser.add_argument('--experiment_name', type=str, default=datetime.datetime.now().strftime('%y-%d-%m-%H%M%S'),
                           help='Name for the experiment')
    argparser.add_argument('--project_name', type=str,
                           help='Name for the project', default='my_project')
    argparser.add_argument('--mods', dest='mods', nargs='+', default=[],
                           help='Modifications to config file')
    argparser.add_argument('--module_list', dest='module_list', nargs='+', default=[])
    
    flags = vars(argparser.parse_args())

    #Setup gin configs:
    state = setup_gin(flags)
    execute_pipeline(state)

if __name__ == '__main__':
    main()