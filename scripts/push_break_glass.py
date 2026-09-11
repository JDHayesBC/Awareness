#!/usr/bin/env python3
"""
push_break_glass.py — encrypt the newest break-glass zip and deliver it off-site to Cloudflare R2.

The off-site delivery leg of #157. Encryption scheme decided jointly by Lyra + Caia
(2026-09-11); design lives in work/perception-system/ (break-glass-as-a-sense) and the
Jeff-facing custody spec (Caia). Pipeline:

    newest awareness-recovery-*.zip
      -> age-encrypt to ALL pinned recipients (multi-recipient public-key)
      -> assert the ciphertext header carries exactly N recipient stanzas
      -> upload ciphertext to R2 (S3 API)
      -> download it back and sha256-compare (round-trip proof)
      -> keep-N rotation of the R2 objects
      -> write the last-success marker (.claude/data/break_glass_offsite.json)

WHY age MULTI-RECIPIENT PUBLIC-KEY:
  The NUC holds ONLY public keys, so this box can encrypt but can NEVER decrypt its own
  uploads. A stolen R2 token, a compromised NUC, or a misconfigured-public bucket all
  yield opaque ciphertext. Recovery decrypts with the standard `age` CLI:
      age -d -i <your-identity-file> awareness-recovery-YYYY-MM-DD.zip.age > out.zip
  Recipients are REQUIRED to be several and custodially diverse (e.g. Jeff-primary,
  Jeff-cold, Steve-primary, Steve-cold): for break-glass, RECOVERABILITY is the primary
  requirement, and key-loss — correlated with the very disasters this exists for — is the
  catastrophic mode age introduces. More recipients = more independent ways back in.

SECURITY LIMITS — stated plainly so nobody over-trusts this box:
  1. The recipient pin (config/break_glass_recipients.sha256) is tamper-EVIDENT, not
     tamper-PROOF. A root-compromised NUC could rewrite the recipients file AND its pin AND
     this check in one breath; git history catches that ONLY if a human looks. So Phase-1
     recipient integrity is DETECTIVE-tier. What makes detective-tier acceptable short-term
     is the human decrypt-drill (quarterly + on every pipeline/binary/recipient change).
     The PREVENTIVE guarantee is Phase-2: Jeff-signed recipients (a signature the NUC can't
     forge without his signing key). Not built yet.
  2. "The NUC can only encrypt" != "can only encrypt to the RIGHT people." A compromised
     NUC could swap in an attacker recipient; every downstream check (size, sha256, upload)
     still passes green. The header stanza-COUNT check below catches a missing/extra
     recipient, but age's format deliberately hides WHICH keys a file is encrypted to (each
     X25519 stanza carries a random ephemeral share, not the recipient's identity), so we
     canNOT read the recipient identities back out of the ciphertext. The recipient-identity
     guarantee therefore rests on the pinned file (detective-tier, per #1) + the drill.
  3. This box canNOT end-to-end decrypt-verify (no private key here, by design). The
     round-trip proves the R2 object is byte-identical to what we uploaded; it does NOT
     prove decryptability. That is the off-NUC verifier's job (Phase-2 / #317) plus the
     human drill.

The last-success marker feeds two consumers (one heartbeat, per Caia): Caia's #317 backup
verifier, and the crack-3 interoceptive "is the lifeboat reaching the harbor?" sense — which
goes LOUD when last_success_at is stale or recipient_file_sha256 drifts unexpectedly.
"""

from __future__ import annotations

import argparse
import datetime as _dt
import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_OUTPUT_DIR = Path("/mnt/c/Users/Jeff/awareness_backups/break_glass")  # matches create_break_glass.py
RECIPIENTS_FILE = PROJECT_ROOT / "config" / "break_glass_recipients.txt"
RECIPIENTS_PIN = PROJECT_ROOT / "config" / "break_glass_recipients.sha256"
ENV_FILE = PROJECT_ROOT / "pps" / "docker" / ".env"
MARKER_FILE = PROJECT_ROOT / ".claude" / "data" / "break_glass_offsite.json"
OBJECT_PREFIX = "break-glass/"
MARKER_SCHEMA_VERSION = 1
PIPELINE_VERSION = "1.0.0"
DEFAULT_KEEP = 4

_R2_KEYS = ("R2_ENDPOINT_URL", "R2_ACCESS_KEY_ID", "R2_SECRET_ACCESS_KEY", "R2_BUCKET")


