"""Détection IA des zones documentaires.

Cette couche reprend le principe de Vysi : la page est d'abord rendue en image,
un détecteur visuel identifie les zones logiques, puis les boîtes sont ramenées
dans le repère PDF/EMU pour guider OCR, paragraphes et rendu Word.
"""
from __future__ import annotations

import importlib.util
import os
from collections.abc import Iterable, Mapping
from dataclasses import asdict, dataclass
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any

import pymupdf

from pdfexact.geometry import BBox, bbox_depuis_rect, pt_vers_emu
from pdfexact.analysis.geometry import bbox_area, intersection_area
from pdfexact.layout.model import LayoutPage

DEFAULT_LAYOUT_PROVIDER = "paddlex"
DEFAULT_LAYOUT_MODEL = "ppstructurev3/PP-DocLayout_plus-L"
# As in vysi (VYSI_PDF_LAYOUT_MIN_CONFIDENCE): a zone the model is less sure of is dropped.
CONFIANCE_MIN_ZONE = float(os.environ.get("PDFEXACT_LAYOUT_MIN_CONFIDENCE", "0.20"))
_MODEL_CACHE: dict[tuple[str, str, str], Any] = {}


class LayoutAIRequiredError(RuntimeError):
    """Raised when a required layout-AI pass cannot produce a page plan."""

TEXT_LABELS = {
    "text",
    "content",
    "title",
    "doc_title",
    "paragraph_title",
    "figure_title",
    "table_title",
    "caption",
    "header",
    "footer",
    "reference",
    "reference_content",
    "list",
    "number",
    "footnote",
    "abstract",
    "algorithm",
    "aside_text",
    "formula_number",
}

# Single source of the semantic role a layout label gives to the text it holds.
# Existing role names are reused where they drive behaviour (titles, captions,
# headers, footers, body continuity); the others name what the model saw.
_ROLES_SEMANTIQUES = {
    "text": "body",
    "doc_title": "title",
    "title": "title",
    "paragraph_title": "heading",
    "header": "header",
    "footer": "footer",
    "figure_title": "caption",
    "table_title": "caption",
    "caption": "caption",
    "content": "table-of-contents",
    "reference": "reference",
    "reference_content": "reference",
    "footnote": "footnote",
    "number": "page-number",
    "abstract": "abstract",
    "aside_text": "aside",
    "algorithm": "algorithm",
    "formula_number": "formula-number",
    "list": "list",
}


def role_semantique_etiquette(label: str) -> str | None:
    """Semantic role of the text held by a layout zone, None for visual zones."""
    return _ROLES_SEMANTIQUES.get(str(label).strip().casefold().replace(" ", "_").replace("-", "_"))


def _options_cpu_paddlex():
    """CPU inference: oneDNN (MKLDNN) kernels when available, every core."""
    from paddlex.inference.utils.misc import is_mkldnn_available
    from paddlex.inference.utils.pp_option import PaddlePredictorOption

    return PaddlePredictorOption(run_mode="mkldnn" if is_mkldnn_available() else "paddle",
                                 cpu_threads=max(1, os.cpu_count() or 1))


@dataclass(frozen=True)
class LayoutAIZone:
    zone_id: str
    label: str
    role: str
    confidence: float | None
    bbox: BBox
    source: str
    model_id: str

    def to_report(self) -> dict[str, Any]:
        value = asdict(self)
        value["bbox"] = [self.bbox.x0, self.bbox.y0, self.bbox.x1, self.bbox.y1]
        return value


@dataclass(frozen=True)
class LayoutAIPage:
    status: str
    provider: str
    model_id: str
    model_path: str | None
    zones: tuple[LayoutAIZone, ...]
    warnings: tuple[str, ...] = ()

    def to_report(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "provider": self.provider,
            "model_id": self.model_id,
            "model_path": self.model_path,
            "zone_count": len(self.zones),
            "warnings": list(self.warnings),
            "zones": [zone.to_report() for zone in self.zones],
        }


