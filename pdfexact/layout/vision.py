"""Zone vision with SmolVLM-500M (Idefics3) in int8 ONNX on CPU, no torch.

Each visual zone (image or raster) is classified by type and by whether it
holds readable text: text inside images must be read (OCR) and translated,
photos and logos must not. A zone the model cannot read is marked, never
guessed.
"""
from __future__ import annotations

import json
import os
import re

import numpy as np
from PIL import Image

from pdfexact.geometry import PageGeometry, emu_vers_pt, pt_vers_emu
from pdfexact.ir import ImageEl, RasterEl
from pdfexact.model_paths import resolve_ai_models_root

IMAGE_TOKEN = 49190
FIN = 49279  # <end_of_utterance>
TAILLE = 512
TOKENS_IMAGE = 64
TYPES = ("photo", "logo", "chart", "diagram", "map", "table", "text", "formula", "decoration")
QUESTION = (
    "What is this image region? Answer with one word among: " + ", ".join(TYPES)
    + ". Then answer yes or no: does it contain readable text? Format: <word>, <yes|no>"
)
# Below this size a zone holds no readable content (rules, bullets, specks).
COTE_MIN_PT = 36.0
_MODELE = "smolvlm-500m-q4-int8"
# Quantised graphs runnable by onnxruntime on CPU. The int8 vision graph uses a
# signed ConvInteger that the CPU provider does not implement; its q4 variant
# quantises the matrix products to 4 bits (MatMulNBits) and keeps the patch
# convolution in float.
FICHIERS_ONNX = {
    "vision_encoder": "vision_encoder_q4.onnx",
    "embed_tokens": "embed_tokens_int8.onnx",
    "decoder_model_merged": "decoder_model_merged_int8.onnx",
}


def _pretraiter(image: Image.Image):
    """Idefics3 without splitting: longest edge 512, zero padding, mask of real pixels."""
    image = image.convert("RGB")
    ratio = TAILLE / max(image.size)
    largeur, hauteur = (max(1, round(side * ratio)) for side in image.size)
    resized = np.asarray(image.resize((largeur, hauteur), Image.LANCZOS), dtype=np.float32)
    pixels = np.zeros((1, 1, 3, TAILLE, TAILLE), dtype=np.float32)
    pixels[0, 0, :, :hauteur, :largeur] = ((resized / 255.0) - 0.5).transpose(2, 0, 1) / 0.5
    mask = np.zeros((1, 1, TAILLE, TAILLE), dtype=np.bool_)
    mask[0, 0, :hauteur, :largeur] = True
    return pixels, mask


def _prompt(question: str) -> str:
    image = "<fake_token_around_image><global-img>" + "<image>" * TOKENS_IMAGE + "<fake_token_around_image>"
    return f"<|im_start|>User:{image}{question}<end_of_utterance>\nAssistant:"


def _fusionner(ids, embeds, features):
    """Put the image features in place of the image tokens, in order."""
    positions = np.flatnonzero(ids[0] == IMAGE_TOKEN)
    flat = features.reshape(-1, embeds.shape[-1])
    if len(positions) != len(flat):
        raise ValueError(f"image-token-mismatch:{len(positions)}!={len(flat)}")
    merged = embeds.copy()
    merged[0, positions] = flat
    return merged


def _lire_reponse(text: str):
    words = re.findall(r"[a-z]+", str(text).casefold())
    kind = next((word for word in words if word in TYPES), None)
    flag = next((word for word in words if word in {"yes", "no"}), None)
    if kind is None or flag is None:
        return None
    # Text in an image is translatable, except a logo (a brand name stays as is).
    return {"type": kind, "contains_text": flag == "yes", "translatable": flag == "yes" and kind != "logo"}


def zones_texte_image(page) -> list:
    """Visual zones to read by OCR: text seen by vision, or zones it could not understand."""
    zones = []
    for element in page.elements:
        seen = (getattr(element, "attributes", None) or {}).get("vision")
        if isinstance(element, (ImageEl, RasterEl)) and seen and (
                seen.get("contains_text") is True or seen.get("status") == "non-compris"):
            zones.append(element.bbox)
    return zones


def zones_a_voir(page) -> list:
    minimum = pt_vers_emu(COTE_MIN_PT)
    return [element for element in page.elements
            if isinstance(element, (ImageEl, RasterEl))
            and element.bbox.largeur >= minimum and element.bbox.hauteur >= minimum]


