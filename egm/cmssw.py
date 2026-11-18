"""Small, dependency-free checks for a user-built CMSSW area."""
import hashlib
from pathlib import Path


PACKAGE = Path("Displaced_EGM_HLT/Ntuplizer")
LIBRARY = "libDisplacedEGMNtuplizerPlugins.so"


def checksum(path):
    h = hashlib.sha256()
    with open(path, "rb") as source:
        for block in iter(lambda: source.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def prebuilt_snapshot(config, source_package):
    """Check the installed package against the farm source; freeze its binary too."""
    base = Path(config["base"]).resolve()
    source_package = Path(source_package)
    installed = base / "src" / PACKAGE
    if not (base / ".SCRAM").is_dir() or not installed.is_dir():
        raise ValueError(f"Invalid CMSSW area or missing {PACKAGE}: {base}")
    if base.name != config["release"]:
        raise ValueError(f"cmssw.base must point to the selected release: {config['release']}")
    binary = base / "lib" / config["scram_arch"] / LIBRARY
    if not binary.is_file():
        raise ValueError(f"Missing compiled plugin: {binary}; run cmsenv and scram b -j 8 first")
    paths = sorted(p.relative_to(source_package) for p in source_package.rglob("*")
                   if p.is_file() and p.suffix in {".cc", ".h", ".xml", ".py"})
    installed_paths = sorted(p.relative_to(installed) for p in installed.rglob("*")
                             if p.is_file() and p.suffix in {".cc", ".h", ".xml", ".py"})
    if not paths or paths != installed_paths:
        raise ValueError("Installed CMSSW package differs from the source snapshot; rebuild and prepare a new farm")
    hashes = {}
    for relative in paths:
        actual = installed / relative
        if checksum(actual) != checksum(source_package / relative):
            raise ValueError(f"CMSSW source differs from the farm: {relative}; rebuild and prepare a new farm")
        if actual.stat().st_mtime_ns > binary.stat().st_mtime_ns:
            raise ValueError(f"CMSSW source is newer than the plugin: {relative}; run scram b")
        hashes[str(relative)] = checksum(actual)
    return dict(base=str(base), sources=hashes, library_sha256=checksum(binary))


def check_prebuilt(config, source_package, expected):
    actual = prebuilt_snapshot(config, source_package)
    if actual != expected:
        raise ValueError("Prebuilt CMSSW area changed after prepare; prepare a new farm and repeat local-test")
