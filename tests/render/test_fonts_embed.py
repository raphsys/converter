import pytest

from pdfexact.render.fonts_embed import nouveau_guid, obfusquer_police

GUID_FIXE = "{12345678-1234-5678-1234-567812345678}"


def test_obfuscation_est_son_propre_inverse():
    original = bytes(range(64))

    une_fois = obfusquer_police(original, GUID_FIXE)
    deux_fois = obfusquer_police(une_fois, GUID_FIXE)

    assert deux_fois == original


def test_obfuscation_ne_touche_que_les_32_premiers_octets():
    original = bytes(64)

    resultat = obfusquer_police(original, GUID_FIXE)

    assert resultat[32:] == original[32:]
    assert resultat[:32] != original[:32]


def test_la_cle_est_le_guid_en_octets_inverses():
    """La clé XOR est la suite d'octets du GUID, lue à l'envers, appliquée deux fois."""
    resultat = obfusquer_police(bytes(32), GUID_FIXE)

    attendu = bytes.fromhex("12345678123456781234567812345678")[::-1] * 2
    assert resultat == attendu


def test_une_police_plus_courte_que_32_octets_ne_leve_pas():
    assert len(obfusquer_police(b"court", GUID_FIXE)) == 5


def test_un_guid_sans_accolades_est_accepte():
    sans = obfusquer_police(bytes(32), "12345678-1234-5678-1234-567812345678")
    avec = obfusquer_police(bytes(32), GUID_FIXE)

    assert sans == avec


def test_un_guid_malforme_est_rejete():
    with pytest.raises(ValueError):
        obfusquer_police(bytes(32), "{pas-un-guid}")


def test_guid_a_le_format_attendu():
    guid = nouveau_guid()

    assert len(guid) == 38
    assert guid.startswith("{") and guid.endswith("}")
    assert guid.count("-") == 4


def test_deux_guid_successifs_different():
    assert nouveau_guid() != nouveau_guid()
