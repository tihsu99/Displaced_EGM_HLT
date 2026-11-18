"""Freeze small jobs locally; store event data only in scratch and EOS."""
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import tarfile

from .config import ROOT, digest, file_digest, read_yaml, validate_production, write_json
from .cmssw import PACKAGE, check_prebuilt, prebuilt_snapshot


def job_script(job_id):
    return '#!/bin/bash\nset -euo pipefail\njob_id=' + job_id + '''
# Condor transfers the worker, input JSON and source bundle into its scratch.
if [[ -n "${_CONDOR_SCRATCH_DIR:-}" && -f "$PWD/$job_id.json" ]]; then
  farm=$PWD
  job="$farm/$job_id.json"
else
  farm=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)
  job="$farm/jobs/$job_id.json"
  if [[ "${1:-}" != --local ]]; then
    echo "Local validation: bash $0 --local. Submit production with egm condor --farm $farm." >&2
    exit 2
  fi
fi
exec /bin/bash "$farm/worker.sh" "$job" "$farm/source.tar.gz" "$@"
'''


def resolve_files(sample, redirector):
    files = sample.get("files")
    if not files:
        dataset = sample["das"]
        if not re.fullmatch(r"/[^/\s]+/[^/\s]+/[^/\s]+", dataset):
            raise ValueError(f"Use a full DAS dataset name: {dataset}")
        result = subprocess.run(["dasgoclient", "--query", f"file dataset={dataset} instance={sample.get('instance', 'prod/global')}"], check=True, capture_output=True, text=True)
        files = result.stdout.splitlines()
    if not files:
        raise ValueError("No input files were resolved")
    result = []
    for source in files:
        if not isinstance(source, str) or any(c.isspace() for c in source) or "," in source:
            raise ValueError(f"Invalid input file: {source!r}")
        if source.startswith("/store/"):
            source = redirector.rstrip("/") + "/" + source
        if not source.startswith("root://") or not source.endswith(".root"):
            raise ValueError(f"Expected a ROOT XRootD URL or /store LFN: {source}")
        result.append(source)
    if len(result) != len(set(result)):
        raise ValueError("Duplicate input files in a sample")
    return sorted(result)


def prepare(config, farm, selected=None, max_files=None):
    cfg = read_yaml(config)
    samples = validate_production(cfg)
    if selected:
        unknown = set(selected) - samples.keys()
        if unknown:
            raise ValueError(f"Unknown or disabled samples: {sorted(unknown)}")
        samples = {name: samples[name] for name in selected}
    if max_files is not None and max_files <= 0:
        raise ValueError("max-files must be positive")
    if cfg["cmssw"]["runtime"] == "prebuilt":
        cfg["cmssw"]["base"] = str(Path(cfg["cmssw"]["base"]).resolve())
        cfg["cmssw"]["prebuilt_snapshot"] = prebuilt_snapshot(cfg["cmssw"], ROOT / PACKAGE.name)
    farm = Path(farm).resolve()
    if str(farm).startswith("/eos/"):
        raise ValueError("Condor submission metadata must be on /tmp, AFS, or another submit-host filesystem")
    if farm.exists():
        raise ValueError(f"Farm already exists: {farm}; use a new directory")
    file_lists = {name: resolve_files(sample, cfg["storage"]["redirector"])[:max_files] for name, sample in samples.items()}
    all_files = [source for files in file_lists.values() for source in files]
    if len(all_files) != len(set(all_files)):
        raise ValueError("An input file appears in multiple samples")
    replay = cfg["cmssw"].get("replay_pset")
    if replay:
        replay = (Path(config).resolve().parent / replay).resolve()
        if not replay.is_file():
            raise ValueError(f"Missing replay pset: {replay}")
        bundled_replay = Path(PACKAGE.name) / "test/replay_cfg.py"
        if replay != ROOT / bundled_replay:
            bundled_replay = Path("scripts/custom_replay_cfg.py")
        cfg["cmssw"]["replay_pset"] = str(bundled_replay)
    farm.mkdir(parents=True)
    (farm / "jobs").mkdir()
    (farm / "logs").mkdir()
    with tarfile.open(farm / "source.tar.gz", "w:gz") as archive:
        for path in sorted((ROOT / PACKAGE.name).rglob("*")):
            if path.is_file() and path.suffix in {".py", ".cc", ".h", ".xml", ".sh"}:
                archive.add(path, arcname=str(path.relative_to(ROOT)))
        for name in ["scripts/activate.sh", "scripts/run_job.py"]:
            archive.add(ROOT / name, arcname=name)
        archive.add(ROOT / "egm/cmssw.py", arcname="scripts/runtime_checks.py")
        if replay and bundled_replay == Path("scripts/custom_replay_cfg.py"):
            archive.add(replay, arcname=str(bundled_replay))
    for name in ["worker.py", "worker.sh"]:
        shutil.copy2(ROOT / "scripts" / name, farm / name)
    (farm / "worker.sh").chmod(0o755)
    count = cfg["production"]["files_per_job"]
    scripts = []
    for name, files in file_lists.items():
        for start in range(0, len(files), count):
            job_id = f"{name}_{start // count:05d}"
            script = f"jobs/{job_id}.sh"
            (farm / script).write_text(job_script(job_id))
            (farm / script).chmod(0o755)
            scripts.append(script)
    snapshot = {name: file_digest(farm / name) for name in ["source.tar.gz", "worker.py", "worker.sh", *scripts]}
    fingerprint = digest(dict(config=cfg, snapshot=snapshot))
    jobs = []
    for name, sample in samples.items():
        for start in range(0, len(file_lists[name]), count):
            job_id = f"{name}_{start // count:05d}"
            job = dict(id=job_id, sample=name, sample_config=sample, fingerprint=fingerprint,
                       bundle_sha256=snapshot["source.tar.gz"], cmssw=cfg["cmssw"], ntuplizer=cfg["ntuplizer"],
                       production=cfg["production"], files=file_lists[name][start:start + count],
                       output_url=f"{cfg['storage']['eos'].rstrip('/')}/{cfg['campaign']}/{name}/{job_id}.root")
            write_json(farm / "jobs" / f"{job_id}.json", job)
            jobs.append(job)
    manifest = dict(config=cfg, fingerprint=fingerprint, snapshot=snapshot, jobs=jobs)
    write_json(farm / "manifest.json", manifest)
    write_submit(farm, cfg, jobs)
    print(f"Prepared {len(jobs)} jobs in {farm}; run jobs/<job>.sh --local before submission")
    return manifest


