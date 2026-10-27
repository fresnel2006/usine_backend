from fastapi import APIRouter, Depends, status
from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app import models
from app.database import get_db
from app.schemas import IncidentIn, IncidentOut, IncidentStats
from app.security import CREER, MODIFIER, SUPPRIMER, autoriser, get_current_user
from app.serializers import incident_out, obtenir_ou_404

router = APIRouter(prefix="/api/incidents", tags=["Incidents"])

CHARGEMENT_INCIDENT = (
    selectinload(models.Incident.type_incident),
    selectinload(models.Incident.lot).selectinload(models.LotProduction.produit),
    selectinload(models.Incident.lot).selectinload(models.LotProduction.ligne).selectinload(models.LigneProduction.atelier),
)


def charger_incidents(db: Session, type_: str | None = None, atelier: int | None = None, lot: int | None = None):
    requete = select(models.Incident).options(*CHARGEMENT_INCIDENT)
    if type_:
        requete = requete.where(models.Incident.code_type == type_.upper())
    if lot is not None:
        requete = requete.where(models.Incident.num_lot == lot)
    if atelier is not None:
        requete = (
            requete.join(models.LotProduction, models.LotProduction.num_lot == models.Incident.num_lot)
            .join(models.LigneProduction, models.LigneProduction.num_ligne == models.LotProduction.num_ligne)
            .where(models.LigneProduction.num_atelier == atelier)
        )
    return db.scalars(requete.order_by(models.Incident.num_incident.desc())).all()


def verifier_references(db: Session, donnees: IncidentIn) -> None:
    obtenir_ou_404(db, models.LotProduction, donnees.num_lot, f"Lot {donnees.num_lot} introuvable.")
    obtenir_ou_404(db, models.TypeIncident, donnees.code_type, f"Type d'incident {donnees.code_type} introuvable.")


@router.get("", response_model=list[IncidentOut], summary="Liste des incidents (filtres : type, atelier, lot)")
def lister(
    type: str | None = None,
    atelier: int | None = None,
    lot: int | None = None,
    db: Session = Depends(get_db),
    _=Depends(get_current_user),
):
    return [incident_out(i) for i in charger_incidents(db, type, atelier, lot)]


@router.get("/statistiques", response_model=IncidentStats, summary="Temps d'arrêt totaux par lot, ligne et atelier")
def statistiques(db: Session = Depends(get_db), _=Depends(get_current_user)):
    groupes: dict[str, dict[str, dict]] = {"par_lot": {}, "par_ligne": {}, "par_atelier": {}}
    incidents = charger_incidents(db)
    for i in incidents:
        lot = i.lot
        cles = {
            "par_lot": (str(lot.num_lot), f"Lot {lot.num_lot} - {lot.produit.designation}"),
            "par_ligne": (str(lot.num_ligne), f"Ligne {lot.num_ligne} - {lot.ligne.atelier.libelle}"),
            "par_atelier": (str(lot.ligne.num_atelier), lot.ligne.atelier.libelle),
        }
        for groupe, (cle, libelle) in cles.items():
            stat = groupes[groupe].setdefault(cle, {"cle": cle, "libelle": libelle, "nb_incidents": 0, "temps_arret_total": 0})
            stat["nb_incidents"] += 1
            stat["temps_arret_total"] += i.temps_arret
    return {
        **{g: sorted(v.values(), key=lambda s: -s["temps_arret_total"]) for g, v in groupes.items()},
        "total_minutes": sum(i.temps_arret for i in incidents),
    }


@router.get("/{num_incident}", response_model=IncidentOut, summary="Détail d'un incident")
def detail(num_incident: int, db: Session = Depends(get_db), _=Depends(get_current_user)):
    return incident_out(obtenir_ou_404(db, models.Incident, num_incident, "Incident introuvable."))


@router.post("", response_model=IncidentOut, status_code=status.HTTP_201_CREATED, summary="Déclarer un incident")
def creer(donnees: IncidentIn, db: Session = Depends(get_db), _=Depends(autoriser("incidents", CREER))):
    verifier_references(db, donnees)
    incident = models.Incident(**donnees.model_dump())
    db.add(incident)
    db.commit()
    db.refresh(incident)
    return incident_out(incident)


@router.put("/{num_incident}", response_model=IncidentOut, summary="Modifier un incident")
def modifier(
    num_incident: int,
    donnees: IncidentIn,
    db: Session = Depends(get_db),
    _=Depends(autoriser("incidents", MODIFIER)),
):
    incident = obtenir_ou_404(db, models.Incident, num_incident, "Incident introuvable.")
    verifier_references(db, donnees)
    for champ, valeur in donnees.model_dump().items():
        setattr(incident, champ, valeur)
    db.commit()
    db.refresh(incident)
    return incident_out(incident)


@router.delete("/{num_incident}", status_code=status.HTTP_204_NO_CONTENT, summary="Supprimer un incident")
def supprimer(num_incident: int, db: Session = Depends(get_db), _=Depends(autoriser("incidents", SUPPRIMER))):
    incident = obtenir_ou_404(db, models.Incident, num_incident, "Incident introuvable.")
    db.delete(incident)
    db.commit()
