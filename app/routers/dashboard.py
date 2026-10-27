"""Tableau de bord : un contenu différent pour chaque rôle (section 5 du document des droits)."""
from collections import Counter
from datetime import date, timedelta

from fastapi import APIRouter, Depends
from sqlalchemy import func, select
from sqlalchemy.orm import Session, selectinload

from app import models
from app.config import settings
from app.database import get_db
from app.schemas import Dashboard
from app.security import ADMIN, COLLAB_RESP, RESP_ATELIER, ROLES, get_current_user
from app.serializers import machine_out, operateur_court, piece_out, utilisateur_out

router = APIRouter(prefix="/api/dashboard", tags=["Tableau de bord"])


def _compter(db: Session, modele) -> int:
    return db.scalar(select(func.count()).select_from(modele))


def _pieces_stock_faible(db: Session) -> list[models.Piece]:
    return db.scalars(
        select(models.Piece)
        .where(models.Piece.quantite_stock <= settings.seuil_stock_faible)
        .order_by(models.Piece.quantite_stock, models.Piece.reference)
    ).all()


def _lots(db: Session, debut: date | None = None, lignes: list[int] | None = None) -> list[models.LotProduction]:
    requete = select(models.LotProduction).options(
        selectinload(models.LotProduction.produit),
        selectinload(models.LotProduction.ligne).selectinload(models.LigneProduction.atelier),
        selectinload(models.LotProduction.incidents),
    )
    if debut:
        requete = requete.where(models.LotProduction.date_production >= debut)
    if lignes is not None:
        requete = requete.where(models.LotProduction.num_ligne.in_(lignes))
    return db.scalars(
        requete.order_by(models.LotProduction.date_production.desc(), models.LotProduction.num_lot.desc())
    ).all()


def _activite_lot(lot: models.LotProduction) -> dict:
    return {
        "date": lot.date_production,
        "titre": f"Lot {lot.num_lot} - {lot.produit.designation}",
        "detail": f"Ligne {lot.num_ligne}, {lot.ligne.atelier.libelle}",
        "lien": f"/lots/{lot.num_lot}",
    }


def pour_administrateur(db: Session, debut: date) -> dict:
    comptes = db.scalars(
        select(models.Utilisateur).options(
            selectinload(models.Utilisateur.operateur).selectinload(models.Operateur.equipe)
        )
    ).all()
    actifs = Counter(u.role for u in comptes if u.actif)
    desactives = Counter(u.role for u in comptes if not u.actif)
    arrets = db.execute(
        select(models.Atelier.libelle, func.coalesce(func.sum(models.Incident.temps_arret), 0))
        .select_from(models.Atelier)
        .outerjoin(models.LigneProduction, models.LigneProduction.num_atelier == models.Atelier.num_atelier)
        .outerjoin(models.LotProduction, models.LotProduction.num_ligne == models.LigneProduction.num_ligne)
        .outerjoin(models.Incident, models.Incident.num_lot == models.LotProduction.num_lot)
        .group_by(models.Atelier.num_atelier, models.Atelier.libelle)
        .order_by(models.Atelier.num_atelier)
    ).all()
    pieces = _pieces_stock_faible(db)
    lots_semaine = _lots(db, debut)
    return {
        "indicateurs": [
            {"libelle": "Comptes actifs", "valeur": sum(actifs.values()), "detail": f"{sum(desactives.values())} désactivé(s)"},
            {"libelle": "Fournisseurs", "valeur": _compter(db, models.Fournisseur), "detail": "Seul l'Administrateur les gère"},
            {"libelle": "Lots des 7 derniers jours", "valeur": len(lots_semaine), "detail": "Toutes lignes confondues"},
            {
                "libelle": "Temps d'arrêt total (min)",
                "valeur": sum(int(total) for _, total in arrets),
                "detail": f"{len(pieces)} pièce(s) en stock faible",
            },
        ],
        "titre_graphique": "Temps d'arrêt par atelier",
        "unite_graphique": "min",
        "graphique": [{"libelle": libelle, "valeur": int(total)} for libelle, total in arrets],
        "titre_activite": "Lots récents",
        "activite": [_activite_lot(lot) for lot in _lots(db)[:5]],
        "comptes_par_role": [
            {"role": role, "actifs": actifs.get(role, 0), "desactives": desactives.get(role, 0)} for role in ROLES
        ],
        "comptes": [utilisateur_out(u) for u in sorted(comptes, key=lambda u: u.login)],
        "pieces_stock_faible": [piece_out(p) for p in pieces],
    }