def detecter_layout_ia(
    page,
    analyse: LayoutPage,
    *,
    provider: str | None = None,
    model: str | None = None,
    model_root: str | Path | None = None,
    device: str | None = None,
    render_scale: float = 1.5,
    required: bool = False,
) -> LayoutAIPage:
    provider = (provider or os.environ.get("PDFEXACT_LAYOUT_PROVIDER") or DEFAULT_LAYOUT_PROVIDER).strip().casefold()
    requested_model = model or os.environ.get("PDFEXACT_LAYOUT_MODEL") or DEFAULT_LAYOUT_MODEL
    root = _resolve_model_root(model_root)
    model_path = _resolve_model_path(root, requested_model)
    if provider in {"auto", "vysi"}:
        provider = _provider_auto(model_path)
    model_id = _model_id(model_path, root, requested_model)

    if provider in {"", "none", "off", "0", "false"}:
        return _failure_or_fallback(
            analyse, provider, model_id, model_path, "layout_ai_disabled", required
        )
    if provider not in {"paddlex", "ultralytics", "yolo"}:
        return _failure_or_fallback(
            analyse, provider, model_id, model_path, f"unsupported_provider:{provider}", required
        )
    if provider == "paddlex" and (model_path is None or not model_path.is_dir()):
        return _failure_or_fallback(
            analyse, provider, model_id, model_path, f"model_not_found:{requested_model}", required
        )
    if provider in {"ultralytics", "yolo"} and model_path is None:
        return _failure_or_fallback(
            analyse, provider, model_id, model_path, f"model_not_found:{requested_model}", required
        )
    if provider == "paddlex" and not (_module_available("paddle") and _module_available("paddlex")):
        return _failure_or_fallback(
            analyse, provider, model_id, model_path, "paddle_or_paddlex_missing", required
        )
    if provider in {"ultralytics", "yolo"} and not _module_available("ultralytics"):
        return _failure_or_fallback(
            analyse, provider, model_id, model_path, "ultralytics_missing", required
        )

    try:
        if provider == "paddlex":
            zones = _detecter_paddlex(
                page,
                provider=provider,
                model_path=model_path,
                model_id=model_id,
                device=device,
                render_scale=render_scale,
            )
        else:
            zones = _detecter_ultralytics(
                page,
                provider="ultralytics",
                model_path=model_path,
                model_id=model_id,
                device=device,
                render_scale=render_scale,
            )
    except Exception as exc:  # noqa: BLE001 - le mode requis doit rester explicite
        return _failure_or_fallback(
            analyse,
            provider,
            model_id,
            model_path,
            f"layout_ai_error:{type(exc).__name__}",
            required,
        )

    zones = filtrer_confiance(zones)
    if not zones:
        return _failure_or_fallback(
            analyse, provider, model_id, model_path, "layout_ai_empty", required
        )
    return LayoutAIPage(
        status="layout_ai_detected",
        provider=provider,
        model_id=model_id,
        model_path=str(model_path),
        zones=tuple(_dedoublonner(zones)),
    )


def _failure_or_fallback(
    analyse: LayoutPage,
    provider: str,
    model_id: str,
    model_path: Path | None,
    warning: str,
    required: bool,
) -> LayoutAIPage:
    if required:
        raise LayoutAIRequiredError(
            f"layout IA requis mais indisponible: {warning}; "
            f"provider={provider or 'unset'}, model={model_id}"
        )
    return _fallback(analyse, provider, model_id, model_path, warning)


