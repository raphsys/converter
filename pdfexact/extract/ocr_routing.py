"""Local CPU OCR, shared detection and explicit, uncalibrated script routing.

All recognizers see the same crops. An automatic choice is only a best-effort
observation: raw alternatives and uncertainty survive in acquisition evidence.
"""
from __future__ import annotations

import copy
from dataclasses import dataclass
from functools import lru_cache
from hashlib import sha256
import json
from pathlib import Path
from threading import RLock
import time
import unicodedata

from pdfexact.model_paths import resolve_ai_models_root


_SCRIPT_RANGES = (
    ("Cyrl", ((0x0400, 0x052F), (0x2DE0, 0x2DFF), (0xA640, 0xA69F))),
    ("Hani", ((0x3400, 0x4DBF), (0x4E00, 0x9FFF), (0xF900, 0xFAFF), (0x20000, 0x323AF))),
    ("Hira", ((0x3040, 0x309F),)),
    ("Kana", ((0x30A0, 0x30FF), (0x31F0, 0x31FF), (0xFF66, 0xFF9D))),
    ("Hang", ((0x1100, 0x11FF), (0x3130, 0x318F), (0xA960, 0xA97F), (0xAC00, 0xD7AF))),
    ("Arab", ((0x0600, 0x06FF), (0x0750, 0x077F), (0x08A0, 0x08FF), (0xFB50, 0xFDFF), (0xFE70, 0xFEFF))),
    ("Deva", ((0x0900, 0x097F), (0xA8E0, 0xA8FF))),
    ("Thai", ((0x0E00, 0x0E7F),)),
    ("Grek", ((0x0370, 0x03FF), (0x1F00, 0x1FFF))),
    ("Taml", ((0x0B80, 0x0BFF),)),
    ("Telu", ((0x0C00, 0x0C7F),)),
)
_ALIASES = {
    "ru": "cyrillic", "rus": "cyrillic", "cyrl": "cyrillic", "uk": "cyrillic",
    "ko": "korean", "kor": "korean", "hang": "korean",
    "zh": "ch", "zh-cn": "ch", "chi-sim": "ch", "chi_sim": "ch", "zh-hans": "ch",
    "zh-tw": "chinese_cht", "zh-hant": "chinese_cht", "chi-tra": "chinese_cht",
    "chinese-cht": "chinese_cht",
    "ja": "japan", "jp": "japan", "jpn": "japan",
    "en": "ch", "eng": "ch", "fr": "ch", "fra": "ch", "latin": "ch", "latn": "ch",
    "ar": "arabic", "ara": "arabic", "arab": "arabic", "fa": "arabic", "ur": "arabic",
    "hi": "devanagari", "hin": "devanagari", "deva": "devanagari",
    "th": "th", "tha": "th", "thai": "th", "el": "el", "ell": "el", "grek": "el",
    "ta": "ta", "tam": "ta", "taml": "ta", "te": "te", "tel": "te", "telu": "te",
}
_LANG_SCRIPTS = {
    "ch": {"Latn", "Hani", "Hira", "Kana"}, "chinese_cht": {"Hani"}, "japan": {"Hira", "Kana", "Hani"},
    "cyrillic": {"Cyrl"}, "korean": {"Hang"}, "arabic": {"Arab"}, "devanagari": {"Deva"},
    "th": {"Thai"}, "el": {"Grek"}, "ta": {"Taml"}, "te": {"Telu"},
}


def script_counts(text: str) -> dict[str, int]:
    counts: dict[str, int] = {}
    for character in text:
        if not character.isalpha():
            continue
        script = next((name for name, ranges in _SCRIPT_RANGES
                       if any(lo <= ord(character) <= hi for lo, hi in ranges)), None)
        if script is None:
            script = "Latn" if "LATIN" in unicodedata.name(character, "") else "Other"
        counts[script] = counts.get(script, 0) + 1
    return counts