def pour_responsable_atelier(db: Session, utilisateur: models.Utilisateur, debut: date) -> dict:
    atelier = db.scalar(select(models.Atelier).where(models.Atelier.matricule_responsable == utilisateur.matricule))
    lignes = (
        db.scalars(
            select(models.LigneProduction)
            .where(models.LigneProduction.num_atelier == atelier.num_atelier)
            .order_by(models.LigneProduction.num_ligne)
        ).all()
        if atelier
        else []
    )
    numeros = [l.num_ligne for l in lignes]
    tous_lots = _lots(db, lignes=numeros)
    lots_semaine = [lot for lot in tous_lots if lot.date_production >= debut]
    par_ligne = Counter(lot.num_ligne for lot in lots_semaine)
    par_produit = Counter(lot.produit.designation for lot in tous_lots)
    return {
        "atelier": {"numero": atelier.num_atelier, "libelle": atelier.libelle} if atelier else None,
        "indicateurs": [
            {"libelle": "Lots des 7 derniers jours", "valeur": len(lots_semaine), "detail": "Dans mon atelier"},
            {"libelle": "Lignes de production", "valeur": len(lignes), "detail": atelier.libelle if atelier else None},
            {
                "libelle": "Temps d'arrêt de mon atelier (min)",
                "valeur": sum(i.temps_arret for lot in tous_lots for i in lot.incidents),
                "detail": f"{sum(len(lot.incidents) for lot in tous_lots)} incident(s)",
            },
            {"libelle": "Produits au catalogue", "valeur": _compter(db, models.Produit), "detail": f"{len(par_produit)} fabriqué(s) dans l'atelier"},
        ],
        "titre_graphique": "Lots des 7 derniers jours par ligne",
        "unite_graphique": "lots",
        "graphique": [{"libelle": f"Ligne {n}", "valeur": par_ligne.get(n, 0)} for n in numeros],
        "production_par_produit": [{"libelle": nom, "valeur": nb} for nom, nb in par_produit.most_common()],
        "titre_activite": "Derniers lots de mon atelier",
        "activite": [_activite_lot(lot) for lot in tous_lots[:5]],
    }


def pour_collaborateur(db: Session, utilisateur: models.Utilisateur, debut: date) -> dict:
    equipe = db.scalar(select(models.Equipe).where(models.Equipe.matricule_responsable == utilisateur.matricule))
    if equipe is None and utilisateur.operateur is not None:
        equipe = utilisateur.operateur.equipe
    membres = sorted(equipe.operateurs, key=lambda o: (o.nom, o.prenom)) if equipe else []
    incidents = db.scalars(
        select(models.Incident)
        .options(
            selectinload(models.Incident.type_incident),
            selectinload(models.Incident.lot).selectinload(models.LotProduction.produit),
        )
        .order_by(models.Incident.num_incident.desc())
    ).all()
    par_type: Counter = Counter()
    for i in incidents:
        par_type[i.type_incident.libelle] += i.temps_arret
    return {
        "equipe": {"numero": equipe.num_equipe, "libelle": equipe.libelle} if equipe else None,
        "membres_equipe": [operateur_court(o) for o in membres],
        "indicateurs": [
            {"libelle": "Membres de mon équipe", "valeur": len(membres), "detail": equipe.libelle if equipe else None},
            {
                "libelle": "Incidents des 7 derniers jours",
                "valeur": sum(1 for i in incidents if i.lot.date_production >= debut),
                "detail": "Selon la date du lot",
            },
            {"libelle": "Temps d'arrêt total (min)", "valeur": sum(i.temps_arret for i in incidents), "detail": f"{len(incidents)} incident(s) au total"},
            {"libelle": "Opérateurs de l'usine", "valeur": _compter(db, models.Operateur), "detail": f"{_compter(db, models.Equipe)} équipe(s)"},
        ],
        "titre_graphique": "Temps d'arrêt par type d'incident",
        "unite_graphique": "min",
        "graphique": [{"libelle": nom, "valeur": total} for nom, total in par_type.most_common()],
        "titre_activite": "Incidents récents",
        "activite": [
            {
                "date": i.lot.date_production,
                "titre": f"{i.type_incident.libelle} - {i.temps_arret} min",
                "detail": f"Lot {i.num_lot}, {i.lot.produit.designation}",
                "lien": f"/incidents/{i.num_incident}",
            }
            for i in incidents[:5]
        ],
    }


