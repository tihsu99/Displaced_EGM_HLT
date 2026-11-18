"""Standard-library worker: scratch -> CMSSW -> checked ROOT -> EOS -> receipt."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tarfile
import tempfile
import time
from urllib.parse import urlsplit
import uuid


def run(args, **kwargs):
    print("Running:", " ".join(map(str, args)), flush=True)
    return subprocess.run(list(map(str, args)), check=True, **kwargs)


def run_logged(args, log_path, stream=False, **kwargs):
    with open(log_path, "w", buffering=1) as log:
        if not stream:
            return run(args, stdout=log, stderr=subprocess.STDOUT, **kwargs)
        args = list(map(str, args))
        print("Running:", " ".join(args), flush=True)
        with subprocess.Popen(args, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                              text=True, errors="replace", bufsize=1, **kwargs) as process:
            for line in process.stdout:
                log.write(line)
                print(line, end="", flush=True)
            status = process.wait()
            if status:
                raise subprocess.CalledProcessError(status, args)


def sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as source:
        for block in iter(lambda: source.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def upload(source, url, attempts):
    parsed = urlsplit(url)
    endpoint = "root://" + parsed.netloc
    target = "/" + parsed.path.lstrip("/")
    partial = target + ".partial-" + uuid.uuid4().hex
    run(["xrdfs", endpoint, "mkdir", "-p", str(Path(target).parent)])
    if subprocess.run(["xrdfs", endpoint, "stat", target], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL).returncode == 0:
        raise RuntimeError(f"Refusing to overwrite {url}; inspect the old job or choose a new campaign")
    try:
        for attempt in range(attempts):
            try:
                run(["xrdcp", "--force", "--nopbar", "--cksum", "adler32", source, endpoint + "/" + partial])
                break
            except subprocess.CalledProcessError:
                if attempt + 1 == attempts:
                    raise
                time.sleep(2 * (attempt + 1))
        run(["xrdfs", endpoint, "mv", partial, target])
    except BaseException:
        subprocess.run(["xrdfs", endpoint, "rm", partial], check=False)
        raise


def parse_args(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("job", type=Path)
    parser.add_argument("bundle", type=Path)
    parser.add_argument("--local", action="store_true", help="Test the first input file without EOS uploads")
    parser.add_argument("--n", type=int, help="Positive event limit for --local; defaults to production.local_test_events")
    args = parser.parse_args(argv)
    if args.n is not None:
        if not args.local:
            parser.error("--n requires --local; production uses the frozen production.max_events")
        if args.n <= 0:
            parser.error("--n must be a positive event count")
    return args


def main():
    args = parse_args()
    job_path = args.job.resolve()
    bundle = args.bundle.resolve()
    local = args.local
    print("WORKER", Path(__file__).resolve(), "MODE", "local (live output)" if local else "condor", flush=True)
    job = json.loads(job_path.read_text())
    if sha256(bundle) != job["bundle_sha256"]:
        raise RuntimeError("Source snapshot changed")
    scratch = Path(tempfile.mkdtemp(prefix="egm-", dir=os.environ.get("_CONDOR_SCRATCH_DIR", tempfile.gettempdir())))
    print("SCRATCH", scratch, flush=True)
    # Keep failed/local jobs for inspection; successful production scratch is removed.
    with tarfile.open(bundle) as archive:
        for member in archive.getmembers():
            if member.issym() or member.islnk() or not (scratch / member.name).resolve().is_relative_to(scratch):
                raise ValueError("Unsafe source archive member")
        archive.extractall(scratch)
    shutil.copy2(job_path, scratch / "job.json")
    cmssw = job["cmssw"]
    sys.path.insert(0, str(scratch / "scripts"))
    from runtime_checks import PACKAGE, check_prebuilt
    if cmssw["runtime"] == "prebuilt":
        check_prebuilt(cmssw, scratch / PACKAGE.name, cmssw["prebuilt_snapshot"])
    files = job["files"]
    if local:
        files = files[:1]
    max_events = job["production"]["local_test_events"] if local else job["production"]["max_events"]
    if args.n is not None:
        max_events = args.n
    print(f"EVENT LIMIT {max_events}; INPUT FILES {len(files)}", flush=True)
    if job["production"]["stage_inputs"]:
        staged = []
        for index, source in enumerate(files):
            target = scratch / f"input-{index}.root"
            run(["xrdcp", "--nopbar", "--cksum", "adler32", source, target])
            staged.append("file:" + str(target))
        files = staged
    resolved = dict(job, input_files=files, max_events=max_events)
    (scratch / "resolved.json").write_text(json.dumps(resolved, indent=2))
    env = {k: os.environ[k] for k in ["HOME", "USER", "LOGNAME", "X509_USER_PROXY", "X509_CERT_DIR", "KRB5CCNAME"] if k in os.environ}
    env.update(PATH="/usr/bin:/bin", TMPDIR=str(scratch), XDG_CACHE_HOME=str(scratch / "cache"),
               PYTHONNOUSERSITE="1", PYTHONDONTWRITEBYTECODE="1", PYTHONUNBUFFERED="1")
    print("LOG", scratch / "worker.log", flush=True)
    try:
        run_logged(["/bin/bash", scratch / "scripts/activate.sh", cmssw["cmsset_default"], cmssw["scram_arch"],
                    cmssw["release"], cmssw["runtime"], cmssw.get("base") or "", cmssw["build_jobs"]],
                   scratch / "worker.log", stream=local, cwd=scratch, env=env)
    except subprocess.CalledProcessError:
        # Condor may remove scratch after failure; preserve the diagnostic tail in stderr.
        if not local:
            print("\n".join((scratch / "worker.log").read_text(errors="replace").splitlines()[-100:]), file=sys.stderr)
        raise
    if cmssw["runtime"] == "prebuilt":
        check_prebuilt(cmssw, scratch / PACKAGE.name, cmssw["prebuilt_snapshot"])
    summary = json.loads((scratch / "inspection.json").read_text())
    receipt = dict(job, **summary, local_test=local, max_events=max_events,
                   input_files=files, root_sha256=sha256(scratch / "ntuple.root"))
    (scratch / "receipt.json").write_text(json.dumps(receipt, indent=2) + "\n")
    if local:
        shutil.copy2(scratch / "receipt.json", job_path.parent / (job_path.stem + ".local-test.json"))
        print("LOCAL TEST PASSED; ROOT and logs:", scratch)
        return
    base = job["output_url"]
    attempts = job["production"]["stageout_attempts"]
    upload(scratch / "ntuple.root", base, attempts)
    with tarfile.open(scratch / "provenance.tar.gz", "w:gz") as archive:
        for name in ["worker.log", "resolved.json", "input_provenance.txt", "event_content.txt", "ntuple_config.py", "FrameworkJobReport.xml", "inspection.json", "Ntuplizer/test/replay_cfg.py", "Ntuplizer/python/replay_tools.py", "Ntuplizer/python/ntuple_tools.py", "scripts/custom_replay_cfg.py", "replay_base.py", "replay_config.py", "replay_metadata.json"]:
            path = scratch / name
            if path.exists():
                archive.add(path, arcname=name)
    upload(scratch / "provenance.tar.gz", base + ".provenance.tar.gz", attempts)
    # Receipt is the completion marker, published only after every required artifact.
    upload(scratch / "receipt.json", base + ".json", attempts)
    shutil.rmtree(scratch)
    print("COMPLETE", base, flush=True)


if __name__ == "__main__":
    main()
