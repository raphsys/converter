"""Resolution locale de la racine commune des modeles IA (sans telechargement)."""
from pathlib import Path
import os


def resolve_ai_models_root(value=None) -> Path:
    if value is not None:
        return Path(value).expanduser().resolve()
    configured = os.environ.get("PDFEXACT_AI_MODELS_ROOT") or os.environ.get("VYSI_AI_MODELS_ROOT")
    if configured:
        return Path(configured).expanduser().resolve()
    local = Path("/home/raphael/Mes_Projets/vysi/ai_models")
    return local if local.is_dir() else (Path.cwd() / "ai_models")
