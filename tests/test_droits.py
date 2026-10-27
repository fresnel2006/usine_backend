"""Matrice des droits (section 4) : une requête par rôle et par case de la matrice.

Pour chaque ressource et chaque action, une action autorisée renvoie 200, 201 ou 204 (suppression),
et une action interdite renvoie 403 avec le message attendu.
"""
import re
from datetime import date
from pathlib import Path

import pytest
from sqlalchemy import select

from app import models
from app.security import DROITS, MESSAGE_INTERDIT, ROLES, hacher_mot_de_passe

# Copie littérale de la section 4 : Administrateur, Responsable atelier, Collaborateur responsable, Opérateur
MATRICE_DOCUMENT = {
    "ateliers": ("CLMS", "CLMS", "L", "L"),
    "lignes": ("CLMS", "CLMS", "L", "L"),
    "lots": ("CLMS", "CLMS", "L", "L"),
    "produits": ("CLMS", "CLMS", "L", "L"),
    "operateurs": ("CLMS", "L", "CLMS", "L"),
    "equipes": ("CLMS", "L", "CLMS", "L"),
    "types_incident": ("CLMS", "L", "CLMS", "L"),
    "incidents": ("CLMS", "L", "CLMS", "CL"),
    "machines": ("CLMS", "L", "CLMS", "CLMS"),
    "maintenances": ("CLMS", "L", "CLMS", "CLM"),
    "pieces_consommees": ("CLMS", "L", "CLMS", "CLM"),
    "pieces": ("CLMS", "L", "CLMS", "CLMS"),
    "nomenclature": ("CLMS", "L", "CLMS", "CLMS"),
    "achats": ("CLMS", "L", "CLMS", "CLM"),
    "fournisseurs": ("CLMS", "L", "L", "L"),
    "utilisateurs": ("CLMS", "-", "-", "-"),
    "profil": ("LM", "LM", "LM", "LM"),
}
LETTRES = {"C": "creer", "L": "lire", "M": "modifier", "S": "supprimer"}
COMPTES = {
    "ADMINISTRATEUR": "admin",
    "RESPONSABLE_ATELIER": "itoure",
    "COLLABORATEUR_RESPONSABLE": "mbamba",
    "OPERATEUR": "knguessan",
}


def matrice_attendue() -> dict[str, dict[str, set[str]]]:
    attendue: dict[str, dict[str, set[str]]] = {}
    for ressource, droits in MATRICE_DOCUMENT.items():
        actions = {action: set() for action in LETTRES.values()}
        for role, lettres in zip(ROLES, droits):
            for lettre in lettres.replace("-", ""):
                actions[LETTRES[lettre]].add(role)
        attendue[ressource] = actions
    return attendue


def test_la_matrice_de_l_api_est_celle_du_document():
    api = {r: {a: set(roles) for a, roles in actions.items()} for r, actions in DROITS.items()}
    assert api == matrice_attendue()


def lire_permissions_front() -> dict[str, dict[str, set[str]]]:
    """Lit l'objet DROITS de frontend/src/utils/permissions.js (format : une ressource par ligne)."""
    fichier = Path(__file__).resolve().parents[2] / "frontend" / "src" / "utils" / "permissions.js"
    texte = fichier.read_text(encoding="utf-8")
    bloc = texte.split("export const DROITS = {", 1)[1].split("\n}", 1)[0]
    lettres = {"A": "ADMINISTRATEUR", "R": "RESPONSABLE_ATELIER", "C": "COLLABORATEUR_RESPONSABLE", "O": "OPERATEUR"}
    front = {}
    for ligne in bloc.strip().splitlines():
        m = re.match(r"\s*(\w+):\s*\{(.*)\},?\s*$", ligne)
        if not m:
            continue
        actions = {}
        for action, valeur in re.findall(r"(\w+):\s*(TOUS|AUCUN|\[[^\]]*\])", m.group(2)):
            if valeur == "TOUS":
                actions[action] = set(ROLES)
            elif valeur == "AUCUN":
                actions[action] = set()
            else:
                actions[action] = {lettres[x.strip()] for x in valeur.strip("[]").split(",") if x.strip()}
        front[m.group(1)] = actions
    return front


def test_la_matrice_du_front_est_identique_a_celle_de_l_api():
    assert lire_permissions_front() == matrice_attendue()


# ---------------------------------------------------------------------
# Une requête valide par case de la matrice
# ---------------------------------------------------------------------
def maintenance_de_knguessan(db) -> int:
    """Maintenance du 19/10/2026 sur la broyeuse, effectuée par OP005 (knguessan) et OP006."""
    return db.scalar(
        select(models.Maintenance.num_maintenance)
        .where(models.Maintenance.num_machine == 1)
        .where(models.Maintenance.operateurs.any(models.Operateur.matricule == "OP005"))
    )


