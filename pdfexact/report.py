"""Collecte des avertissements de conversion.

Aucune page ne fait échouer la conversion : une page qui pose problème est dégradée et
signalée ici. Le rapport est ce qui permet à l'utilisateur de savoir où regarder — et,
pour les polices, ce qu'il lui reste à déposer dans fonts/.
"""
import json
from dataclasses import asdict, dataclass, field


@dataclass
class PageDegradee:
    index: int
    motif: str


@dataclass
class DiagnosticElement:
    kind: str
    role: str
    source: str
    strategy: str
    bbox: dict[str, int]
    editable: bool = False
    confidence: float = 1.0
    reasons: list[str] = field(default_factory=list)


@dataclass
class DiagnosticLayout:
    index: int
    resume: str
    profiles: list[str] = field(default_factory=list)
    elements: dict[str, int] = field(default_factory=dict)
    strategies: dict[str, int] = field(default_factory=dict)
    inventory: list[DiagnosticElement] = field(default_factory=list)
    zones_ocr: int = 0
    zones_layout: int = 0
    layout_ai: dict = field(default_factory=dict)


@dataclass
class DiagnosticWordNative:
    conforme: bool
    paragraphes: int = 0
    tableaux: int = 0
    images: int = 0
    ancres: int = 0
    ancres_derriere: int = 0
    frames: int = 0
    textboxes: int = 0
    tableaux_positionnes: int = 0
    runs_compresses: int = 0


@dataclass
class CorrectionWordNative:
    pages_corrigees: int = 0
    textboxes_converties: int = 0
    lignes_converties: int = 0


@dataclass
class IssueCertificationFinale:
    page: int
    categorie: str
    message: str
    bbox: list[int] = field(default_factory=list)
    severite: str = "warning"


@dataclass
class CertificationFinale:
    active: bool = False
    conforme: bool = True
    pages_analysees: int = 0
    zones_ai: int = 0
    zones_visuelles_attendues: int = 0
    zones_visuelles_comparees: int = 0
    zones_visuelles_recuperees: int = 0
    zones_visuelles_non_couvertes: int = 0
    mots_source: int = 0
    mots_converti: int = 0
    ratio_texte: float = 1.0
    score_visuel_min: float | None = None
    score_zone_visuelle_min: float | None = None
    avertissements: list[str] = field(default_factory=list)
    issues: list[IssueCertificationFinale] = field(default_factory=list)


@dataclass
class Rapport:
    pages_totales: int = 0
    pages_degradees: list[PageDegradee] = field(default_factory=list)
    polices_reconnues: list[str] = field(default_factory=list)
    polices_substituees: list[str] = field(default_factory=list)
    polices_non_reconnues: list[str] = field(default_factory=list)
    clusters_rasterises: int = 0
    images: int = 0
    formes: int = 0
    tableaux: int = 0
    liens: int = 0
    diagnostics_layout: list[DiagnosticLayout] = field(default_factory=list)
    diagnostic_word_native: DiagnosticWordNative | None = None
    correction_word_native: CorrectionWordNative | None = None
    certification_finale: CertificationFinale | None = None

    def vers_json(self) -> str:
        return json.dumps(asdict(self), ensure_ascii=False, indent=2)

    def resume(self) -> str:
        lignes = [f"{self.pages_totales} page(s) converties."]

        if self.pages_degradees:
            lignes.append(f"{len(self.pages_degradees)} page(s) dégradées :")
            for page in self.pages_degradees:
                lignes.append(f"  page {page.index + 1} : {page.motif}")

        details = []
        if self.images:
            details.append(f"{self.images} image(s)")
        if self.formes:
            details.append(f"{self.formes} forme(s) vectorielle(s)")
        if self.tableaux:
            details.append(f"{self.tableaux} tableau(x)")
        if self.clusters_rasterises:
            details.append(f"{self.clusters_rasterises} zone(s) rastérisée(s)")
        if self.liens:
            details.append(f"{self.liens} lien(s)")
        if details:
            lignes.append("Contenu : " + ", ".join(details) + ".")

        if self.diagnostics_layout:
            lignes.append(f"Diagnostics layout : {len(self.diagnostics_layout)} page(s).")

        if self.diagnostic_word_native is not None:
            diag = self.diagnostic_word_native
            statut = "OK" if diag.conforme else "NON CONFORME"
            lignes.append(
                "Contrat Word native page-exact : "
                f"{statut} ({diag.paragraphes} paragraphe(s), {diag.tableaux} tableau(x), "
                f"frames={diag.frames}, ancres={diag.ancres}, textboxes éditables={diag.textboxes}, "
                f"tableaux positionnés={diag.tableaux_positionnes}, runs compressés={diag.runs_compresses}, "
                f"ancres derrière={diag.ancres_derriere})."
            )
        if self.correction_word_native is not None and self.correction_word_native.textboxes_converties:
            correction = self.correction_word_native
            lignes.append(
                "Correction Word native : "
                f"{correction.textboxes_converties} textbox(es) -> "
                f"{correction.lignes_converties} paragraphe(s) sur "
                f"{correction.pages_corrigees} page(s)."
            )
        if self.certification_finale is not None and self.certification_finale.active:
            certification = self.certification_finale
            statut = "OK" if certification.conforme else "À REVOIR"
            lignes.append(
                "Certification finale : "
                f"{statut}, {certification.zones_visuelles_recuperees} zone(s) récupérée(s), "
                f"{certification.zones_visuelles_non_couvertes} manque(s) visuel(s), "
                f"ratio texte={certification.ratio_texte:.3f}."
            )

        if self.polices_non_reconnues:
            lignes.append(
                f"{len(self.polices_non_reconnues)} police(s) non reconnues, "
                "substituées — à déposer dans fonts/ pour un rendu exact :"
            )
            for nom in sorted(set(self.polices_non_reconnues)):
                lignes.append(f"  {nom}")
        elif self.polices_reconnues:
            lignes.append(f"{len(set(self.polices_reconnues))} police(s), toutes reconnues.")
        if self.polices_substituees:
            lignes.append(f"{len(set(self.polices_substituees))} police(s) avec équivalent proche.")

        return "\n".join(lignes)
