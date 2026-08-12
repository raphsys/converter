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
class Rapport:
    pages_totales: int = 0
    pages_degradees: list[PageDegradee] = field(default_factory=list)
    polices_reconnues: list[str] = field(default_factory=list)
    polices_non_reconnues: list[str] = field(default_factory=list)
    clusters_rasterises: int = 0
    images: int = 0
    formes: int = 0
    liens: int = 0

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
        if self.clusters_rasterises:
            details.append(f"{self.clusters_rasterises} zone(s) rastérisée(s)")
        if self.liens:
            details.append(f"{self.liens} lien(s)")
        if details:
            lignes.append("Contenu : " + ", ".join(details) + ".")

        if self.polices_non_reconnues:
            lignes.append(
                f"{len(self.polices_non_reconnues)} police(s) non reconnues, "
                "substituées — à déposer dans fonts/ pour un rendu exact :"
            )
            for nom in sorted(set(self.polices_non_reconnues)):
                lignes.append(f"  {nom}")
        elif self.polices_reconnues:
            lignes.append(f"{len(set(self.polices_reconnues))} police(s), toutes reconnues.")

        return "\n".join(lignes)