def pour_operateur(db: Session, utilisateur: models.Utilisateur) -> dict:
    operateur = utilisateur.operateur
    maintenances = (
        sorted(operateur.maintenances, key=lambda m: m.date_heure_debut, reverse=True) if operateur else []
    )
    # « Sa ligne » : les lignes des lots qu'il a produits et des machines qu'il a entretenues
    lignes = sorted(
        {lot.num_ligne for lot in (operateur.lots if operateur else [])} | {m.machine.num_ligne for m in maintenances}
    )
    machines = db.scalars(
        select(models.Machine)
        .options(
            selectinload(models.Machine.ligne).selectinload(models.LigneProduction.atelier),
            selectinload(models.Machine.maintenances),
        )
        .where(models.Machine.num_ligne.in_(lignes))
        .order_by(models.Machine.num_machine)
    ).all()
    pieces = _pieces_stock_faible(db)
    toutes_pieces = db.scalars(select(models.Piece).order_by(models.Piece.quantite_stock)).all()
    return {
        "indicateurs": [
            {"libelle": "Mes maintenances", "valeur": len(maintenances), "detail": "Effectuées par moi"},
            {"libelle": "Temps de maintenance (min)", "valeur": sum(m.duree for m in maintenances), "detail": "Cumul de mes interventions"},
            {"libelle": "Pièces en stock faible", "valeur": len(pieces), "detail": f"{settings.seuil_stock_faible} unités ou moins"},
            {"libelle": "Machines de ma ligne", "valeur": len(machines), "detail": ", ".join(f"Ligne {n}" for n in lignes) or None},
        ],
        "titre_graphique": "Stock des pièces",
        "unite_graphique": "unités",
        "graphique": [{"libelle": p.reference, "valeur": p.quantite_stock} for p in toutes_pieces],
        "titre_activite": "Mes dernières maintenances",
        "activite": [
            {
                "date": m.date_heure_debut,
                "titre": f"Maintenance {m.num_maintenance} - {m.machine.designation}",
                "detail": f"{m.duree} min, {len(m.consommations)} pièce(s) consommée(s)",
                "lien": f"/maintenances/{m.num_maintenance}",
            }
            for m in maintenances[:5]
        ],
        "pieces_stock_faible": [piece_out(p) for p in pieces],
        "machines": [machine_out(m) for m in machines],
    }


@router.get("", response_model=Dashboard, summary="Tableau de bord adapté au rôle de l'utilisateur connecté")
def tableau_de_bord(db: Session = Depends(get_db), utilisateur: models.Utilisateur = Depends(get_current_user)):
    fin = date.today()
    debut = fin - timedelta(days=6)  # les 7 derniers jours, aujourd'hui compris
    if utilisateur.role == ADMIN:
        contenu = pour_administrateur(db, debut)
    elif utilisateur.role == RESP_ATELIER:
        contenu = pour_responsable_atelier(db, utilisateur, debut)
    elif utilisateur.role == COLLAB_RESP:
        contenu = pour_collaborateur(db, utilisateur, debut)
    else:
        contenu = pour_operateur(db, utilisateur)
    return {
        "role": utilisateur.role,
        "periode_debut": debut,
        "periode_fin": fin,
        "seuil_stock_faible": settings.seuil_stock_faible,
        **contenu,
    }