def has_non_latin_letters(text: str) -> bool:
    return any(name != "Latn" for name in script_counts(text))


@dataclass(frozen=True)
class LocalOcrModel:
    id: str
    task: str
    path: Path
    sha256: str
    ocr_version: str
    model_type: str
    lang_type: str
    scripts: tuple[str, ...] = ()
    languages: tuple[str, ...] = ()
    dictionary: dict | None = None


def load_catalog(model_root=None) -> tuple[LocalOcrModel, ...]:
    root = resolve_ai_models_root(model_root)
    catalog = root / "ocr" / "rapidocr" / "catalog.json"
    if not catalog.is_file():
        # Existing bundled RapidOCR models are local, not a download fallback.
        import rapidocr
        directory = Path(rapidocr.__file__).parent / "models"
        models = []
        for stem, task, version, kind in (
            ("PP-OCRv6_det_small", "det", "PP-OCRv6", "small"),
            ("PP-OCRv6_rec_small", "rec", "PP-OCRv6", "small"),
            ("ch_ppocr_mobile_v2.0_cls_mobile", "cls", "PP-OCRv4", "mobile"),
        ):
            path = directory / f"{stem}.onnx"
            if not path.is_file():
                raise FileNotFoundError(f"Local OCR catalog/model absent: {catalog}; {path}")
            models.append(LocalOcrModel(stem, task, path, sha256(path.read_bytes()).hexdigest(),
                                        version, kind, "ch", tuple(_LANG_SCRIPTS["ch"]) if task == "rec" else ()))
        return tuple(models)
    data = json.loads(catalog.read_text(encoding="utf-8"))
    if data.get("schema") != "pdfexact.ocr-models.v1" or not isinstance(data.get("models"), list):
        raise ValueError(f"Invalid OCR catalog schema: {catalog}")
    models = []
    for entry in data["models"]:
        path = (catalog.parent / entry["path"]).resolve()
        if not path.is_relative_to(catalog.parent.resolve()):
            raise ValueError(f"OCR catalog path escapes its root: {entry['path']}")
        if entry.get("engine") != "onnxruntime" or entry.get("task") not in {"rec", "det", "cls"}:
            raise ValueError(f"Unsupported OCR engine/task: {entry['id']}")
        if not path.is_file() or sha256(path.read_bytes()).hexdigest() != entry["sha256"]:
            raise ValueError(f"OCR model missing or SHA256 mismatch: {path}")
        models.append(LocalOcrModel(entry["id"], entry["task"], path, entry["sha256"],
                                    entry["ocr_version"], entry["model_type"], entry["lang_type"],
                                    tuple(entry.get("scripts", ())), tuple(entry.get("languages", ())),
                                    entry.get("dictionary")))
    if len({model.id for model in models}) != len(models):
        raise ValueError("Duplicate OCR catalog model IDs")
    for task in ("det", "cls", "rec"):
        if not any(model.task == task for model in models):
            raise ValueError(f"OCR catalog missing task: {task}")
    return tuple(models)


def validate_alphabet(model, metadata, output_classes=None) -> tuple[str, ...]:
    value = metadata.get("character")
    if not isinstance(value, str) or not value:
        raise ValueError(f"OCR embedded character dictionary absent: {model.id}; no generic fallback allowed")
    characters = tuple(value.splitlines())
    # Repeated labels are legal in upstream alphabets (notably Arabic). Their
    # positions are CTC classes: deduplicating them would change the decoder.
    if not characters or any(not character for character in characters):
        raise ValueError(f"OCR empty dictionary entries: {model.id}")
    audit = model.dictionary or {}
    if audit.get("sha256") and sha256(value.encode("utf-8")).hexdigest() != audit["sha256"]:
        raise ValueError(f"OCR dictionary SHA256 mismatch: {model.id}")
    if audit.get("count") is not None and len(characters) != audit["count"]:
        raise ValueError(f"OCR dictionary count mismatch: {model.id}")
    if isinstance(output_classes, int) and output_classes != len(characters) + 2:
        raise ValueError(f"OCR logits/dictionary mismatch: {model.id}: {output_classes} != {len(characters)} + 2")
    actual = script_counts("".join(characters))
    if not model.scripts or any(actual.get(script, 0) == 0 for script in model.scripts):
        raise ValueError(f"OCR declared script/alphabet mismatch: {model.id}: {model.scripts}")
    return characters


