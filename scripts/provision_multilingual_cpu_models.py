#!/usr/bin/env python3
"""Explicit, hash-pinned OCR provisioning. Importing this module performs no I/O."""

import argparse
from contextlib import closing
import hashlib
from importlib import metadata
import json
import os
from pathlib import Path
import re
import shutil
import tempfile
from urllib.parse import urlsplit
from urllib.request import Request, urlopen


INVENTORY = Path(__file__).parent / "data/ocr_models_rapidocr_v3_9_2.json"
SCHEMA = "pdfexact.ocr-models.v1"
MAX_BYTES = 64 * 1024 * 1024


def file_hash(path):
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def check_file(path, expected):
    if path.is_symlink() or not path.is_file():
        raise ValueError(f"not a regular model: {path}")
    if file_hash(path) != expected:
        raise ValueError(f"sha256 mismatch: {path}")


def publish_new(source, target):
    # Hard-link publication is atomic and cannot replace an existing destination.
    os.link(source, target, follow_symlinks=False)
    descriptor = os.open(target.parent, os.O_RDONLY | os.O_DIRECTORY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def dictionary_evidence(value, classes):
    from rapidocr.ch_ppocr_rec.utils import CTCLabelDecode

    if not value or not value.splitlines():
        raise ValueError("missing ONNX character metadata")
    characters = value.splitlines()
    expected = len(CTCLabelDecode(character=list(characters)).character)
    if classes != expected:
        raise ValueError(f"dictionary/logit classes mismatch: {classes} != {expected}")
    return {"source": "onnx.metadata.character", "sha256": hashlib.sha256(value.encode("utf-8")).hexdigest(),
            "count": len(characters), "classes_count": expected}


def validate_cpu(path, model):
    import numpy as np
    import onnxruntime as ort

    options = ort.SessionOptions()
    options.intra_op_num_threads = 1
    options.inter_op_num_threads = 1
    options.enable_cpu_mem_arena = False
    session = ort.InferenceSession(str(path), sess_options=options, providers=["CPUExecutionProvider"])
    if session.get_providers() != ["CPUExecutionProvider"]:
        raise ValueError("CPU-only providers required")
    inputs = session.get_inputs()
    if len(inputs) != 1 or inputs[0].type != "tensor(float)" or len(inputs[0].shape) != 4:
        raise ValueError("unsupported OCR input contract")
    fallback = [1, 3, 64, 64] if model["task"] == "det" else [1, 3, 48, 320]
    shape = [dim if isinstance(dim, int) and dim > 0 else fallback[i] for i, dim in enumerate(inputs[0].shape)]
    outputs = session.run(None, {inputs[0].name: np.zeros(shape, dtype=np.float32)})
    if not outputs or any(not np.isfinite(output).all() for output in outputs):
        raise ValueError("invalid CPU outputs")
    evidence = {"providers": session.get_providers(), "input_shape": shape,
                "output_shapes": [list(output.shape) for output in outputs],
                "probe": "synthetic-zero-tensor; runtime-contract-only, not language accuracy",
                "onnxruntime": ort.__version__}
    if model["task"] == "rec":
        if outputs[0].ndim != 3:
            raise ValueError("recognition logits must have rank 3")
        evidence["dictionary"] = dictionary_evidence(session.get_modelmeta().custom_metadata_map.get("character", ""), outputs[0].shape[-1])
    return evidence


def fetch_url(url):
    if urlsplit(url).scheme != "https" or urlsplit(url).hostname != "www.modelscope.cn":
        raise ValueError("only pinned official HTTPS ModelScope URLs are allowed")
    return urlopen(Request(url, headers={"User-Agent": "pdfexact-model-provisioner/1"}), timeout=120)


def load_inventory(path=INVENTORY):
    inventory = json.loads(path.read_text(encoding="utf-8"))
    if inventory.get("schema") != "pdfexact.ocr-provisioning.v1":
        raise ValueError("unsupported provisioning inventory")
    models = []
    for entry in inventory["models"]:
        model = dict(entry)
        model["url"] = f'{inventory["base_url"]}{model["ocr_version"]}/{model["task"]}/{model["id"]}.onnx'
        for field in ("catalog_url", "license", "license_url", "coverage_url", "coverage_note"):
            model.setdefault(field, inventory[field])
        if model["ocr_version"] == "PP-OCRv6":
            model["coverage_url"] = inventory["v6_coverage_url"]
        models.append(model)
    return models


def _safe_models(models):
    seen = set()
    for model in models:
        key = model.get("id", "")
        if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]*", key) or key in seen:
            raise ValueError(f"invalid or duplicate model id: {key}")
        if not re.fullmatch(r"[a-f0-9]{64}", model.get("sha256", "")):
            raise ValueError(f"invalid sha256: {key}")
        seen.add(key)