class VisionSmolVLM:
    """Lazy int8 ONNX sessions, loaded once and reused for every zone."""

    def __init__(self, model_root=None):
        self.path = resolve_ai_models_root(model_root) / "visual_layout" / "smolvlm-500m"
        self._sessions = None

    def _charger(self):
        import onnxruntime as ort
        from tokenizers import Tokenizer

        options = ort.SessionOptions()
        options.intra_op_num_threads = max(1, os.cpu_count() or 1)
        options.inter_op_num_threads = 1
        options.graph_optimization_level = ort.GraphOptimizationLevel.ORT_ENABLE_ALL

        def session(name):
            return ort.InferenceSession(str(self.path / "onnx" / FICHIERS_ONNX[name]), options,
                                        providers=["CPUExecutionProvider"])

        text = json.loads((self.path / "config.json").read_text())["text_config"]
        decoder = session("decoder_model_merged")
        self._sessions = {
            "vision": session("vision_encoder"), "embed": session("embed_tokens"), "decoder": decoder,
            "tokenizer": Tokenizer.from_file(str(self.path / "tokenizer.json")),
            "layers": text["num_hidden_layers"], "kv_heads": text["num_key_value_heads"],
            "head_dim": text.get("head_dim") or text["hidden_size"] // text["num_attention_heads"],
            "present": [output.name for output in decoder.get_outputs()[1:]],
        }

    def repondre(self, image: Image.Image, question: str = QUESTION, max_tokens: int = 16) -> str:
        if self._sessions is None:
            self._charger()
        s = self._sessions
        pixels, mask = _pretraiter(image)
        wanted = {item.name for item in s["vision"].get_inputs()}
        features = s["vision"].run(None, {key: value for key, value in
                                          (("pixel_values", pixels), ("pixel_attention_mask", mask)) if key in wanted})[0]
        ids = np.array([s["tokenizer"].encode(_prompt(question)).ids], dtype=np.int64)
        embeds = _fusionner(ids, s["embed"].run(None, {"input_ids": ids})[0], features)
        past = {f"past_key_values.{layer}.{kind}": np.zeros((1, s["kv_heads"], 0, s["head_dim"]), np.float32)
                for layer in range(s["layers"]) for kind in ("key", "value")}
        length, produced = ids.shape[1], []
        positions = np.arange(length, dtype=np.int64)[None]
        for _ in range(max_tokens):
            outputs = s["decoder"].run(None, {"inputs_embeds": embeds, "attention_mask": np.ones((1, length), np.int64),
                                              "position_ids": positions, **past})
            token = int(outputs[0][0, -1].argmax())
            if token == FIN:
                break
            produced.append(token)
            past = {name.replace("present", "past_key_values"): value for name, value in zip(s["present"], outputs[1:])}
            embeds = s["embed"].run(None, {"input_ids": np.array([[token]], np.int64)})[0]
            positions = np.array([[length]], dtype=np.int64)
            length += 1
        return s["tokenizer"].decode(produced, skip_special_tokens=True)


def _image_zone(pdf_page, element, geometry) -> Image.Image:
    import pymupdf

    rect = pymupdf.Rect(*(emu_vers_pt(value) for value in (element.bbox.x0, element.bbox.y0, element.bbox.x1, element.bbox.y1)))
    clip = geometry.rect_affiche_vers_natif(rect)
    zoom = TAILLE / max(clip.width, clip.height, 1.0)
    pixmap = pdf_page.get_pixmap(matrix=pymupdf.Matrix(zoom, zoom), clip=clip, alpha=False)
    return Image.frombytes("RGB", (pixmap.width, pixmap.height), pixmap.samples)


def annoter_zones_visuelles(document, source_pdf, vision: VisionSmolVLM) -> list[dict]:
    """Classify every readable visual zone; failures are marked, not guessed."""
    import pymupdf

    zones = [(page, zones_a_voir(page)) for page in document.pages]
    if not any(elements for _, elements in zones):
        return []
    rapports, vus = [], {}
    with pymupdf.open(source_pdf) as pdf:
        for page, elements in zones:
            if not elements:
                continue
            pdf_page = pdf[page.index]
            geometry = PageGeometry.depuis_page(pdf_page)
            for element in elements:
                key = (getattr(element, "media_ref", None), element.bbox)
                if key not in vus:
                    try:
                        answer = vision.repondre(_image_zone(pdf_page, element, geometry))
                        result = _lire_reponse(answer)
                        vus[key] = ({**result, "status": "compris", "model": _MODELE} if result
                                    else {"status": "non-compris", "reason": f"unreadable-answer:{answer[:80]}", "model": _MODELE})
                    except Exception as exc:  # noqa: BLE001 - the zone is marked, the run goes on
                        vus[key] = {"status": "non-compris", "reason": f"{type(exc).__name__}: {exc}"[:200], "model": _MODELE}
                element.attributes["vision"] = dict(vus[key])
                rapports.append({"page": page.index, **vus[key]})
    return rapports