def _preflight(model):
    import onnxruntime as ort
    options = ort.SessionOptions()
    options.intra_op_num_threads = 2
    options.inter_op_num_threads = 1
    session = ort.InferenceSession(str(model.path), sess_options=options, providers=["CPUExecutionProvider"])
    if session.get_providers() != ["CPUExecutionProvider"]:
        raise ValueError(f"OCR is not CPU-only: {model.id}: {session.get_providers()}")
    characters = ()
    if model.task == "rec":
        characters = validate_alphabet(model, session.get_modelmeta().custom_metadata_map,
                                       session.get_outputs()[0].shape[-1])
    return characters


def candidate_evidence(model, text, score, characters):
    counts = script_counts(text)
    alphabet = set("".join(characters))
    valid = all(character.isspace() or character in alphabet for character in text)
    letters = sum(counts.values())
    native = sum(counts.get(script, 0) for script in model.scripts if script != "Latn")
    return {"model_id": model.id, "model_sha256": model.sha256, "provider": "CPUExecutionProvider",
            "text": text, "raw_ctc_score": float(score), "score_calibrated": False,
            "dictionary_source": "onnx.metadata.character", "alphabet_entries": len(characters),
            "ctc_classes": len(characters) + 2,
            "scripts": counts, "alphabet_valid": valid, "script_fraction": native / max(letters, 1),
            "non_latin_letters": native}


def choose_candidate(candidates, *, explicit=False):
    """A heuristic choice, never a probability or an erasure of other readings."""
    if not candidates:
        raise ValueError("No OCR candidates")
    valid = [candidate for candidate in candidates if candidate["alphabet_valid"] and candidate["text"].strip()]
    if explicit:
        pool = valid or candidates
    else:
        # Script evidence must accompany a score. A dedicated model reading a
        # Latin line as only digits/Latin is not evidence for another script.
        non_latin = [candidate for candidate in valid if candidate["non_latin_letters"] >= 2
                     and candidate["script_fraction"] >= 0.30 and candidate["raw_ctc_score"] >= 0.70]
        baseline = candidates[0]
        if non_latin:
            best = max(non_latin, key=lambda item: item["raw_ctc_score"])
            pool = non_latin if best["raw_ctc_score"] >= baseline["raw_ctc_score"] - 0.10 else [baseline]
        else:
            pool = [baseline] if baseline in valid else (valid or candidates)
    chosen = max(pool, key=lambda item: item["raw_ctc_score"])
    alternatives = [item for item in valid if item["text"] != chosen["text"]
                    and item["raw_ctc_score"] >= max(0.70, chosen["raw_ctc_score"] - 0.12)]
    ambiguous = bool(alternatives or not chosen["alphabet_valid"] or chosen["raw_ctc_score"] < 0.70
                     or not chosen["text"].strip())
    return chosen, {"policy": "explicit-language" if explicit else "auto-script-best-effort-v1",
                    "ambiguous": ambiguous, "calibrated": False,
                    "reason": "conflicting-readings-or-weak-evidence" if ambiguous else "heuristic-script-and-alphabet-evidence",
                    "candidates": candidates, "selected_model": chosen["model_id"]}


class _CheckedEngine:
    def __init__(self, engine, classes):
        self.engine, self.classes = engine, classes

    def __getattr__(self, name):
        return getattr(self.engine, name)

    def __call__(self, batch):
        result = self.engine(batch)
        if result.shape[-1] != self.classes:
            raise ValueError(f"OCR logits/dictionary mismatch at inference: {result.shape[-1]} != {self.classes}")
        return result


