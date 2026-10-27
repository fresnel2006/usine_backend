"""Parcours de la section 7 (un par rôle) et règles sur les comptes, la connexion et le stock."""
from datetime import datetime, timedelta, timezone

from sqlalchemy import select

from app import models
from app.security import MESSAGE_INTERDIT, hacher_mot_de_passe


def stock(db, reference: str) -> int:
    db.expire_all()
    return db.get(models.Piece, reference).quantite_stock


def temps_arret_atelier(client, h, libelle: str) -> int:
    stats = client.get("/api/incidents/statistiques", headers=h).json()
    return next(s["temps_arret_total"] for s in stats["par_atelier"] if s["libelle"] == libelle)


# ---------------------------------------------------------------------
# 1. Responsable atelier (itoure)
# ---------------------------------------------------------------------
def test_parcours_responsable_atelier(client, entetes):
    h = entetes("itoure")
    r = client.post("/api/lignes", json={"num_ligne": 103, "nb_operateurs_necessaires": 3, "num_atelier": 10}, headers=h)
    assert r.status_code == 201
    assert r.json()["atelier_libelle"] == "Atelier transformation"

    r = client.post(
        "/api/lots",
        json={"num_lot": 6001, "date_production": "2026-10-26", "num_ligne": 103, "reference_produit": "PRD-ATT1K", "operateurs": ["OP001", "OP007"]},
        headers=h,
    )
    assert r.status_code == 201
    assert len(r.json()["operateurs"]) == 2

    # Pas de bouton côté interface, et 403 si la requête est forcée
    r = client.delete("/api/fournisseurs/F003", headers=h)
    assert r.status_code == 403
    assert r.json()["detail"] == MESSAGE_INTERDIT


def test_un_lot_a_au_moins_un_operateur(client, entetes):
    r = client.post(
        "/api/lots",
        json={"num_lot": 6002, "date_production": "2026-10-26", "num_ligne": 101, "reference_produit": "PRD-ATT1K", "operateurs": []},
        headers=entetes("itoure"),
    )
    assert r.status_code == 422


# ---------------------------------------------------------------------
# 2. Collaborateur responsable (mbamba)
# ---------------------------------------------------------------------
def test_parcours_collaborateur_responsable(client, entetes):
    h = entetes("mbamba")
    r = client.post(
        "/api/operateurs",
        json={"matricule": "OP009", "nom": "YAO", "prenom": "Affoué", "date_entree": "2026-10-26", "num_equipe": 1},
        headers=h,
    )
    assert r.status_code == 201
    assert r.json()["equipe_libelle"] == "Équipe du matin"

    avant = temps_arret_atelier(client, h, "Atelier embouteillage")
    r = client.post("/api/incidents", json={"num_lot": 5002, "code_type": "COU", "temps_arret": 40}, headers=h)
    assert r.status_code == 201
    assert temps_arret_atelier(client, h, "Atelier embouteillage") == avant + 40


def test_temps_d_arret_strictement_positif(client, entetes):
    r = client.post("/api/incidents", json={"num_lot": 5002, "code_type": "COU", "temps_arret": 0}, headers=entetes("mbamba"))
    assert r.status_code == 422


def test_suppression_d_equipe_refusee_si_elle_a_des_operateurs(client, entetes):
    r = client.delete("/api/equipes/1", headers=entetes("mbamba"))
    assert r.status_code == 409


def test_suppression_d_un_responsable_refusee(client, entetes):
    r = client.delete("/api/operateurs/OP008", headers=entetes("mbamba"))
    assert r.status_code == 409
    assert "responsable" in r.json()["detail"]


# ---------------------------------------------------------------------
# 3. Opérateur (knguessan)
# ---------------------------------------------------------------------
def test_parcours_operateur(client, entetes, db):
    h = entetes("knguessan")
    joints = stock(db, "PCE-JOIN")
    r = client.post(
        "/api/maintenances",
        json={
            "num_machine": 4,
            "date_heure_debut": "2026-10-26T09:00:00",
            "duree": 60,
            "operateurs": ["OP005"],
            "pieces": [{"reference_piece": "PCE-JOIN", "quantite": 2}],
        },
        headers=h,
    )
    assert r.status_code == 201
    assert r.json()["designation_machine"] == "Capsuleuse automatique"
    assert stock(db, "PCE-JOIN") == joints - 2

    num = r.json()["num_maintenance"]
    r = client.post(f"/api/maintenances/{num}/pieces", json={"reference_piece": "PCE-ROUL", "quantite": 500}, headers=h)
    assert r.status_code == 409
    assert r.json()["detail"].startswith("Stock insuffisant pour cette pièce.")

    roulements = stock(db, "PCE-ROUL")
    r = client.post(
        "/api/achats",
        json={"reference_piece": "PCE-ROUL", "code_fournisseur": "F001", "date_achat": "2026-10-26", "prix_achat": 3400, "quantite": 20},
        headers=h,
    )
    assert r.status_code == 201
    assert r.json()["raison_sociale"] == "Ivoire Pièces Industrielles"
    assert stock(db, "PCE-ROUL") == roulements + 20