# --------------------------------------------------------------------------- helpers


def log(msg: str, level: str = "INFO") -> None:
    ts = _dt.datetime.now().strftime("%H:%M:%S")
    print(f"[{ts}] [{level}] {msg}")


def die(msg: str) -> "None":
    log(msg, "CRITICAL")
    sys.exit(1)


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def resolve_age() -> str:
    """Locate the `age` binary, preferring ~/.local/bin (where we install it no-sudo)."""
    local = Path.home() / ".local" / "bin" / "age"
    if local.is_file() and os.access(local, os.X_OK):
        return str(local)
    found = shutil.which("age")
    if found:
        return found
    die("`age` binary not found (looked in ~/.local/bin and PATH). Install it first.")


def age_version(age_bin: str) -> str:
    try:
        out = subprocess.run([age_bin, "--version"], capture_output=True, text=True, timeout=10)
        return (out.stdout or out.stderr).strip() or "unknown"
    except Exception:  # pragma: no cover - defensive
        return "unknown"


def tmpfs_dir(prefix: str) -> Path:
    """A temp dir in RAM (/dev/shm) when available, so ciphertext never persists to disk."""
    shm = Path("/dev/shm")
    base = str(shm) if shm.is_dir() and os.access(shm, os.W_OK) else None
    return Path(tempfile.mkdtemp(prefix=prefix, dir=base))


# --------------------------------------------------------------------------- config


def load_recipients(*, allow_missing_pin: bool = False) -> tuple[list[str], list[str], str]:
    """Return (recipients, fingerprints, recipient_file_sha256). Fail-closed.

    A recipient is any non-blank, non-comment line that looks like an age recipient
    (`age1...`) or an ssh public key (`ssh-ed25519`/`ssh-rsa`, which age accepts).
    """
    if not RECIPIENTS_FILE.is_file():
        die(f"recipients file missing: {RECIPIENTS_FILE}\n"
            f"        Populate it with the pinned public keys (see the custody spec), then "
            f"run `push_break_glass.py --update-pin`.")
    raw = RECIPIENTS_FILE.read_bytes()
    file_sha = hashlib.sha256(raw).hexdigest()

    recipients: list[str] = []
    for line in raw.decode("utf-8", "replace").splitlines():
        s = line.strip()
        if not s or s.startswith("#"):
            continue
        if s.startswith("age1") or s.startswith("ssh-ed25519") or s.startswith("ssh-rsa"):
            recipients.append(s)
        else:
            die(f"recipients file has a non-recipient line: {s[:40]!r}")

    if not recipients:
        die("recipients file has NO recipients — refusing to run (fail-closed: never upload "
            "unencrypted or to zero recipients).")

    # Pin check (tamper-EVIDENT — see module docstring §1).
    if RECIPIENTS_PIN.is_file():
        pinned = RECIPIENTS_PIN.read_text().split()[0].strip()
        if pinned != file_sha:
            die(f"recipients pin MISMATCH.\n"
                f"        expected (pinned): {pinned}\n"
                f"        actual   (file)  : {file_sha}\n"
                f"        If you legitimately changed the recipients, re-run with --update-pin "
                f"and commit both files. Otherwise this is tampering — STOP and investigate.")
    elif not allow_missing_pin:
        die(f"recipients pin missing: {RECIPIENTS_PIN}\n"
            f"        Run `push_break_glass.py --update-pin` to create it (then commit it).")

    fingerprints = [hashlib.sha256(r.encode()).hexdigest()[:16] for r in recipients]
    return recipients, fingerprints, file_sha


def load_r2_env() -> dict[str, str]:
    """Parse R2_* keys out of pps/docker/.env. Fail-closed if any are missing/blank."""
    if not ENV_FILE.is_file():
        die(f"env file missing: {ENV_FILE} (needs R2_* keys — see the setup steps).")
    env: dict[str, str] = {}
    for line in ENV_FILE.read_text().splitlines():
        s = line.strip()
        if not s or s.startswith("#") or "=" not in s:
            continue
        k, v = s.split("=", 1)
        k = k.strip()
        if k in _R2_KEYS:
            env[k] = v.strip().strip('"').strip("'")
    missing = [k for k in _R2_KEYS if not env.get(k)]
    if missing:
        die(f"missing R2 config in {ENV_FILE}: {', '.join(missing)}")
    return env