def provision(root, models, *, reuse_dir=None, fetch=fetch_url, validate=validate_cpu, max_bytes=MAX_BYTES):
    models = [dict(model) for model in models]
    _safe_models(models)
    root = Path(root).absolute()
    base = root / "ocr/rapidocr"
    for path in (root, root / "ocr", base, base / "v3.9.2", base / "catalog.json"):
        if path.is_symlink():
            raise ValueError(f"symlink destination refused: {path}")
    catalog_path = base / "catalog.json"
    if catalog_path.exists():
        catalog = json.loads(catalog_path.read_text(encoding="utf-8"))
        if catalog.get("schema") != SCHEMA:
            raise ValueError("existing catalog schema conflict")
        by_id = {model["id"]: model for model in catalog["models"]}
        if len(by_id) != len(catalog["models"]) or set(by_id) != {model["id"] for model in models}:
            raise ValueError("existing catalog model IDs conflict; no overwrite")
        for model in models:
            existing = by_id[model["id"]]
            expected_path = f'v3.9.2/{model["id"]}.onnx'
            if existing["path"] != expected_path or existing["sha256"] != model["sha256"]:
                raise ValueError("existing catalog path/hash conflict; no overwrite")
            for field in ("task", "ocr_version", "model_type", "lang_type", "scripts", "languages"):
                if existing.get(field) != model.get(field):
                    raise ValueError(f"existing catalog {field} conflict; no overwrite")
            check_file(base / expected_path, model["sha256"])
            validate(base / expected_path, model)
        return catalog
    # Preflight all existing model paths before any network activity.
    for model in models:
        existing = base / "v3.9.2" / f'{model["id"]}.onnx'
        if existing.exists() or existing.is_symlink():
            check_file(existing, model["sha256"])
    base.mkdir(parents=True, exist_ok=True)
    records, pending = [], []
    with tempfile.TemporaryDirectory(prefix=".provision-", dir=base) as temporary:
        staging = Path(temporary)
        for model in models:
            name = f'{model["id"]}.onnx'
            destination = base / "v3.9.2" / name
            candidate = staging / name
            local = destination if destination.exists() else (Path(reuse_dir) / name if reuse_dir else None)
            if local is not None and local.exists():
                check_file(local, model["sha256"])
                shutil.copyfile(local, candidate)
                origin = {"method": "reused-hash-verified", "local_path": str(local)}
            else:
                print(f'download {model["id"]}', flush=True)
                with closing(fetch(model["url"])) as stream, candidate.open("xb") as output:
                    size = 0
                    while chunk := stream.read(1024 * 1024):
                        size += len(chunk)
                        if size > max_bytes:
                            raise ValueError(f"size limit exceeded: {name}")
                        output.write(chunk)
                    output.flush()
                    os.fsync(output.fileno())
                    origin = {"method": "download", "requested_url": model["url"],
                              "resolved_url": stream.geturl() if hasattr(stream, "geturl") else model["url"]}
            check_file(candidate, model["sha256"])
            evidence = validate(candidate, model)
            record = {**model, "engine": "onnxruntime", "path": f"v3.9.2/{name}",
                      "size_bytes": candidate.stat().st_size, "origin": origin,
                      "verified": True, "cpu": evidence}
            if "dictionary" in evidence:
                record["dictionary"] = evidence["dictionary"]
            records.append(record)
            pending.append((candidate, destination))
            print(f'verified {model["id"]}: {record["size_bytes"]} bytes', flush=True)
        catalog = {"schema": SCHEMA, "version": 1, "models": records,
                   "publication": "all hashes and CPU contracts verified before catalog; no overwrite"}
        manifest = staging / "catalog.json"
        with manifest.open("x", encoding="utf-8") as output:
            json.dump(catalog, output, ensure_ascii=True, indent=2)
            output.write("\n")
            output.flush()
            os.fsync(output.fileno())
        (base / "v3.9.2").mkdir(exist_ok=True)
        published = []
        try:
            for candidate, destination in pending:
                if destination.exists():
                    check_file(destination, file_hash(candidate))
                else:
                    publish_new(candidate, destination)
                    published.append(destination)
            publish_new(manifest, catalog_path)
        except BaseException:
            for path in reversed(published):
                path.unlink()
            raise
    return catalog