def _detecter_paddlex(
    page,
    *,
    provider: str,
    model_path: Path,
    model_id: str,
    device: str | None,
    render_scale: float,
) -> list[LayoutAIZone]:
    os.environ.setdefault("DISABLE_MODEL_SOURCE_CHECK", "True")
    os.environ.setdefault("PADDLE_PDX_DISABLE_MODEL_SOURCE_CHECK", "True")
    from paddlex import create_model  # type: ignore[import-not-found]

    resolved_device = device or os.environ.get("PDFEXACT_LAYOUT_DEVICE", "cpu")
    cache_key = (provider, str(model_path), resolved_device)
    model = _MODEL_CACHE.get(cache_key)
    if model is None:
        model = create_model(
            model_name=model_path.name,
            model_dir=str(model_path),
            device=resolved_device,
            **({"pp_option": _options_cpu_paddlex()} if resolved_device == "cpu" else {}),
        )
        _MODEL_CACHE[cache_key] = model
    with TemporaryDirectory(prefix="pdfexact-layout-ai-") as dossier:
        image_path = Path(dossier) / "page.png"
        pix = page.get_pixmap(matrix=pymupdf.Matrix(render_scale, render_scale), alpha=False)
        pix.save(str(image_path))
        raw = model.predict(input=str(image_path), batch_size=1, layout_nms=True)
        return _normaliser_detections(
            raw,
            provider=provider,
            model_id=model_id,
            page_width_pt=float(page.rect.width),
            page_height_pt=float(page.rect.height),
            image_width=float(pix.width),
            image_height=float(pix.height),
        )


def _detecter_ultralytics(
    page,
    *,
    provider: str,
    model_path: Path,
    model_id: str,
    device: str | None,
    render_scale: float,
) -> list[LayoutAIZone]:
    """Execute the VYSI Ultralytics route with explicit local weights only."""
    if not model_path.is_file():
        raise FileNotFoundError(f"Ultralytics weights must be a local file: {model_path}")
    from ultralytics import YOLO  # type: ignore[import-not-found]

    resolved_device = device or os.environ.get("PDFEXACT_LAYOUT_DEVICE", "cpu")
    cache_key = (provider, str(model_path), resolved_device)
    model = _MODEL_CACHE.get(cache_key)
    if model is None:
        model = YOLO(str(model_path))
        _MODEL_CACHE[cache_key] = model
    with TemporaryDirectory(prefix="pdfexact-layout-ai-") as dossier:
        image_path = Path(dossier) / "page.png"
        pix = page.get_pixmap(matrix=pymupdf.Matrix(render_scale, render_scale), alpha=False)
        pix.save(str(image_path))
        results = model.predict(
            source=str(image_path),
            device=resolved_device,
            verbose=False,
            save=False,
            stream=False,
        )
        detections: list[dict[str, Any]] = []
        for result in results or ():
            boxes = getattr(result, "boxes", None)
            if boxes is None:
                continue
            coordinates = _to_list(getattr(boxes, "xyxy", None))
            confidences = _to_list(getattr(boxes, "conf", None))
            classes = _to_list(getattr(boxes, "cls", None))
            names = getattr(result, "names", {})
            for index, bbox in enumerate(coordinates or ()):
                if not isinstance(bbox, (list, tuple)) or len(bbox) != 4:
                    continue
                class_id = int(float(classes[index])) if index < len(classes or ()) else None
                if isinstance(names, dict):
                    label = str(names.get(class_id, class_id if class_id is not None else "unknown"))
                else:
                    label = str(class_id if class_id is not None else "unknown")
                detections.append(
                    {
                        "bbox": bbox,
                        "label": label,
                        "score": confidences[index] if index < len(confidences or ()) else None,
                    }
                )
        return _normaliser_detections(
            detections,
            provider=provider,
            model_id=model_id,
            page_width_pt=float(page.rect.width),
            page_height_pt=float(page.rect.height),
            image_width=float(pix.width),
            image_height=float(pix.height),
        )


def _to_list(value: Any) -> list[Any]:
    if value is None:
        return []
    detach = getattr(value, "detach", None)
    if callable(detach):
        value = detach()
    cpu = getattr(value, "cpu", None)
    if callable(cpu):
        value = cpu()
    tolist = getattr(value, "tolist", None)
    if callable(tolist):
        value = tolist()
    if isinstance(value, (list, tuple)):
        return list(value)
    return []