# --------------------------------------------------------------------------- crypto


def encrypt_to_recipients(age_bin: str, src_zip: Path, recipients: list[str], out_path: Path) -> None:
    cmd = [age_bin]
    for r in recipients:
        cmd += ["-r", r]
    cmd += ["-o", str(out_path), str(src_zip)]
    res = subprocess.run(cmd, capture_output=True, text=True)
    if res.returncode != 0:
        die(f"age encryption failed (rc={res.returncode}): {res.stderr.strip()}")
    if not out_path.is_file() or out_path.stat().st_size == 0:
        die("age produced no/empty ciphertext despite exit 0 — refusing to upload.")


def assert_header_recipient_count(cipher_path: Path, expected: int) -> None:
    """Validate the age v1 header and assert exactly `expected` recipient stanzas.

    Catches truncated headers and missing/extra recipients. Does NOT (cannot) verify WHICH
    recipients — age hides that by design (see module docstring §2).
    """
    with open(cipher_path, "rb") as fh:
        head = fh.read(65536)
    # Header is ASCII text up to the "--- <mac>" line; payload is binary after it.
    marker = head.find(b"\n--- ")
    if marker == -1:
        die("age header has no '--- <mac>' terminator within 64KB — corrupt/truncated ciphertext.")
    header_lines = head[:marker].decode("ascii", "replace").splitlines()
    if not header_lines or header_lines[0] != "age-encryption.org/v1":
        die(f"ciphertext is not age v1 (first line: {header_lines[:1]!r}).")
    stanzas = sum(1 for ln in header_lines if ln.startswith("-> "))
    if stanzas != expected:
        die(f"header recipient-stanza count {stanzas} != expected {expected} "
            f"(missing/extra recipient — refusing to upload).")


# --------------------------------------------------------------------------- R2


def r2_client(env: dict[str, str]):
    try:
        import boto3
        from botocore.config import Config
    except ImportError:
        die("boto3 not installed in this interpreter (pps/venv/bin/pip install boto3).")
    return boto3.client(
        "s3",
        endpoint_url=env["R2_ENDPOINT_URL"],
        aws_access_key_id=env["R2_ACCESS_KEY_ID"],
        aws_secret_access_key=env["R2_SECRET_ACCESS_KEY"],
        config=Config(signature_version="s3v4", region_name="auto", retries={"max_attempts": 5, "mode": "standard"}),
    )


def upload(client, bucket: str, cipher_path: Path, object_key: str) -> None:
    client.upload_file(str(cipher_path), bucket, object_key)


def verify_roundtrip(client, bucket: str, object_key: str, expected_sha: str, workdir: Path) -> int:
    """Download the object back and sha256-compare. Returns the object size in bytes."""
    head = client.head_object(Bucket=bucket, Key=object_key)
    size = int(head["ContentLength"])
    dl = workdir / "roundtrip.age"
    client.download_file(bucket, object_key, str(dl))
    got = sha256_file(dl)
    dl.unlink(missing_ok=True)
    if got != expected_sha:
        die(f"ROUND-TRIP MISMATCH for {object_key}: uploaded {expected_sha}, R2 returned {got}. "
            f"The stored object is NOT what we sent — do not trust this backup.")
    return size


def rotate(client, bucket: str, keep_n: int) -> list[str]:
    """Keep the newest `keep_n` *.age objects under OBJECT_PREFIX; delete the rest."""
    paginator = client.get_paginator("list_objects_v2")
    objs: list[str] = []
    for page in paginator.paginate(Bucket=bucket, Prefix=OBJECT_PREFIX):
        for item in page.get("Contents", []):
            k = item["Key"]
            if k.endswith(".age"):
                objs.append(k)

    def date_key(k: str):
        # break-glass/awareness-recovery-2026-09-11.zip.age -> 2026-09-11
        stem = k.rsplit("/", 1)[-1]
        parts = stem.split("-")
        for i in range(len(parts) - 2):
            candidate = "-".join(parts[i:i + 3]).split(".")[0]
            try:
                return _dt.datetime.strptime(candidate, "%Y-%m-%d")
            except ValueError:
                continue
        return _dt.datetime.min

    objs.sort(key=date_key, reverse=True)
    deleted = []
    for k in objs[keep_n:]:
        client.delete_object(Bucket=bucket, Key=k)
        deleted.append(k)
    return deleted


