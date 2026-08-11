"""Embarquement de polices dans un package OOXML.

Word attend les polices embarquées sous forme obfusquée (extension .odttf) : les 32
premiers octets du fichier sont combinés par XOR avec une clé de 16 octets dérivée du
GUID déclaré dans fontTable.xml. L'opération est involutive.

Ce module est pour l'instant de l'infrastructure non branchée : la conversion utilise les
polices système, pas l'embarquement. Voir docs/superpowers/notes/decision-polices.md.
"""
import uuid


def nouveau_guid() -> str:
    """Retourne un GUID au format attendu par w:fontKey, accolades comprises."""
    return "{" + str(uuid.uuid4()).upper() + "}"


def _cle_depuis_guid(guid: str) -> bytes:
    hexa = guid.strip("{}").replace("-", "")
    if len(hexa) != 32:
        raise ValueError(f"GUID malformé : {guid!r}")
    return bytes.fromhex(hexa)[::-1]


def obfusquer_police(octets: bytes, guid: str) -> bytes:
    """Obfusque (ou désobfusque — l'opération est involutive) une police pour Word."""
    cle = _cle_depuis_guid(guid)
    donnees = bytearray(octets)
    for i in range(min(32, len(donnees))):
        donnees[i] ^= cle[i % 16]
    return bytes(donnees)