def _normaliser_detections(
    raw: Any,
    *,
    provider: str,
    model_id: str,
    page_width_pt: float,
    page_height_pt: float,
    image_width: float,
    image_height: float,
) -> list[LayoutAIZone]:
    detections = []
    for item in _iter_detection_dicts(raw):
        bbox = item.get("bbox", item.get("coordinate", item.get("coordinates", item.get("box"))))
        if not isinstance(bbox, (list, tuple)) or len(bbox) != 4:
            continue
        try:
            x0, y0, x1, y1 = (float(value) for value in bbox)
        except (TypeError, ValueError):
            continue
        sx = page_width_pt / max(1.0, image_width)
        sy = page_height_pt / max(1.0, image_height)
        rect = _clamp_pt((x0 * sx, y0 * sy, x1 * sx, y1 * sy), page_width_pt, page_height_pt)
        if rect is None:
            continue
        label = str(item.get("label", item.get("label_name", item.get("category_name", item.get("type", "unknown")))))
        confidence = item.get("score", item.get("confidence"))
        try:
            confidence = float(confidence) if confidence is not None else None
        except (TypeError, ValueError):
            confidence = None
        detections.append(
            LayoutAIZone(
                zone_id=f"ai_z{len(detections) + 1:04d}",
                label=label,
                role=_role(label),
                confidence=confidence,
                bbox=bbox_depuis_rect(pymupdf.Rect(*rect)),
                source=provider,
                model_id=model_id,
            )
        )
    return detections


def _fallback(
    analyse: LayoutPage,
    provider: str,
    model_id: str,
    model_path: Path | None,
    warning: str,
) -> LayoutAIPage:
    zones = _zones_geometriques(analyse)
    return LayoutAIPage(
        status="layout_ai_fallback",
        provider=provider or "geometric",
        model_id=model_id,
        model_path=str(model_path) if model_path else None,
        zones=zones,
        warnings=(warning,),
    )


def _zones_geometriques(analyse: LayoutPage) -> tuple[LayoutAIZone, ...]:
    zones: list[LayoutAIZone] = []
    for block in analyse.text_blocks:
        if block.bbox.largeur < pt_vers_emu(16) or block.bbox.hauteur < pt_vers_emu(6):
            continue
        zones.append(
            LayoutAIZone(
                zone_id=f"geo_t{len(zones) + 1:04d}",
                label="native_text_block",
                role="text",
                confidence=None,
                bbox=block.bbox,
                source="geometric",
                model_id="native_text_block_fallback",
            )
        )
    return tuple(sorted(zones, key=lambda item: (item.bbox.y0, item.bbox.x0)))


def _role(label: str) -> str:
    norm = label.strip().casefold().replace(" ", "_").replace("-", "_")
    if "caption" in norm or "figure_title" in norm or "table_title" in norm:
        return "caption"
    if norm in TEXT_LABELS or "text" in norm:
        return "text"
    if "table" in norm:
        return "table"
    if "formula" in norm or "equation" in norm:
        return "formula"
    if "image" in norm or "figure" in norm or "chart" in norm:
        return "visual"
    return "other"


def _iter_detection_dicts(raw: Any):
    raw = _plain(raw)
    if isinstance(raw, Mapping):
        for key in ("boxes", "layout_det_res", "results", "res", "objects"):
            nested = raw.get(key)
            if nested is not None:
                yield from _iter_detection_dicts(nested)
                return
        if any(key in raw for key in ("bbox", "coordinate", "coordinates", "box")):
            yield raw
        return
    if isinstance(raw, (list, tuple)) or (
        isinstance(raw, Iterable) and not isinstance(raw, (str, bytes, bytearray, Mapping))
    ):
        for value in raw:
            yield from _iter_detection_dicts(value)
        return