def write_submit(farm, cfg, jobs):
    condor = cfg["condor"]
    proxy = condor.get("proxy", "")
    if not proxy or "${" in proxy:
        proxy = "$ENV(X509_USER_PROXY)"
    # Reject characters which could inject additional ClassAd statements.
    values = [str(farm), proxy, condor["flavour"], condor["requirements"]]
    if any("\n" in value or "\r" in value for value in values) or any('"' in value for value in values[:3]):
        raise ValueError("Invalid Condor value")
    content = f'''universe = vanilla
executable = {farm}/jobs/$(job).sh
initialdir = {farm}
should_transfer_files = YES
when_to_transfer_output = ON_EXIT
transfer_input_files = {farm}/source.tar.gz,{farm}/worker.sh,{farm}/worker.py,{farm}/jobs/$(job).json
transfer_output_files = ""
output = {farm}/logs/$(job).out
error = {farm}/logs/$(job).err
log = {farm}/logs/cluster.log
use_x509userproxy = True
x509userproxy = {proxy}
request_cpus = {condor['cpus']}
request_memory = {condor['memory_mb']}MB
request_disk = {condor['disk_mb']}MB
requirements = {condor['requirements']}
+JobFlavour = "{condor['flavour']}"
on_exit_hold = (ExitBySignal == True) || (ExitCode != 0)
queue job from (
'''
    content += "\n".join(job["id"] for job in jobs) + "\n)\n"
    (farm / "jobs.sub").write_text(content)


def read_farm(farm):
    farm = Path(farm).resolve()
    manifest = json.loads((farm / "manifest.json").read_text())
    if manifest["fingerprint"] != digest(dict(config=manifest["config"], snapshot=manifest["snapshot"])):
        raise ValueError("Frozen manifest changed; prepare a new farm")
    for name, expected in manifest["snapshot"].items():
        if file_digest(farm / name) != expected:
            raise ValueError(f"Frozen farm file changed: {name}; prepare a new farm")
    for job in manifest["jobs"]:
        if json.loads((farm / "jobs" / (job["id"] + ".json")).read_text()) != job:
            raise ValueError(f"Frozen job changed: {job['id']}")
    return farm, manifest


def check_farm_runtime(farm, manifest):
    config = manifest["config"]["cmssw"]
    if config["runtime"] == "prebuilt":
        # Compare against the farm's saved source, not a later working-tree edit.
        import tempfile
        with tempfile.TemporaryDirectory(prefix="egm-source-check-") as temporary:
            package = Path(temporary)
            with tarfile.open(farm / "source.tar.gz") as archive:
                prefix = PACKAGE.name + "/"
                for member in archive.getmembers():
                    if member.isfile() and member.name.startswith(prefix):
                        target = package / member.name[len(prefix):]
                        if not target.resolve().is_relative_to(package.resolve()):
                            raise ValueError("Invalid package path in farm archive")
                        target.parent.mkdir(parents=True, exist_ok=True)
                        target.write_bytes(archive.extractfile(member).read())
            check_prebuilt(config, package, config["prebuilt_snapshot"])


def local_test(farm, sample=None):
    farm, manifest = read_farm(farm)
    check_farm_runtime(farm, manifest)
    selected = {}
    for job in manifest["jobs"]:
        if sample is None or job["sample"] == sample:
            selected.setdefault(job["sample"], job)
    if not selected:
        raise ValueError(f"No jobs for sample: {sample}")
    for job in selected.values():
        subprocess.run(["/bin/bash", str(farm / "jobs" / (job["id"] + ".sh")), "--local"], cwd=farm, check=True)


def submit(farm, dry_run=False):
    farm, manifest = read_farm(farm)
    check_farm_runtime(farm, manifest)
    passed = set()
    for path in (farm / "jobs").glob("*.local-test.json"):
        report = json.loads(path.read_text())
        if report.get("fingerprint") == manifest["fingerprint"] and report.get("local_test") and report.get("events", 0) > 0 and report.get("candidates", 0) > 0:
            passed.add(report["sample"])
    missing = {job["sample"] for job in manifest["jobs"]} - passed
    if missing:
        raise ValueError(f"Matching local tests required for: {', '.join(sorted(missing))}")
    # Re-render from the frozen manifest instead of trusting a manually changed submit file.
    write_submit(farm, manifest["config"], manifest["jobs"])
    if dry_run:
        print((farm / "jobs.sub").read_text())
        return
    subprocess.run(["voms-proxy-info", "--exists", "--valid", "1:00"], check=True)
    subprocess.run(["condor_submit", str(farm / "jobs.sub")], cwd=farm, check=True)