class LocalOcrRouter:
    def __init__(self, models, language="auto"):
        from rapidocr import RapidOCR
        from rapidocr.utils.typings import EngineType, ModelType, OCRVersion
        self.models = models
        self.language = language.lower().replace("_", "-")
        self.lock = RLock()
        self.recognizers = {}
        self.alphabets = {}
        self.failures = {}
        self.rec_models = [model for model in models if model.task == "rec"]
        baseline = next((model for model in self.rec_models if model.ocr_version == "PP-OCRv6"), self.rec_models[0])
        self.rec_models.remove(baseline)
        self.rec_models.insert(0, baseline)
        params = {"EngineConfig.onnxruntime.intra_op_num_threads": 2,
                  "EngineConfig.onnxruntime.inter_op_num_threads": 1,
                  "Global.log_level": "error"}
        for accelerator in ("cuda", "dml", "cann", "coreml"):
            params[f"EngineConfig.onnxruntime.use_{accelerator}"] = False
        for section, task in (("Det", "det"), ("Cls", "cls"), ("Rec", "rec")):
            model = baseline if task == "rec" else next(item for item in models if item.task == task)
            characters = _preflight(model)
            if task == "rec":
                self.alphabets[model.id] = characters
            params.update({f"{section}.model_path": str(model.path), f"{section}.engine_type": EngineType.ONNXRUNTIME,
                           f"{section}.ocr_version": OCRVersion(model.ocr_version),
                           f"{section}.model_type": ModelType(model.model_type), f"{section}.lang_type": model.lang_type})
        self.base = RapidOCR(params=params)
        self.recognizers[baseline.id] = self._check_recognizer(self.base.text_rec, baseline)
        for engine in (self.base.text_det, self.base.text_cls):
            if engine.session.session.get_providers() != ["CPUExecutionProvider"]:
                raise ValueError("OCR detection/classification is not CPU-only")
        self.selected_models = self._models_for_language()

    def _models_for_language(self):
        if self.language == "auto":
            return self.rec_models
        result = []
        for language in self.language.replace(",", "+").split("+"):
            lang = _ALIASES.get(language, language)
            scripts = _LANG_SCRIPTS.get(lang)
            matches = [model for model in self.rec_models if model.lang_type == lang
                       or language in model.languages or (scripts and scripts.issubset(set(model.scripts)))]
            if not matches:
                raise ValueError(f"No local OCR recognizer for language/script {language!r}; provision a matching catalog model")
            if matches[0] not in result:
                result.append(matches[0])
        return result

    def _check_recognizer(self, recognizer, model):
        if recognizer.session.session.get_providers() != ["CPUExecutionProvider"]:
            raise ValueError(f"OCR recognizer is not CPU-only: {model.id}")
        characters = self.alphabets[model.id]
        if recognizer.postprocess_op.character != ["blank", *characters, " "]:
            raise ValueError(f"OCR decoder/alphabet mismatch: {model.id}")
        recognizer.session = _CheckedEngine(recognizer.session, len(characters) + 2)
        return recognizer

    def _recognizer(self, model):
        from rapidocr.ch_ppocr_rec import TextRecognizer
        from rapidocr.utils.typings import ModelType, OCRVersion
        if model.id not in self.recognizers:
            self.alphabets[model.id] = _preflight(model)
            cfg = copy.deepcopy(self.base.cfg.Rec)
            cfg.model_path, cfg.lang_type = str(model.path), model.lang_type
            cfg.ocr_version, cfg.model_type = OCRVersion(model.ocr_version), ModelType(model.model_type)
            self.recognizers[model.id] = self._check_recognizer(TextRecognizer(cfg), model)
        return self.recognizers[model.id]

    def __call__(self, image, *, return_word_box=False, return_single_char_box=False, accept_box=None):
        # RapidOCR mutates detection and word-box configuration between calls.
        with self.lock:
            return self._run(image, return_word_box, return_single_char_box, accept_box)

    def _run(self, image, word_boxes, char_boxes, accept_box):
        import numpy as np
        from rapidocr.ch_ppocr_rec import TextRecInput, TextRecOutput
        from rapidocr.utils.output import RapidOCROutput
        start = time.perf_counter()
        image = self.base.load_img(image)
        detected = self.base(image, use_det=True, use_cls=False, use_rec=False)
        boxes = [box for box in (() if detected.boxes is None else detected.boxes)
                 if accept_box is None or accept_box(box)]
        output = RapidOCROutput(img=image, boxes=np.asarray(boxes), txts=(), scores=(), word_results=())
        output.routing_evidence, output.routing_warnings = [], []
        if not boxes:
            return output
        boxes = np.asarray(boxes)
        crops = self.base.crop_text_regions(image, boxes)
        crops, _ = self.base.cls_and_rotate(crops)
        readings = []
        for model in self.selected_models:
            try:
                if model.id in self.failures:
                    raise ValueError(self.failures[model.id])
                result = self._recognizer(model)(TextRecInput(img=crops, return_word_box=word_boxes))
                readings.append((model, result))
            except (ValueError, RuntimeError) as error:
                if self.language != "auto":
                    raise
                self.failures[model.id] = str(error)
                output.routing_warnings.append({"model_id": model.id, "reason": str(error)})
        if not readings:
            raise RuntimeError(f"No usable local OCR recognizer: {output.routing_warnings}")
        if self.language == "auto":
            available_scripts = {script for model, result in readings for script in model.scripts}
            missing = sorted({"Cyrl", "Hang", "Hani", "Hira", "Kana"} - available_scripts)
            if missing:
                output.routing_warnings.append({"reason": "incomplete-local-script-coverage", "missing_scripts": missing})
        texts, scores, words = [], [], []
        for index in range(len(boxes)):
            candidates = [candidate_evidence(model, result.txts[index], result.scores[index], self.alphabets[model.id])
                          for model, result in readings]
            chosen, evidence = choose_candidate(candidates, explicit=self.language != "auto")
            evidence["model_failures"] = output.routing_warnings
            if output.routing_warnings:
                evidence["ambiguous"] = True
                evidence["reason"] = "incomplete-local-recognizers"
            evidence["attempted_models"] = [model.id for model in self.selected_models]
            evidence["shared_detection"] = True
            evidence["crop_sha256"] = sha256(crops[index].tobytes()).hexdigest()
            output.routing_evidence.append(evidence)
            result = next(result for model, result in readings if model.id == chosen["model_id"])
            texts.append(chosen["text"])
            scores.append(chosen["raw_ctc_score"])
            words.append(result.word_results[index] if word_boxes else None)
        output.boxes, output.txts, output.scores = boxes, tuple(texts), tuple(scores)
        output.word_results = ()
        indices = [index for index, word in enumerate(words) if word and texts[index].strip()]
        if word_boxes and indices:
            self.base.return_single_char_box = char_boxes
            selected_crops = [crops[index] for index in indices]
            selected = TextRecOutput(selected_crops, tuple(texts[index] for index in indices),
                                     tuple(scores[index] for index in indices), tuple(words[index] for index in indices))
            output.word_results = self.base.calc_word_boxes(selected_crops, boxes[indices], selected)
        output.routing_elapsed_seconds = time.perf_counter() - start
        return output


@lru_cache(maxsize=4)
def _cached_router(root: str, language: str, catalog_stamp: int):
    return LocalOcrRouter(load_catalog(root), language)


def get_local_ocr(model_root=None, language="auto"):
    root = resolve_ai_models_root(model_root)
    catalog = root / "ocr" / "rapidocr" / "catalog.json"
    stamp = catalog.stat().st_mtime_ns if catalog.is_file() else 0
    return _cached_router(str(root), language, stamp)
