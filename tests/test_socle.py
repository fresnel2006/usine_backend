"""Sprint 2 : authentification, droits par rôle, ateliers, lignes et produits."""


def test_connexion_refusee_avec_mauvais_mot_de_passe(client):
    r = client.post("/api/auth/login", json={"login": "admin", "mot_de_passe": "mauvais"})
    assert r.status_code == 401
    assert r.json()["detail"] == "Identifiant ou mot de passe incorrect."


def test_route_protegee_sans_jeton(client):
    assert client.get("/api/ateliers").status_code == 401


def test_collaborateur_ne_peut_pas_creer_un_atelier(client, entetes):
    r = client.post(
        "/api/ateliers",
        json={"num_atelier": 90, "libelle": "Test", "matricule_responsable": "OP005"},
        headers=entetes("mbamba"),
    )
    assert r.status_code == 403


def test_un_operateur_ne_dirige_qu_un_seul_atelier(client, entetes):
    # OP001 est déjà responsable de l'atelier 20
    r = client.post(
        "/api/ateliers",
        json={"num_atelier": 90, "libelle": "Test", "matricule_responsable": "OP001"},
        headers=entetes("itoure"),
    )
    assert r.status_code == 409
    assert "déjà responsable" in r.json()["detail"]


def test_numero_atelier_en_doublon(client, entetes):
    r = client.post(
        "/api/ateliers",
        json={"num_atelier": 10, "libelle": "Doublon", "matricule_responsable": "OP005"},
        headers=entetes("itoure"),
    )
    assert r.status_code == 409


def test_suppression_refusee_si_l_atelier_a_des_lignes(client, entetes):
    r = client.delete("/api/ateliers/10", headers=entetes("admin"))
    assert r.status_code == 409
    assert "ligne" in r.json()["detail"]


def test_creation_puis_suppression_d_un_atelier_vide(client, entetes):
    h = entetes("itoure")
    corps = {"num_atelier": 90, "libelle": "Atelier test", "matricule_responsable": "OP005"}
    assert client.post("/api/ateliers", json=corps, headers=h).status_code == 201
    assert client.delete("/api/ateliers/90", headers=h).status_code == 204
    assert client.get("/api/ateliers/90", headers=h).status_code == 404


def test_prix_de_produit_negatif_refuse(client, entetes):
    r = client.post(
        "/api/produits",
        json={"reference": "PRD-X", "designation": "X", "prix_vente_unitaire": -5, "quantite_stock": 1},
        headers=entetes("itoure"),
    )
    assert r.status_code == 422
    assert r.json()["erreurs"][0]["champ"] == "prix_vente_unitaire"
