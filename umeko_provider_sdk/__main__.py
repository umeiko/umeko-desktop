"""Usage: python -m umeko_provider_sdk validate FOLDER | pack FOLDER OUTPUT.zip"""
import argparse
from .packages import validate_folder, pack_package

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument("command", choices=("validate", "pack"))
parser.add_argument("folder")
parser.add_argument("output", nargs="?")
args = parser.parse_args()
if args.command == "pack":
    if not args.output: parser.error("pack requires OUTPUT.zip")
    pack_package(args.folder, args.output)
else:
    manifest, _, _ = validate_folder(args.folder)
    print(f"Valid: {manifest['id']} {manifest['version']} (API {manifest['apiVersion']})")