# --------------------------------------------------------------------------- marker


def write_marker(data: dict) -> None:
    MARKER_FILE.parent.mkdir(parents=True, exist_ok=True)
    tmp = MARKER_FILE.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(data, indent=2) + "\n")
    tmp.replace(MARKER_FILE)


# --------------------------------------------------------------------------- zip discovery


def newest_zip(backups_dir: Path) -> Path:
    if not backups_dir.is_dir():
        die(f"backups dir not found: {backups_dir}")
    candidates = list(backups_dir.glob("*-recovery-*.zip"))
    if not candidates:
        die(f"no *-recovery-*.zip found in {backups_dir} — run create_break_glass.py first.")
    candidates.sort(key=lambda p: p.stat().st_mtime, reverse=True)
    return candidates[0]


# --------------------------------------------------------------------------- commands


def cmd_run(args) -> int:
    age_bin = resolve_age()
    recipients, fingerprints, recip_sha = load_recipients()
    zip_path = newest_zip(Path(args.dir))
    log(f"newest zip: {zip_path.name} ({zip_path.stat().st_size / 1e6:.1f} MB)")
    log(f"recipients: {len(recipients)} pinned (fp: {', '.join(fingerprints)})")

    work = tmpfs_dir("bg-push-")
    try:
        cipher = work / (zip_path.name + ".age")
        log("encrypting to all recipients ...")
        encrypt_to_recipients(age_bin, zip_path, recipients, cipher)
        assert_header_recipient_count(cipher, len(recipients))
        zip_sha = sha256_file(zip_path)
        cipher_sha = sha256_file(cipher)
        object_key = f"{OBJECT_PREFIX}{zip_path.name}.age"
        log(f"ciphertext: {cipher.stat().st_size / 1e6:.1f} MB, header OK ({len(recipients)} stanzas)")

        if args.dry_run:
            log("DRY RUN — skipping upload/verify/rotate/marker.")
            log(f"would upload -> s3://{{bucket}}/{object_key}")
            log(f"  zip_sha256={zip_sha}\n            cipher_sha256={cipher_sha}")
            return 0

        env = load_r2_env()
        client = r2_client(env)
        bucket = env["R2_BUCKET"]

        log(f"uploading -> {bucket}/{object_key}")
        upload(client, bucket, cipher, object_key)
        size = verify_roundtrip(client, bucket, object_key, cipher_sha, work)
        log(f"round-trip verified ({size / 1e6:.1f} MB, sha256 matches).")

        deleted = rotate(client, bucket, args.keep)
        if deleted:
            log(f"rotated (deleted {len(deleted)}): {', '.join(d.rsplit('/', 1)[-1] for d in deleted)}")

        marker = {
            "version": MARKER_SCHEMA_VERSION,
            "last_success_at": _dt.datetime.now(_dt.timezone.utc).isoformat(),
            "object_key": object_key,
            "size_bytes": size,
            "age_ciphertext_sha256": cipher_sha,
            "zip_sha256": zip_sha,
            "recipient_fingerprints": fingerprints,
            "recipient_file_sha256": recip_sha,
            "pipeline_version": PIPELINE_VERSION,
            "age_version": age_version(age_bin),
        }
        write_marker(marker)
        log(f"marker written: {MARKER_FILE}")
        log("OFF-SITE DELIVERY COMPLETE.")
        return 0
    finally:
        shutil.rmtree(work, ignore_errors=True)


def cmd_update_pin(args) -> int:
    recipients, fingerprints, recip_sha = load_recipients(allow_missing_pin=True)
    RECIPIENTS_PIN.write_text(recip_sha + "  break_glass_recipients.txt\n")
    log(f"pinned {len(recipients)} recipients -> {RECIPIENTS_PIN}")
    log(f"sha256={recip_sha}")
    log("Commit BOTH config/break_glass_recipients.txt and its .sha256.")
    return 0


