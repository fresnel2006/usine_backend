from fastapi import APIRouter, Depends, status
from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app import models
from app.database import get_db
from app.schemas import MachineDetail, MachineIn, MachineOut, MachineUpdate
from app.security import CREER, MODIFIER, SUPPRIMER, autoriser, get_current_user
from app.serializers import conflit, machine_out, maintenance_courte, obtenir_ou_404

router = APIRouter(prefix="/api/machines", tags=["Machines"])


@router.get("", response_model=list[MachineOut], summary="Liste des machines")
def lister(ligne: int | None = None, db: Session = Depends(get_db), _=Depends(get_current_user)):
    requete = select(models.Machine).options(
        selectinload(models.Machine.ligne).selectinload(models.LigneProduction.atelier),
        selectinload(models.Machine.maintenances),
    )
    if ligne is not None:
        requete = requete.where(models.Machine.num_ligne == ligne)
    return [machine_out(m) for m in db.scalars(requete.order_by(models.Machine.num_machine)).all()]


@router.get("/{num_machine}", response_model=MachineDetail, summary="Fiche d'une machine et ses maintenances")
def detail(num_machine: int, db: Session = Depends(get_db), _=Depends(get_current_user)):
    machine = obtenir_ou_404(db, models.Machine, num_machine, "Machine introuvable.")
    return {
        **machine_out(machine),
        "maintenances": [
            maintenance_courte(m) for m in sorted(machine.maintenances, key=lambda m: m.date_heure_debut, reverse=True)
        ],
    }


@router.post("", response_model=MachineOut, status_code=status.HTTP_201_CREATED, summary="Ajouter une machine à une ligne")
def creer(donnees: MachineIn, db: Session = Depends(get_db), _=Depends(autoriser("machines", CREER))):
    if db.get(models.Machine, donnees.num_machine):
        raise conflit(f"Une machine porte déjà le numéro {donnees.num_machine}.")
    obtenir_ou_404(db, models.LigneProduction, donnees.num_ligne, f"Ligne de production {donnees.num_ligne} introuvable.")
    machine = models.Machine(**donnees.model_dump())
    db.add(machine)
    db.commit()
    db.refresh(machine)
    return machine_out(machine)


@router.put("/{num_machine}", response_model=MachineOut, summary="Modifier une machine")
def modifier(
    num_machine: int,
    donnees: MachineUpdate,
    db: Session = Depends(get_db),
    _=Depends(autoriser("machines", MODIFIER)),
):
    machine = obtenir_ou_404(db, models.Machine, num_machine, "Machine introuvable.")
    obtenir_ou_404(db, models.LigneProduction, donnees.num_ligne, f"Ligne de production {donnees.num_ligne} introuvable.")
    machine.designation = donnees.designation
    machine.num_ligne = donnees.num_ligne
    db.commit()
    db.refresh(machine)
    return machine_out(machine)


@router.delete("/{num_machine}", status_code=status.HTTP_204_NO_CONTENT, summary="Supprimer une machine")
def supprimer(num_machine: int, db: Session = Depends(get_db), _=Depends(autoriser("machines", SUPPRIMER))):
    machine = obtenir_ou_404(db, models.Machine, num_machine, "Machine introuvable.")
    if machine.maintenances:
        raise conflit(f"Impossible : {len(machine.maintenances)} maintenance(s) sont enregistrées sur cette machine.")
    db.delete(machine)
    db.commit()