def test_maintenance_refusee_si_stock_insuffisant_sans_rien_modifier(client, entetes, db):
    joints = stock(db, "PCE-JOIN")
    r = client.post(
        "/api/maintenances",
        json={
            "num_machine": 4,
            "date_heure_debut": "2026-10-26T09:00:00",
            "duree": 30,
            "operateurs": ["OP005"],
            "pieces": [{"reference_piece": "PCE-JOIN", "quantite": 500}],
        },
        headers=entetes("knguessan"),
    )
    assert r.status_code == 409
    assert stock(db, "PCE-JOIN") == joints


def test_operateur_ne_modifie_que_ses_maintenances(client, entetes, db):
    # Maintenance du 22/10/2026 sur la capsuleuse : effectuée par OP006 seulement
    num = db.scalar(select(models.Maintenance.num_maintenance).where(models.Maintenance.num_machine == 4))
    r = client.put(
        f"/api/maintenances/{num}",
        json={"num_machine": 4, "date_heure_debut": "2026-10-22T10:00:00", "duree": 50, "operateurs": ["OP006"]},
        headers=entetes("knguessan"),
    )
    assert r.status_code == 403
    assert r.json()["detail"].startswith(MESSAGE_INTERDIT)
    # Le collaborateur responsable peut modifier toutes les maintenances
    r = client.put(
        f"/api/maintenances/{num}",
        json={"num_machine": 4, "date_heure_debut": "2026-10-22T10:00:00", "duree": 50, "operateurs": ["OP006"]},
        headers=entetes("mbamba"),
    )
    assert r.status_code == 200


def test_operateur_declare_mais_ne_modifie_pas_un_incident(client, entetes):
    h = entetes("knguessan")
    r = client.post("/api/incidents", json={"num_lot": 5004, "code_type": "QUA", "temps_arret": 15}, headers=h)
    assert r.status_code == 201
    num = r.json()["num_incident"]
    assert client.put(f"/api/incidents/{num}", json={"num_lot": 5004, "code_type": "QUA", "temps_arret": 10}, headers=h).status_code == 403
    assert client.delete(f"/api/incidents/{num}", headers=h).status_code == 403


def test_une_piece_ne_se_compose_pas_d_elle_meme(client, entetes):
    r = client.post("/api/pieces/PCE-MOTR/composants", json={"reference_composant": "PCE-MOTR", "quantite": 1}, headers=entetes("knguessan"))
    assert r.status_code == 400


def test_nomenclature_sans_boucle(client, entetes):
    # PCE-MOTR contient PCE-ROUL : PCE-ROUL ne peut pas contenir PCE-MOTR
    r = client.post("/api/pieces/PCE-ROUL/composants", json={"reference_composant": "PCE-MOTR", "quantite": 1}, headers=entetes("knguessan"))
    assert r.status_code == 409


# ---------------------------------------------------------------------
# 4. Administrateur (admin)
# ---------------------------------------------------------------------
def test_parcours_administrateur(client, entetes):
    h = entetes("admin")
    r = client.post(
        "/api/utilisateurs",
        json={"login": "agbagbo", "mot_de_passe": "Provisoire@2026", "role": "OPERATEUR", "matricule": "OP007"},
        headers=h,
    )
    assert r.status_code == 201
    assert r.json()["nom_complet"] == "GBAGBO Ahou Prisca"

    r = client.post("/api/utilisateurs/agbagbo/desactiver", headers=h)
    assert r.status_code == 200
    assert r.json()["actif"] is False
    r = client.post("/api/auth/login", json={"login": "agbagbo", "mot_de_passe": "Provisoire@2026"})
    assert r.status_code == 403
    assert r.json()["detail"] == "Ce compte est désactivé. Contactez l'administrateur."

    r = client.post(
        "/api/fournisseurs",
        json={"code_fournisseur": "F004", "raison_sociale": "Abidjan Roulements", "telephone": "+225 27 20 00 00 00"},
        headers=h,
    )
    assert r.status_code == 201

    r = client.post("/api/utilisateurs/admin/desactiver", headers=h)
    assert r.status_code == 403
    assert r.json()["detail"] == "Vous ne pouvez pas désactiver votre propre compte."


def test_l_administrateur_ne_supprime_pas_son_compte_ni_son_role(client, entetes):
    h = entetes("admin")
    assert client.delete("/api/utilisateurs/admin", headers=h).status_code == 403
    r = client.put("/api/utilisateurs/admin", json={"role": "OPERATEUR", "matricule": "OP007", "actif": True}, headers=h)
    assert r.status_code == 403


def test_il_reste_toujours_un_administrateur_actif(db):
    """Par l'API, les règles sur son propre compte suffisent déjà ; la vérification reste en filet de sécurité."""
    import pytest
    from fastapi import HTTPException

    from app.routers.utilisateurs import verifier_admin_restant

    for u in db.scalars(select(models.Utilisateur).where(models.Utilisateur.role == "ADMINISTRATEUR")):
        u.actif = u.login == "admin"
    db.flush()
    with pytest.raises(HTTPException) as erreur:
        verifier_admin_restant(db, db.get(models.Utilisateur, "admin"))
    assert erreur.value.status_code == 409
    assert "au moins un Administrateur actif" in erreur.value.detail


