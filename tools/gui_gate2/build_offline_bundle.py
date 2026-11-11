"""Build a closed offline-library ZIP. Does not execute it or authorize deployment."""
import argparse,importlib.util,json
from pathlib import Path
P=Path(__file__).resolve().parent
def main(argv=None):
    parser=argparse.ArgumentParser();parser.add_argument('--output',type=Path,required=True);args=parser.parse_args(argv)
    spec=importlib.util.spec_from_file_location('offline_boundary',P/'boundary_check.py');m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)
    print(json.dumps(m.build_bundle(P,args.output)))
if __name__=='__main__':main()