def qwen_local_inventory(root):
    directory = Path(root) / "semantic_corrector/qwen2_5_0_5b_ct2_int8"
    if not directory.is_dir():
        return {"status": "absent"}
    return {"status": "local-user-bundle", "weight_provenance": "unknown-no-conversion-manifest",
            "official_origin_verified": False, "path": str(directory),
            "candidate_upstream": "https://huggingface.co/Qwen/Qwen2.5-0.5B-Instruct/tree/7ae557604adf67be50417f59c2c2f167def9a775",
            "candidate_license": "Apache-2.0; not certification of local converted weights",
            "files": [{"name": path.name, "size_bytes": path.stat().st_size, "sha256": file_hash(path)}
                      for path in sorted(directory.iterdir()) if path.is_file() and not path.is_symlink()]}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model-root", type=Path, required=True)
    parser.add_argument("--apply", action="store_true", help="Download/copy, CPU-validate and publish new files")
    parser.add_argument("--proof", type=Path, help="New JSON proof file; never replaced")
    args = parser.parse_args(argv)
    models = load_inventory()
    if not args.apply:
        print(json.dumps({"dry_run": True, "models": models}, indent=2))
        return 0
    if args.proof and (args.proof.exists() or args.proof.is_symlink()):
        raise FileExistsError(args.proof)
    rapidocr = metadata.distribution("rapidocr")
    reuse = Path(rapidocr.locate_file("rapidocr/models"))
    catalog = provision(args.model_root, models, reuse_dir=reuse)
    proof = {"schema": "pdfexact.model-provisioning-proof.v1", "catalog": str(args.model_root / "ocr/rapidocr/catalog.json"),
             "catalog_sha256": file_hash(args.model_root / "ocr/rapidocr/catalog.json"),
             "ocr": catalog, "qwen_existing": qwen_local_inventory(args.model_root),
             "runtimes": {name: metadata.version(name) for name in ("rapidocr", "onnxruntime", "ctranslate2", "tokenizers")}}
    if args.proof:
        args.proof.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(prefix=".proof-", dir=args.proof.parent) as directory:
            path = Path(directory) / "proof.json"
            with path.open("x", encoding="utf-8") as output:
                json.dump(proof, output, indent=2, ensure_ascii=True)
                output.write("\n")
                output.flush()
                os.fsync(output.fileno())
            publish_new(path, args.proof)
    print(json.dumps({"catalog": proof["catalog"], "models": len(catalog["models"]),
                      "total_bytes": sum(model["size_bytes"] for model in catalog["models"]),
                      "proof": str(args.proof) if args.proof else None}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