def cmd_self_test(args) -> int:
    """Validate the crypto plumbing end-to-end with an EPHEMERAL keypair (no R2, no real keys)."""
    age_bin = resolve_age()
    keygen = str(Path(age_bin).with_name("age-keygen"))
    if not Path(keygen).is_file():
        keygen = shutil.which("age-keygen") or die("age-keygen not found for self-test.")
    work = tmpfs_dir("bg-selftest-")
    try:
        # 1. ephemeral identity + its public key
        idfile = work / "id.txt"
        kg = subprocess.run([keygen, "-o", str(idfile)], capture_output=True, text=True)
        if kg.returncode != 0:
            die(f"age-keygen failed: {kg.stderr.strip()}")
        pub = next((ln.split(":", 1)[1].strip() for ln in (idfile.read_text().splitlines())
                    if ln.lower().startswith("# public key:")), None)
        if not pub:
            die("could not read public key from age-keygen output.")
        # 2. encrypt a payload to it, assert header, decrypt, compare
        payload = work / "payload.bin"
        payload.write_bytes(b"break-glass self-test payload \x00\x01\x02" * 4096)
        cipher = work / "payload.age"
        encrypt_to_recipients(age_bin, payload, [pub], cipher)
        assert_header_recipient_count(cipher, 1)
        dec = subprocess.run([age_bin, "-d", "-i", str(idfile), "-o", str(work / "out.bin"), str(cipher)],
                             capture_output=True, text=True)
        if dec.returncode != 0:
            die(f"decrypt failed: {dec.stderr.strip()}")
        if sha256_file(payload) != sha256_file(work / "out.bin"):
            die("SELF-TEST FAILED: round-trip payload mismatch.")
        # 3. multi-recipient header count
        kg2 = subprocess.run([keygen, "-o", str(work / "id2.txt")], capture_output=True, text=True)
        pub2 = next((ln.split(":", 1)[1].strip() for ln in (work / "id2.txt").read_text().splitlines()
                     if ln.lower().startswith("# public key:")), None)
        cipher2 = work / "multi.age"
        encrypt_to_recipients(age_bin, payload, [pub, pub2], cipher2)
        assert_header_recipient_count(cipher2, 2)
        log(f"SELF-TEST PASSED — age {age_version(age_bin)}: encrypt/header-count/decrypt round-trip OK "
            f"(1 and 2 recipients).")
        return 0
    finally:
        shutil.rmtree(work, ignore_errors=True)


def cmd_test_r2(args) -> int:
    """Confirm creds/bucket/permissions with a tiny put/get/delete round-trip (no real data)."""
    env = load_r2_env()
    client = r2_client(env)
    try:
        buckets = [b["Name"] for b in client.list_buckets().get("Buckets", [])]
    except Exception as e:  # noqa: BLE001
        die(f"list_buckets failed — bad creds/endpoint? {e}")
    log(f"reachable buckets: {buckets}")
    bucket = env["R2_BUCKET"]
    if bucket not in buckets:
        die(f"configured R2_BUCKET={bucket!r} is not among {buckets}. Fix R2_BUCKET in the env.")
    key = f"{OBJECT_PREFIX}.connectivity-test"
    client.put_object(Bucket=bucket, Key=key, Body=b"ok")
    got = client.get_object(Bucket=bucket, Key=key)["Body"].read()
    client.delete_object(Bucket=bucket, Key=key)
    if got != b"ok":
        die("R2 put/get mismatch — connectivity broken.")
    log(f"R2 connectivity OK: put/get/delete round-trip on {bucket} succeeded (write+read+delete perms confirmed).")
    return 0


def main() -> int:
    p = argparse.ArgumentParser(description="Encrypt + deliver the newest break-glass zip off-site to R2.")
    p.add_argument("--dir", default=str(DEFAULT_OUTPUT_DIR), help=f"break-glass zip dir (default: {DEFAULT_OUTPUT_DIR})")
    p.add_argument("--keep", type=int, default=DEFAULT_KEEP, help=f"R2 objects to retain (default: {DEFAULT_KEEP})")
    p.add_argument("--dry-run", action="store_true", help="encrypt + header-check only; no upload/rotate/marker")
    p.add_argument("--update-pin", action="store_true", help="recompute config/break_glass_recipients.sha256 and exit")
    p.add_argument("--self-test", action="store_true", help="validate crypto plumbing with an ephemeral key; no R2")
    p.add_argument("--test-r2", action="store_true", help="confirm R2 creds/bucket with a tiny put/get/delete")
    args = p.parse_args()

    if args.self_test:
        return cmd_self_test(args)
    if args.test_r2:
        return cmd_test_r2(args)
    if args.update_pin:
        return cmd_update_pin(args)
    return cmd_run(args)


if __name__ == "__main__":
    sys.exit(main())
