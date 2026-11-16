"""Standard-library worker: scratch -> CMSSW -> checked ROOT -> EOS -> receipt."""
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


def main():
    job_path = Path(sys.argv[1]).resolve()
    bundle = Path(sys.argv[2]).resolve()
    local = len(sys.argv) > 3 and sys.argv[3] == "--local"
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
    sys.path.insert(0, str(scratch / "cmssw"))
    from runtime_checks import PACKAGE, check_prebuilt
    if cmssw["runtime"] == "prebuilt":
        check_prebuilt(cmssw, scratch / "cmssw" / PACKAGE, cmssw["prebuilt_snapshot"])
    files = job["files"]
    if local:
        files = files[:1]
    if job["production"]["stage_inputs"]:
        staged = []
        for index, source in enumerate(files):
            target = scratch / f"input-{index}.root"
            run(["xrdcp", "--nopbar", "--cksum", "adler32", source, target])
            staged.append("file:" + str(target))
        files = staged
    resolved = dict(job, input_files=files, max_events=job["production"]["local_test_events"] if local else job["production"]["max_events"])
    (scratch / "resolved.json").write_text(json.dumps(resolved, indent=2))
    env = {k: os.environ[k] for k in ["HOME", "USER", "LOGNAME", "X509_USER_PROXY", "X509_CERT_DIR", "KRB5CCNAME"] if k in os.environ}
    env.update(PATH="/usr/bin:/bin", TMPDIR=str(scratch), XDG_CACHE_HOME=str(scratch / "cache"),
               PYTHONNOUSERSITE="1", PYTHONDONTWRITEBYTECODE="1")
    try:
        with open(scratch / "worker.log", "w") as log:
            run(["/bin/bash", scratch / "cmssw/activate.sh", cmssw["cmsset_default"], cmssw["scram_arch"],
                 cmssw["release"], cmssw["runtime"], cmssw.get("base") or "", cmssw["build_jobs"]],
                cwd=scratch, env=env, stdout=log, stderr=subprocess.STDOUT)
    except subprocess.CalledProcessError:
        # Condor may remove scratch after failure; preserve the diagnostic tail in stderr.
        print("\n".join((scratch / "worker.log").read_text(errors="replace").splitlines()[-100:]), file=sys.stderr)
        raise
    if cmssw["runtime"] == "prebuilt":
        check_prebuilt(cmssw, scratch / "cmssw" / PACKAGE, cmssw["prebuilt_snapshot"])
    summary = json.loads((scratch / "inspection.json").read_text())
    receipt = dict(job, **summary, local_test=local, root_sha256=sha256(scratch / "ntuple.root"))
    (scratch / "receipt.json").write_text(json.dumps(receipt, indent=2) + "\n")
    if local:
        shutil.copy2(scratch / "receipt.json", job_path.parent / (job_path.stem + ".local-test.json"))
        print("LOCAL TEST PASSED; ROOT and logs:", scratch)
        return
    base = job["output_url"]
    attempts = job["production"]["stageout_attempts"]
    upload(scratch / "ntuple.root", base, attempts)
    with tarfile.open(scratch / "provenance.tar.gz", "w:gz") as archive:
        for name in ["worker.log", "resolved.json", "input_provenance.txt", "event_content.txt", "ntuple_config.py", "FrameworkJobReport.xml", "ReplayJobReport.xml", "inspection.json", "cmssw/replay_cfg.py"]:
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