def _plain(value: Any) -> Any:
    if isinstance(value, Mapping):
        return value
    json_value = getattr(value, "json", None)
    if isinstance(json_value, Mapping):
        return json_value
    if callable(json_value):
        try:
            result = json_value()
            if isinstance(result, Mapping):
                return result
        except Exception:
            pass
    method = getattr(value, "to_dict", None)
    if callable(method):
        try:
            result = method()
            if isinstance(result, Mapping):
                return result
        except Exception:
            pass
    return value


def _resolve_model_root(value: str | Path | None) -> Path:
    if value:
        return Path(value).expanduser().resolve()
    env = os.environ.get("PDFEXACT_AI_MODELS_ROOT") or os.environ.get("VYSI_AI_MODELS_ROOT")
    if env:
        return Path(env).expanduser().resolve()
    vysi_root = Path("/home/raphael/Mes_Projets/vysi/ai_models")
    if vysi_root.exists():
        return vysi_root.resolve()
    return (Path.cwd() / "ai_models").resolve()


def _resolve_model_path(root: Path, requested: str) -> Path | None:
    direct = Path(requested).expanduser()
    if direct.is_absolute():
        return direct.resolve() if direct.exists() else None
    candidates = [requested]
    if "/" not in requested:
        candidates.append(f"ppstructurev3/{requested}")
    for candidate in candidates:
        path = root / candidate
        if path.exists():
            return path.resolve()
        folded = _resolve_casefold(root, candidate)
        if folded is not None and folded.exists():
            return folded.resolve()
    return None


def _provider_auto(model_path: Path | None) -> str:
    """Choose a local runtime from the model artifact, never from the filename alone."""
    if model_path is not None and model_path.is_file():
        if model_path.suffix.casefold() in {".pt", ".onnx"}:
            return "ultralytics"
    return "paddlex"


def _resolve_casefold(root: Path, relative: str) -> Path | None:
    current = root
    for part in Path(relative).parts:
        if not current.is_dir():
            return None
        matches = [item for item in current.iterdir() if item.name.casefold() == part.casefold()]
        if len(matches) != 1:
            return None
        current = matches[0]
    return current


def _model_id(path: Path | None, root: Path, requested: str) -> str:
    if path is None:
        return requested
    try:
        return path.relative_to(root).as_posix()
    except ValueError:
        return path.name


def _module_available(name: str) -> bool:
    try:
        return importlib.util.find_spec(name) is not None
    except (ImportError, AttributeError, ValueError):
        return False


def _clamp_pt(
    bbox: tuple[float, float, float, float],
    width: float,
    height: float,
) -> tuple[float, float, float, float] | None:
    x0, y0, x1, y1 = bbox
    x0 = max(0.0, min(width, x0))
    y0 = max(0.0, min(height, y0))
    x1 = max(0.0, min(width, x1))
    y1 = max(0.0, min(height, y1))
    if x1 - x0 < 2 or y1 - y0 < 2:
        return None
    return (x0, y0, x1, y1)


def _aire(bbox: BBox) -> int:
    return bbox_area(bbox)


def _intersection(a: BBox, b: BBox) -> int:
    return intersection_area(a, b)


def filtrer_confiance(zones: list[LayoutAIZone], seuil: float = CONFIANCE_MIN_ZONE) -> list[LayoutAIZone]:
    """Zones at or above the confidence floor (an unknown confidence is kept)."""
    return [zone for zone in zones if zone.confidence is None or zone.confidence >= seuil]


def _dedoublonner(zones: list[LayoutAIZone]) -> list[LayoutAIZone]:
    gardees: list[LayoutAIZone] = []
    for zone in sorted(zones, key=lambda item: (item.confidence or 0.0, _aire(item.bbox)), reverse=True):
        if any(
            _intersection(zone.bbox, autre.bbox) / max(min(_aire(zone.bbox), _aire(autre.bbox)), 1) > 0.92
            and zone.role == autre.role
            for autre in gardees
        ):
            continue
        gardees.append(zone)
    return sorted(gardees, key=lambda item: (item.bbox.y0, item.bbox.x0))
