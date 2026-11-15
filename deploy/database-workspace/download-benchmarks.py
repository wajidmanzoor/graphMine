"""Download the public PropGBench artifacts, preserving metadata and checksums.

Usage: python download-benchmarks.py /data/labdata/wajid/graphmine_data/datasets
Re-running resumes partial transfers and skips files with verified manifests.
"""

import argparse
import concurrent.futures
import hashlib
import json
import subprocess
import time
from pathlib import Path

SITE = "https://pgraphbenchweb.vercel.app"
DATASETS = {
    "yelp": ("yelp", "QRU9NL"),
    "movielens-32m": ("ml32m", "4EN5JS"),
    "movielens-genome": ("mlgenome", "Q3TTXR"),
    "amazon": ("amazon", "1SZMLY"),
    "stackoverflow": ("stackoverflow", "S3YWHH"),
    "ontime": ("ontime", "O2OKKB"),
}


def fetch(url, target, resume=False):
    command = [
        "curl", "-fL", "--silent", "--show-error", "--retry", "5", "--retry-all-errors",
        "--retry-delay", "3", "--connect-timeout", "30",
        "--speed-time", "120", "--speed-limit", "1024",
    ]
    if url.startswith("https://datasets.ldbcouncil.org/"):
        command += ["--http1.1"]
    if resume:
        command += ["-C", "-"]
    subprocess.run(command + [url, "-o", str(target)], check=True)


def write_json(path, value):
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(value, indent=2) + "\n")
    temporary.replace(path)


def transfer(job):
    path, url, expected, expected_size = job
    receipt = path.with_name(path.name + ".verified.json")
    if receipt.exists() and path.exists():
        old = json.loads(receipt.read_text())
        if old.get("size_bytes") == path.stat().st_size and old.get("source") == url:
            return {"file": str(path), "status": "verified"}
    partial = path.with_name(path.name + ".partial")
    try:
        if not expected_size or not partial.exists() or partial.stat().st_size != expected_size:
            fetch(url, partial, resume=partial.exists())
        digest = hashlib.md5()
        sha256 = hashlib.sha256()
        with partial.open("rb") as stream:
            while chunk := stream.read(8 * 1024 * 1024):
                digest.update(chunk)
                sha256.update(chunk)
        if expected and digest.hexdigest() != expected:
            raise ValueError("Published MD5 checksum does not match; partial file retained")
        if expected_size and partial.stat().st_size != expected_size:
            raise ValueError("Published file size does not match; partial file retained")
        partial.replace(path)
        write_json(receipt, {
            "source": url, "size_bytes": path.stat().st_size,
            "md5": digest.hexdigest(), "sha256": sha256.hexdigest(),
            "verified_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "published_checksum_verified": bool(expected),
        })
        print(f"VERIFIED {path} ({path.stat().st_size:,} bytes)", flush=True)
        return {"file": str(path), "status": "verified"}
    except Exception as error:
        print(f"FAILED {path}: {error}", flush=True)
        return {"file": str(path), "status": "failed", "error": str(error)}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("destination", type=Path)
    parser.add_argument("--workers", type=int, default=4)
    args = parser.parse_args()
    args.destination.mkdir(parents=True, exist_ok=True)
    jobs, inventory = [], {}
    for name, (page, code) in DATASETS.items():
        directory = args.destination / name
        directory.mkdir(exist_ok=True)
        source = f"{SITE}/datasets/{page}.html"
        try:
            fetch(source, directory / "source.html")
            metadata = directory / "dataverse-metadata.json"
            fetch(
                "https://dataverse.harvard.edu/api/datasets/:persistentId/"
                f"?persistentId=doi:10.7910/DVN/{code}", metadata,
            )
            version = json.loads(metadata.read_text())["data"]["latestVersion"]
            files = version["files"]
            inventory[name] = {"source": source, "doi": f"10.7910/DVN/{code}", "files": len(files)}
            raw = directory / "raw"
            raw.mkdir(exist_ok=True)
            for item in files:
                data = item["dataFile"]
                if item.get("restricted"):
                    inventory[name].setdefault("restricted", []).append(data["filename"])
                    continue
                filename = data.get("originalFileName") or data["filename"]
                if Path(filename).name != filename:
                    raise ValueError("Unexpected file path in download metadata")
                jobs.append((
                    raw / filename,
                    f"https://dataverse.harvard.edu/api/access/datafile/{data['id']}"
                    + ("?format=original" if data.get("originalFileName") else ""),
                    data.get("checksum", {}).get("value"),
                    data.get("originalFileSize") or data.get("filesize"),
                ))
        except Exception as error:
            inventory[name] = {"source": source, "status": "skipped", "error": str(error)}
            print(f"UNAVAILABLE {name}: {error}", flush=True)
    for name, page in [("fars", "fars"), ("ldbc-snb", "snb")]:
        directory = args.destination / name
        directory.mkdir(exist_ok=True)
        fetch(f"{SITE}/datasets/{page}.html", directory / "source.html")
    inventory["fars"] = {
        "source": f"{SITE}/datasets/fars.html",
        "status": "skipped",
        "reason": "The dataset page links to DVN/FARS_PLACEHOLDER; the index incorrectly repeats the OnTime DOI. User requested skipping unavailable links.",
    }
    ldbc = args.destination / "ldbc-snb"
    inventory["ldbc-snb"] = {"source": f"{SITE}/datasets/snb.html", "scale_factor": 100}
    jobs += [
        (ldbc / "bi-sf100-composite-projected-fk.tar.zst",
         "https://datasets.ldbcouncil.org/bi-pre-audit/bi-sf100-composite-projected-fk.tar.zst",
         None, 31420711315),
        (ldbc / "ldbc-snb-bi-parameters-sf1-to-sf30000.zip",
         "https://datasets.ldbcouncil.org/snb-bi/ldbc-snb-bi-parameters-sf1-to-sf30000.zip",
         None, None),
    ]
    write_json(args.destination / "benchmark-inventory.json", inventory)
    print(f"Downloading {len(jobs)} artifacts ({sum(j[3] or 0 for j in jobs):,} advertised bytes)", flush=True)
    results = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=args.workers) as pool:
        pending = [pool.submit(transfer, job) for job in sorted(jobs, key=lambda j: j[3] or 0, reverse=True)]
        for future in concurrent.futures.as_completed(pending):
            result = future.result()
            results.append(result)
            write_json(args.destination / "download-progress.json", results)
    print(f"Complete: {sum(r['status'] == 'verified' for r in results)}/{len(jobs)} verified", flush=True)
    return 1 if any(r["status"] != "verified" for r in results) else 0


if __name__ == "__main__":
    raise SystemExit(main())
