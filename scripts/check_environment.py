"""Inspect centrally supplied dependencies without installing anything."""
import argparse
import importlib
from pathlib import Path
import re
import sys


def requirements():
    # The dependency list is a single literal in this project's metadata.
    import ast
    metadata = (Path(__file__).resolve().parents[1] / "pyproject.toml").read_text()
    names = re.search(r"^dependencies\s*=\s*(\[[^\n]+\])", metadata, re.MULTILINE)
    python = re.search(r'^requires-python\s*=\s*">=([0-9.]+)"', metadata, re.MULTILINE)
    if not names or not python:
        raise ValueError("Cannot read dependency requirements from pyproject.toml")
    return python.group(1), ast.literal_eval(names.group(1))


def version_tuple(value):
    match = re.match(r"\d+(?:\.\d+)*", value)
    if not match:
        raise ValueError(f"Unrecognized package version: {value}")
    return tuple(map(int, match.group().split(".")))


def inspect(include_tests=False):
    minimum_python, packages = requirements()
    failures = []
    print(f"Python {sys.version.split()[0]}: {sys.executable}")
    if sys.version_info[:3] < version_tuple(minimum_python):
        failures.append(f"Python >= {minimum_python} is required")
    if sys.prefix != sys.base_prefix:
        failures.append("Use the CVMFS/cmsenv Python directly, without a virtual environment")
    if include_tests:
        packages = packages + ["pytest>=7"]
    aliases = {"PyYAML": "yaml", "scikit-learn": "sklearn"}
    for requirement in packages:
        name, operator, minimum = requirement.partition(">=")
        if not operator:
            raise ValueError(f"Unsupported dependency specification: {requirement}")
        try:
            module = importlib.import_module(aliases.get(name, name))
            version = module.__version__
            print(f"  {name} {version}: {module.__file__}")
            if version_tuple(version) < version_tuple(minimum):
                failures.append(f"{name} {version} is too old; require >= {minimum}")
        except Exception as error:
            failures.append(f"{name}: {error}")
    if failures:
        print("Environment check failed:\n  " + "\n  ".join(failures), file=sys.stderr)
        print("Select a compatible CVMFS view, then repeat this check in a fresh shell.", file=sys.stderr)
        return 1
    print("Environment imports and minimum versions OK")
    return 0


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--tests", action="store_true", help="Also require pytest for the test suite")
    args = parser.parse_args()
    sys.exit(inspect(args.tests))