def premier_incident(db) -> int:
    return db.scalar(select(models.Incident.num_incident).order_by(models.Incident.num_incident))


def ajouter(db, objet):
    db.add(objet)
    db.flush()
    return objet


def changer_mot_de_passe(c, h, db, login):
    db.get(models.Utilisateur, login).mot_de_passe = hacher_mot_de_passe("Ancien@2026")
    db.flush()
    corps = {"ancien_mot_de_passe": "Ancien@2026", "nouveau_mot_de_passe": "Nouveau@2026", "confirmation": "Nouveau@2026"}
    return c.put("/api/profil/mot-de-passe", json=corps, headers=h)


SCENARIOS = {
    "ateliers": {
        "creer": lambda c, h, db, _: c.post("/api/ateliers", json={"num_atelier": 90, "libelle": "Atelier test", "matricule_responsable": "OP005"}, headers=h),
        "lire": lambda c, h, db, _: c.get("/api/ateliers", headers=h),
        "modifier": lambda c, h, db, _: c.put("/api/ateliers/10", json={"libelle": "Atelier transformation", "matricule_responsable": "OP008"}, headers=h),
        "supprimer": lambda c, h, db, _: (
            ajouter(db, models.Atelier(num_atelier=90, libelle="Vide", matricule_responsable="OP005")),
            c.delete("/api/ateliers/90", headers=h),
        )[1],
    },
    "lignes": {
        "creer": lambda c, h, db, _: c.post("/api/lignes", json={"num_ligne": 103, "nb_operateurs_necessaires": 2, "num_atelier": 10}, headers=h),
        "lire": lambda c, h, db, _: c.get("/api/lignes", headers=h),
        "modifier": lambda c, h, db, _: c.put("/api/lignes/101", json={"nb_operateurs_necessaires": 4, "num_atelier": 10}, headers=h),
        "supprimer": lambda c, h, db, _: (
            ajouter(db, models.LigneProduction(num_ligne=109, nb_operateurs_necessaires=1, num_atelier=10)),
            c.delete("/api/lignes/109", headers=h),
        )[1],
    },
    "lots": {
        "creer": lambda c, h, db, _: c.post(
            "/api/lots",
            json={"num_lot": 6001, "date_production": "2026-10-26", "num_ligne": 101, "reference_produit": "PRD-ATT1K", "operateurs": ["OP001", "OP002"]},
            headers=h,
        ),
        "lire": lambda c, h, db, _: c.get("/api/lots", headers=h),
        "modifier": lambda c, h, db, _: c.put(
            "/api/lots/5005",
            json={"date_production": "2026-10-22", "num_ligne": 301, "reference_produit": "PRD-ATT1K", "operateurs": ["OP002"]},
            headers=h,
        ),
        "supprimer": lambda c, h, db, _: c.delete("/api/lots/5005", headers=h),
    },
    "produits": {
        "creer": lambda c, h, db, _: c.post("/api/produits", json={"reference": "PRD-TEST", "designation": "Test", "prix_vente_unitaire": 100, "quantite_stock": 5}, headers=h),
        "lire": lambda c, h, db, _: c.get("/api/produits", headers=h),
        "modifier": lambda c, h, db, _: c.put("/api/produits/PRD-ATT1K", json={"designation": "Attiéké déshydraté 1 kg", "prix_vente_unitaire": 1500, "quantite_stock": 1200}, headers=h),
        "supprimer": lambda c, h, db, _: (
            ajouter(db, models.Produit(reference="PRD-TEST", designation="Test", prix_vente_unitaire=1, quantite_stock=0)),
            c.delete("/api/produits/PRD-TEST", headers=h),
        )[1],
    },
    "operateurs": {
        "creer": lambda c, h, db, _: c.post("/api/operateurs", json={"matricule": "OP900", "nom": "KOFFI", "prenom": "Adjoua", "date_entree": "2026-10-26", "num_equipe": 1}, headers=h),
        "lire": lambda c, h, db, _: c.get("/api/operateurs", headers=h),
        "modifier": lambda c, h, db, _: c.put("/api/operateurs/OP007", json={"nom": "GBAGBO", "prenom": "Ahou Prisca", "date_entree": "2023-05-02", "num_equipe": 1}, headers=h),
        "supprimer": lambda c, h, db, _: (
            ajouter(db, models.Operateur(matricule="OP900", nom="KOFFI", prenom="Adjoua", date_entree=date(2026, 10, 26), num_equipe=1)),
            c.delete("/api/operateurs/OP900", headers=h),
        )[1],
    },
    "equipes": {
        "creer": lambda c, h, db, _: c.post("/api/equipes", json={"num_equipe": 9, "libelle": "Équipe de nuit"}, headers=h),
        "lire": lambda c, h, db, _: c.get("/api/equipes", headers=h),
        "modifier": lambda c, h, db, _: c.put("/api/equipes/1", json={"libelle": "Équipe du matin", "matricule_responsable": "OP002"}, headers=h),
        "supprimer": lambda c, h, db, _: (
            ajouter(db, models.Equipe(num_equipe=9, libelle="Équipe de nuit")),
            c.delete("/api/equipes/9", headers=h),
        )[1],
    },
    "types_incident": {
        "creer": lambda c, h, db, _: c.post("/api/types-incident", json={"code_type": "ELEC", "libelle": "Panne électrique"}, headers=h),
        "lire": lambda c, h, db, _: c.get("/api/types-incident", headers=h),
        "modifier": lambda c, h, db, _: c.put("/api/types-incident/PAN", json={"libelle": "Panne machine"}, headers=h),
        "supprimer": lambda c, h, db, _: (
            ajouter(db, models.TypeIncident(code_type="ELEC", libelle="Panne électrique")),
            c.delete("/api/types-incident/ELEC", headers=h),
        )[1],
    },
    "incidents": {
        "creer": lambda c, h, db, _: c.post("/api/incidents", json={"num_lot": 5002, "code_type": "COU", "temps_arret": 40}, headers=h),
        "lire": lambda c, h, db, _: c.get("/api/incidents", headers=h),
        "modifier": lambda c, h, db, _: c.put(f"/api/incidents/{premier_incident(db)}", json={"num_lot": 5001, "code_type": "PAN", "temps_arret": 45}, headers=h),
        "supprimer": lambda c, h, db, _: c.delete(f"/api/incidents/{premier_incident(db)}", headers=h),
    },
    "machines": {
        "creer": lambda c, h, db, _: c.post("/api/machines", json={"num_machine": 90, "designation": "Étiqueteuse", "num_ligne": 201}, headers=h),
        "lire": lambda c, h, db, _: c.get("/api/machines", headers=h),
        "modifier": lambda c, h, db, _: c.put("/api/machines/4", json={"designation": "Capsuleuse automatique", "num_ligne": 201}, headers=h),
        "supprimer": lambda c, h, db, _: (
            ajouter(db, models.Machine(num_machine=90, designation="Étiqueteuse", num_ligne=201)),
            c.delete("/api/machines/90", headers=h),
        )[1],
    },
    "maintenances": {
        "creer": lambda c, h, db, _: c.post(
            "/api/maintenances",
            json={"num_machine": 4, "date_heure_debut": "2026-10-26T08:00:00", "duree": 60, "operateurs": ["OP005"], "pieces": [{"reference_piece": "PCE-JOIN", "quantite": 2}]},
            headers=h,
        ),
        "lire": lambda c, h, db, _: c.get("/api/maintenances", headers=h),
        "modifier": lambda c, h, db, _: c.put(
            f"/api/maintenances/{maintenance_de_knguessan(db)}",
            json={"num_machine": 1, "date_heure_debut": "2026-10-19T14:00:00", "duree": 75, "operateurs": ["OP005", "OP006"]},
            headers=h,
        ),
        "supprimer": lambda c, h, db, _: c.delete(f"/api/maintenances/{maintenance_de_knguessan(db)}", headers=h),
    },
    "pieces_consommees": {
        "creer": lambda c, h, db, _: c.post(f"/api/maintenances/{maintenance_de_knguessan(db)}/pieces", json={"reference_piece": "PCE-ARBR", "quantite": 1}, headers=h),
        "lire": lambda c, h, db, _: c.get(f"/api/maintenances/{maintenance_de_knguessan(db)}", headers=h),
        "modifier": lambda c, h, db, _: c.put(f"/api/maintenances/{maintenance_de_knguessan(db)}/pieces/PCE-COUR", json={"quantite": 2}, headers=h),
        "supprimer": lambda c, h, db, _: c.delete(f"/api/maintenances/{maintenance_de_knguessan(db)}/pieces/PCE-COUR", headers=h),
    },
    "pieces": {
        "creer": lambda c, h, db, _: c.post("/api/pieces", json={"reference": "PCE-TEST", "libelle": "Pièce test", "prix_unitaire_ht": 1000, "quantite_stock": 3}, headers=h),
        "lire": lambda c, h, db, _: c.get("/api/pieces", headers=h),
        "modifier": lambda c, h, db, _: c.put("/api/pieces/PCE-COUR", json={"libelle": "Courroie de transmission", "prix_unitaire_ht": 12500, "quantite_stock": 15}, headers=h),
        "supprimer": lambda c, h, db, _: (
            ajouter(db, models.Piece(reference="PCE-TEST", libelle="Pièce test", prix_unitaire_ht=1000, quantite_stock=3)),
            c.delete("/api/pieces/PCE-TEST", headers=h),
        )[1],
    },
    "nomenclature": {
        "creer": lambda c, h, db, _: c.post("/api/pieces/PCE-MOTR/composants", json={"reference_composant": "PCE-JOIN", "quantite": 2}, headers=h),
        "lire": lambda c, h, db, _: c.get("/api/pieces/PCE-MOTR/nomenclature", headers=h),
        "modifier": lambda c, h, db, _: c.put("/api/pieces/PCE-MOTR/composants/PCE-ROUL", json={"quantite": 3}, headers=h),
        "supprimer": lambda c, h, db, _: c.delete("/api/pieces/PCE-MOTR/composants/PCE-ROUL", headers=h),
    },
    "achats": {
        "creer": lambda c, h, db, _: c.post(
            "/api/achats",
            json={"reference_piece": "PCE-ROUL", "code_fournisseur": "F001", "date_achat": "2026-10-26", "prix_achat": 3500, "quantite": 20},
            headers=h,
        ),
        "lire": lambda c, h, db, _: c.get("/api/achats", headers=h),
        "modifier": lambda c, h, db, _: c.put("/api/achats/PCE-COUR/F001/2026-09-10", json={"prix_achat": 11800, "quantite": 10}, headers=h),
        "supprimer": lambda c, h, db, _: c.delete("/api/achats/PCE-COUR/F002/2026-10-05", headers=h),
    },
    "fournisseurs": {
        "creer": lambda c, h, db, _: c.post("/api/fournisseurs", json={"code_fournisseur": "F900", "raison_sociale": "Fournisseur test", "telephone": "+225 01 02 03 04"}, headers=h),
        "lire": lambda c, h, db, _: c.get("/api/fournisseurs", headers=h),
        "modifier": lambda c, h, db, _: c.put("/api/fournisseurs/F001", json={"raison_sociale": "Ivoire Pièces Industrielles", "adresse": "Vridi", "telephone": "+225 27 21 00 11 22"}, headers=h),
        "supprimer": lambda c, h, db, _: (
            ajouter(db, models.Fournisseur(code_fournisseur="F900", raison_sociale="Fournisseur test")),
            c.delete("/api/fournisseurs/F900", headers=h),
        )[1],
    },
    "utilisateurs": {
        "creer": lambda c, h, db, _: c.post("/api/utilisateurs", json={"login": "agbagbo", "mot_de_passe": "Provisoire@2026", "role": "OPERATEUR", "matricule": "OP007"}, headers=h),
        "lire": lambda c, h, db, _: c.get("/api/utilisateurs", headers=h),
        "modifier": lambda c, h, db, _: c.put("/api/utilisateurs/knguessan", json={"role": "OPERATEUR", "matricule": "OP005", "actif": True}, headers=h),
        "supprimer": lambda c, h, db, _: c.delete("/api/utilisateurs/knguessan", headers=h),
    },
    "profil": {
        "lire": lambda c, h, db, _: c.get("/api/profil", headers=h),
        "modifier": lambda c, h, db, login: changer_mot_de_passe(c, h, db, login),
    },
}

CAS = [
    pytest.param(ressource, action, role, id=f"{ressource}-{action}-{COMPTES[role]}")
    for ressource, actions in SCENARIOS.items()
    for action in actions
    for role in ROLES
]


def test_chaque_case_de_la_matrice_a_un_scenario():
    for ressource, actions in matrice_attendue().items():
        for action, roles in actions.items():
            if roles:
                assert action in SCENARIOS[ressource], f"Scénario manquant : {ressource} / {action}"


@pytest.mark.matrice
@pytest.mark.parametrize("ressource,action,role", CAS)
def test_matrice(client, entetes, db, ressource, action, role):
    login = COMPTES[role]
    reponse = SCENARIOS[ressource][action](client, entetes(login), db, login)
    if role in matrice_attendue()[ressource][action]:
        assert reponse.status_code in (200, 201, 204), reponse.text
    else:
        assert reponse.status_code == 403, reponse.text
        assert reponse.json()["detail"] == MESSAGE_INTERDIT
