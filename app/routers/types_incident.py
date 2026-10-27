from fastapi import APIRouter, Depends, status
from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app import models
from app.database import get_db
from app.schemas import TypeIncidentIn, TypeIncidentOut, TypeIncidentUpdate
from app.security import CREER, MODIFIER, SUPPRIMER, autoriser, get_current_user
from app.serializers import conflit, obtenir_ou_404

router = APIRouter(prefix="/api/types-incident", tags=["Types d'incident"])


def type_out(t: models.TypeIncident) -> dict:
    return {"code_type": t.code_type, "libelle": t.libelle, "nb_incidents": len(t.incidents)}


@router.get("", response_model=list[TypeIncidentOut], summary="Liste des types d'incident")
def lister(db: Session = Depends(get_db), _=Depends(get_current_user)):
    types = db.scalars(
        select(models.TypeIncident).options(selectinload(models.TypeIncident.incidents)).order_by(models.TypeIncident.libelle)
    ).all()
    return [type_out(t) for t in types]


@router.post("", response_model=TypeIncidentOut, status_code=status.HTTP_201_CREATED, summary="Créer un type d'incident")
def creer(donnees: TypeIncidentIn, db: Session = Depends(get_db), _=Depends(autoriser("types_incident", CREER))):
    if db.get(models.TypeIncident, donnees.code_type):
        raise conflit(f"Le code de type {donnees.code_type} existe déjà.")
    type_incident = models.TypeIncident(**donnees.model_dump())
    db.add(type_incident)
    db.commit()
    db.refresh(type_incident)
    return type_out(type_incident)


@router.put("/{code_type}", response_model=TypeIncidentOut, summary="Modifier un type d'incident")
def modifier(
    code_type: str,
    donnees: TypeIncidentUpdate,
    db: Session = Depends(get_db),
    _=Depends(autoriser("types_incident", MODIFIER)),
):
    type_incident = obtenir_ou_404(db, models.TypeIncident, code_type.upper(), "Type d'incident introuvable.")
    type_incident.libelle = donnees.libelle
    db.commit()
    db.refresh(type_incident)
    return type_out(type_incident)


@router.delete("/{code_type}", status_code=status.HTTP_204_NO_CONTENT, summary="Supprimer un type d'incident")
def supprimer(code_type: str, db: Session = Depends(get_db), _=Depends(autoriser("types_incident", SUPPRIMER))):
    type_incident = obtenir_ou_404(db, models.TypeIncident, code_type.upper(), "Type d'incident introuvable.")
    if type_incident.incidents:
        raise conflit(f"Impossible : {len(type_incident.incidents)} incident(s) sont de ce type.")
    db.delete(type_incident)
    db.commit()
