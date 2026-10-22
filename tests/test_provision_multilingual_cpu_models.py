import hashlib
import importlib.util
import io
import json
from pathlib import Path

import pytest


SCRIPT = Path(__file__).resolve().parents[1] / "scripts/provision_multilingual_cpu_models.py"


@pytest.fixture
def provision():
    spec = importlib.util.spec_from_file_location("provision_cpu", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def item(payload=b"model"):
    return {
        "id": "sample", "task": "rec", "ocr_version": "PP-OCRv5",
        "model_type": "mobile", "lang_type": "cyrillic",
        "scripts": ["Cyrl"], "languages": ["ru"],
        "url": "https://www.modelscope.cn/models/RapidAI/RapidOCR/resolve/v3.9.2/sample.onnx",
        "sha256": hashlib.sha256(payload).hexdigest(),
    }


def fake_validator(path, model):
    return {"providers": ["CPUExecutionProvider"], "dictionary": {"source": "onnx.metadata.character"}}


def test_import_has_no_download_or_write(monkeypatch):
    import urllib.request

    def forbidden(*args, **kwargs):
        pytest.fail("import attempted network/filesystem side effect")

    monkeypatch.setattr(urllib.request, "urlopen", forbidden)
    monkeypatch.setattr(Path, "mkdir", forbidden)
    monkeypatch.setattr(Path, "write_text", forbidden)
    spec = importlib.util.spec_from_file_location("provision_import_only", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    assert callable(module.provision)


def test_hash_failure_never_publishes_catalog(provision, tmp_path):
    with pytest.raises(ValueError, match="sha256"):
        provision.provision(tmp_path, [item()], fetch=lambda url: io.BytesIO(b"corrupt"), validate=fake_validator)
    assert not (tmp_path / "ocr/rapidocr/catalog.json").exists()
    assert not list(tmp_path.rglob("*.onnx"))


def test_cpu_failure_never_publishes_models(provision, tmp_path):
    def reject(path, model):
        raise ValueError("missing character dictionary")
    with pytest.raises(ValueError, match="dictionary"):
        provision.provision(tmp_path, [item()], fetch=lambda url: io.BytesIO(b"model"), validate=reject)
    assert not list(tmp_path.rglob("*.onnx"))


def test_existing_conflict_is_not_overwritten(provision, tmp_path):
    existing = tmp_path / "ocr/rapidocr/v3.9.2/sample.onnx"
    existing.parent.mkdir(parents=True)
    existing.write_bytes(b"user model")
    with pytest.raises(ValueError, match="sha256"):
        provision.provision(tmp_path, [item()], fetch=lambda url: pytest.fail("network"), validate=fake_validator)
    assert existing.read_bytes() == b"user model"
    assert not (existing.parents[1] / "catalog.json").exists()


def test_publish_and_repeat_without_network_or_mutation(provision, tmp_path):
    model = item()
    original = json.dumps(model, sort_keys=True)
    catalog = provision.provision(tmp_path, [model], fetch=lambda url: io.BytesIO(b"model"), validate=fake_validator)
    path = tmp_path / "ocr/rapidocr/catalog.json"
    before = path.read_bytes()
    assert catalog["schema"] == "pdfexact.ocr-models.v1"
    assert catalog["models"][0]["path"] == "v3.9.2/sample.onnx"
    provision.provision(tmp_path, [model], fetch=lambda url: pytest.fail("network"), validate=fake_validator)
    assert path.read_bytes() == before
    assert json.dumps(model, sort_keys=True) == original


def test_atomic_create_refuses_existing_bytes(provision, tmp_path):
    source, target = tmp_path / "source", tmp_path / "target"
    source.write_bytes(b"new")
    target.write_bytes(b"existing")
    with pytest.raises(FileExistsError):
        provision.publish_new(source, target)
    assert target.read_bytes() == b"existing"


@pytest.mark.parametrize("bad_id", ["../escape", "a/b", "/absolute"])
def test_unsafe_id_rejected_before_network(provision, tmp_path, bad_id):
    model = item()
    model["id"] = bad_id
    with pytest.raises(ValueError, match="id"):
        provision.provision(tmp_path, [model], fetch=lambda url: pytest.fail("network"), validate=fake_validator)


def test_dictionary_hash_is_exact_and_classes_checked(provision):
    evidence = provision.dictionary_evidence("a\n\u0416\n", 4)
    assert evidence["count"] == 2
    assert evidence["sha256"] == hashlib.sha256("a\n\u0416\n".encode()).hexdigest()
    with pytest.raises(ValueError, match="classes"):
        provision.dictionary_evidence("a\n", 999)
    with pytest.raises(ValueError, match="character"):
        provision.dictionary_evidence("", 2)


def test_size_limit_does_not_publish(provision, tmp_path):
    with pytest.raises(ValueError, match="size"):
        provision.provision(tmp_path, [item()], fetch=lambda url: io.BytesIO(b"model"), validate=fake_validator, max_bytes=2)
    assert not list(tmp_path.rglob("*.onnx"))


def test_publication_failure_rolls_back_only_new_files(provision, tmp_path, monkeypatch):
    existing = tmp_path / "ocr/rapidocr/v3.9.2/existing.onnx"
    existing.parent.mkdir(parents=True)
    existing.write_bytes(b"model")
    previous = item()
    previous["id"] = "existing"
    original = provision.publish_new

    def reject_catalog(source, target):
        if target.name == "catalog.json":
            raise OSError("publication failure")
        original(source, target)

    monkeypatch.setattr(provision, "publish_new", reject_catalog)
    with pytest.raises(OSError, match="publication failure"):
        provision.provision(tmp_path, [previous, item()], fetch=lambda url: io.BytesIO(b"model"), validate=fake_validator)
    assert existing.read_bytes() == b"model"
    assert not (existing.parent / "sample.onnx").exists()
    assert not list(existing.parents[1].glob(".provision-*"))


def test_existing_catalog_conflict_preserves_every_byte(provision, tmp_path):
    provision.provision(tmp_path, [item()], fetch=lambda url: io.BytesIO(b"model"), validate=fake_validator)
    path = tmp_path / "ocr/rapidocr/catalog.json"
    before = path.read_bytes()
    changed = item()
    changed["languages"] = ["en"]
    with pytest.raises(ValueError, match="languages conflict"):
        provision.provision(tmp_path, [changed], fetch=lambda url: pytest.fail("network"), validate=fake_validator)
    assert path.read_bytes() == before
    assert (path.parent / "v3.9.2/sample.onnx").read_bytes() == b"model"


def test_local_reuse_is_hash_checked_and_left_unchanged(provision, tmp_path):
    reuse = tmp_path / "wheel"
    reuse.mkdir()
    path = reuse / "sample.onnx"
    path.write_bytes(b"model")
    catalog = provision.provision(tmp_path / "target", [item()], reuse_dir=reuse, fetch=lambda url: pytest.fail("network"), validate=fake_validator)
    assert catalog["models"][0]["origin"]["method"] == "reused-hash-verified"
    assert path.read_bytes() == b"model"


def test_symlink_destination_refused(provision, tmp_path):
    other = tmp_path / "existing"
    other.mkdir()
    root = tmp_path / "models"
    root.symlink_to(other, target_is_directory=True)
    with pytest.raises(ValueError, match="symlink"):
        provision.provision(root, [item()], fetch=lambda url: pytest.fail("network"), validate=fake_validator)
    assert list(other.iterdir()) == []


def test_duplicate_ids_refused_before_network(provision, tmp_path):
    with pytest.raises(ValueError, match="duplicate model id"):
        provision.provision(tmp_path, [item(), item()], fetch=lambda url: pytest.fail("network"), validate=fake_validator)


def test_dry_run_never_provisions(provision, tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(provision, "provision", lambda *args, **kwargs: pytest.fail("provision"))
    root = tmp_path / "not-created"
    assert provision.main(["--model-root", str(root)]) == 0
    assert json.loads(capsys.readouterr().out)["dry_run"] is True
    assert not root.exists()


def test_qwen_inventory_never_certifies_local_weight_origin(provision, tmp_path):
    directory = tmp_path / "semantic_corrector/qwen2_5_0_5b_ct2_int8"
    directory.mkdir(parents=True)
    path = directory / "model.bin"
    path.write_bytes(b"local converted model")
    evidence = provision.qwen_local_inventory(tmp_path)
    assert evidence["official_origin_verified"] is False
    assert evidence["weight_provenance"] == "unknown-no-conversion-manifest"
    assert evidence["files"][0]["sha256"] == hashlib.sha256(path.read_bytes()).hexdigest()


def test_inventory_is_pinned_and_contains_no_redundant_large_models(provision):
    models = provision.load_inventory()
    assert len(models) == 11
    assert len({model["id"] for model in models}) == 11
    assert {script for model in models for script in model["scripts"]} == {
        "Latn", "Hani", "Hira", "Kana", "Cyrl", "Hang", "Arab", "Deva", "Thai", "Grek", "Taml", "Telu",
    }
    assert all("/resolve/v3.9.2/onnx/" in model["url"] for model in models)
    assert all(model["license"] == "Apache-2.0" for model in models)
