"""Construction des réponses à partir des objets SQLAlchemy et fonctions communes aux routeurs."""
from fastapi import HTTPException, status
from sqlalchemy.orm import Session

from app.config import settings
from app import models


def obtenir_ou_404(db: Session, modele, cle, message: str):
    objet = db.get(modele, cle)
    if objet is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=message)
    return objet


def conflit(message: str) -> HTTPException:
    return HTTPException(status_code=status.HTTP_409_CONFLICT, detail=message)


def requete_invalide(message: str) -> HTTPException:
    return HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=message)


def operateur_court(o: models.Operateur | None) -> dict | None:
    if o is None:
        return None
    return {"matricule": o.matricule, "nom": o.nom, "prenom": o.prenom}


def lot_court(lot: models.LotProduction) -> dict:
    return {
        "num_lot": lot.num_lot,
        "date_production": lot.date_production,
        "reference_produit": lot.reference_produit,
        "designation_produit": lot.produit.designation,
    }


def lot_out(lot: models.LotProduction) -> dict:
    return {
        "num_lot": lot.num_lot,
        "date_production": lot.date_production,
        "num_ligne": lot.num_ligne,
        "num_atelier": lot.ligne.num_atelier,
        "atelier_libelle": lot.ligne.atelier.libelle,
        "reference_produit": lot.reference_produit,
        "designation_produit": lot.produit.designation,
        "operateurs": [operateur_court(o) for o in sorted(lot.operateurs, key=lambda o: o.matricule)],
        "nb_incidents": len(lot.incidents),
        "temps_arret_total": sum(i.temps_arret for i in lot.incidents),
    }


def incident_out(i: models.Incident) -> dict:
    return {
        "num_incident": i.num_incident,
        "temps_arret": i.temps_arret,
        "num_lot": i.num_lot,
        "date_production": i.lot.date_production,
        "num_ligne": i.lot.num_ligne,
        "atelier_libelle": i.lot.ligne.atelier.libelle,
        "designation_produit": i.lot.produit.designation,
        "code_type": i.code_type,
        "type_libelle": i.type_incident.libelle,
    }


def maintenance_courte(m: models.Maintenance) -> dict:
    return {
        "num_maintenance": m.num_maintenance,
        "date_heure_debut": m.date_heure_debut,
        "duree": m.duree,
        "num_machine": m.num_machine,
        "designation_machine": m.machine.designation,
    }


def maintenance_out(m: models.Maintenance) -> dict:
    pieces = [
        {
            "reference_piece": c.reference_piece,
            "libelle": c.piece.libelle,
            "quantite": c.quantite,
            "prix_unitaire_ht": float(c.piece.prix_unitaire_ht),
            "montant": float(c.piece.prix_unitaire_ht) * c.quantite,
        }
        for c in sorted(m.consommations, key=lambda c: c.reference_piece)
    ]
    return {
        **maintenance_courte(m),
        "num_ligne": m.machine.num_ligne,
        "operateurs": [operateur_court(o) for o in sorted(m.operateurs, key=lambda o: o.matricule)],
        "pieces": pieces,
        "cout_pieces": sum(p["montant"] for p in pieces),
    }


def piece_out(p: models.Piece, nb_composants: int = 0) -> dict:
    return {
        "reference": p.reference,
        "libelle": p.libelle,
        "prix_unitaire_ht": float(p.prix_unitaire_ht),
        "quantite_stock": p.quantite_stock,
        "stock_faible": p.quantite_stock <= settings.seuil_stock_faible,
        "nb_composants": nb_composants,
    }


def achat_out(a: models.Achat) -> dict:
    return {
        "reference_piece": a.reference_piece,
        "libelle_piece": a.piece.libelle,
        "code_fournisseur": a.code_fournisseur,
        "raison_sociale": a.fournisseur.raison_sociale,
        "date_achat": a.date_achat,
        "prix_achat": float(a.prix_achat),
        "quantite": a.quantite,
        "montant": float(a.prix_achat) * a.quantite,
    }


def charger_operateurs(db: Session, matricules: list[str]) -> list[models.Operateur]:
    """Retourne les opérateurs demandés, ou lève 404 en citant les matricules inconnus."""
    trouves = db.query(models.Operateur).filter(models.Operateur.matricule.in_(matricules)).all()
    inconnus = sorted(set(matricules) - {o.matricule for o in trouves})
    if inconnus:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Opérateur(s) introuvable(s) : {', '.join(inconnus)}.",
        )
    return trouves


def machine_out(m: models.Machine) -> dict:
    return {
        "num_machine": m.num_machine,
        "designation": m.designation,
        "num_ligne": m.num_ligne,
        "atelier_libelle": m.ligne.atelier.libelle,
        "nb_maintenances": len(m.maintenances),
        "derniere_maintenance": max((x.date_heure_debut for x in m.maintenances), default=None),
    }


def utilisateur_out(u: models.Utilisateur) -> dict:
    return {
        "login": u.login,
        "role": u.role,
        "matricule": u.matricule,
        "nom_complet": u.operateur.nom_complet if u.operateur else None,
        "equipe_libelle": u.operateur.equipe.libelle if u.operateur else None,
        "actif": u.actif,
    }


def piece_verrouillee(db: Session, reference: str) -> models.Piece:
    """Charge une pièce en verrouillant sa ligne (SELECT ... FOR UPDATE) avant de modifier son stock."""
    piece = db.get(models.Piece, reference, with_for_update=True)
    if piece is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Pièce {reference} introuvable.")
    return piece


def stock_insuffisant(piece: models.Piece, demande: int) -> HTTPException:
    return conflit(
        f"Stock insuffisant pour cette pièce. {piece.libelle} ({piece.reference}) : "
        f"{piece.quantite_stock} en stock, {demande} demandé(s)."
    )