def test_un_administrateur_peut_desactiver_un_autre_administrateur(client, entetes, db):
    db.add(models.Utilisateur(login="admin2", mot_de_passe=hacher_mot_de_passe("Admin2@2026"), role="ADMINISTRATEUR"))
    db.flush()
    assert client.post("/api/utilisateurs/admin2/desactiver", headers=entetes("admin")).status_code == 200
    assert client.post("/api/utilisateurs/admin2/reactiver", headers=entetes("admin")).status_code == 200


def test_un_compte_non_administrateur_est_lie_a_un_operateur(client, entetes):
    r = client.post(
        "/api/utilisateurs",
        json={"login": "sansfiche", "mot_de_passe": "Provisoire@2026", "role": "OPERATEUR"},
        headers=entetes("admin"),
    )
    assert r.status_code == 400


def test_mot_de_passe_de_8_caracteres_minimum(client, entetes):
    r = client.post(
        "/api/utilisateurs",
        json={"login": "agbagbo", "mot_de_passe": "court", "role": "OPERATEUR", "matricule": "OP007"},
        headers=entetes("admin"),
    )
    assert r.status_code == 422


# ---------------------------------------------------------------------
# Connexion, jeton et profil
# ---------------------------------------------------------------------
def test_blocage_apres_cinq_echecs(client, db):
    db.get(models.Utilisateur, "knguessan").mot_de_passe = hacher_mot_de_passe("Operateur@2026")
    db.flush()
    for _ in range(5):
        r = client.post("/api/auth/login", json={"login": "knguessan", "mot_de_passe": "mauvais"})
        assert r.status_code == 401
    r = client.post("/api/auth/login", json={"login": "knguessan", "mot_de_passe": "Operateur@2026"})
    assert r.status_code == 429
    assert r.json()["detail"] == "Trop de tentatives, réessayez dans 5 minutes."


def test_le_jeton_contient_le_role_et_le_matricule(client, db):
    import jwt

    from app.config import settings

    db.get(models.Utilisateur, "mbamba").mot_de_passe = hacher_mot_de_passe("Equipe@2026")
    db.flush()
    r = client.post("/api/auth/login", json={"login": "mbamba", "mot_de_passe": "Equipe@2026"})
    assert r.status_code == 200
    charge = jwt.decode(r.json()["access_token"], settings.jwt_secret, algorithms=[settings.jwt_algorithm])
    assert charge["role"] == "COLLABORATEUR_RESPONSABLE"
    assert charge["matricule"] == "OP002"
    restant = datetime.fromtimestamp(charge["exp"], timezone.utc) - datetime.now(timezone.utc)
    assert timedelta(hours=7, minutes=59) < restant <= timedelta(hours=8)


def test_profil_du_responsable_d_atelier(client, entetes):
    r = client.get("/api/profil", headers=entetes("itoure"))
    assert r.status_code == 200
    profil = r.json()
    assert profil["nom"] == "TOURE"
    assert profil["atelier_responsable"] == {"numero": 10, "libelle": "Atelier transformation"}


def test_changement_de_mot_de_passe_avec_mauvais_ancien(client, entetes):
    corps = {"ancien_mot_de_passe": "faux", "nouveau_mot_de_passe": "Nouveau@2026", "confirmation": "Nouveau@2026"}
    r = client.put("/api/profil/mot-de-passe", json=corps, headers=entetes("knguessan"))
    assert r.status_code == 400


# ---------------------------------------------------------------------
# Tableau de bord selon le rôle
# ---------------------------------------------------------------------
def test_tableau_de_bord_selon_le_role(client, entetes):
    admin = client.get("/api/dashboard", headers=entetes("admin")).json()
    assert admin["role"] == "ADMINISTRATEUR"
    assert len(admin["comptes_par_role"]) == 4
    assert admin["indicateurs"][1]["valeur"] >= 3  # fournisseurs

    atelier = client.get("/api/dashboard", headers=entetes("itoure")).json()
    assert atelier["atelier"]["numero"] == 10
    assert [p["libelle"] for p in atelier["graphique"]] == ["Ligne 101", "Ligne 102"]

    equipe = client.get("/api/dashboard", headers=entetes("mbamba")).json()
    assert equipe["equipe"]["libelle"] == "Équipe du matin"
    assert sum(p["valeur"] for p in equipe["graphique"]) == equipe["indicateurs"][2]["valeur"]

    operateur = client.get("/api/dashboard", headers=entetes("knguessan")).json()
    assert operateur["indicateurs"][0]["valeur"] >= 2  # maintenances 1 et 2
    assert {m["num_machine"] for m in operateur["machines"]} >= {1, 3, 4}
    assert all(p["quantite_stock"] <= 5 for p in operateur["pieces_stock_faible"])
