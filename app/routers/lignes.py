from fastapi import APIRouter, Depends, status
from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app import models
from app.database import get_db
from app.schemas import LigneDetail, LigneIn, LigneOut, LigneUpdate
from app.security import CREER, MODIFIER, SUPPRIMER, autoriser, get_current_user
from app.serializers import conflit, lot_court, obtenir_ou_404

router = APIRouter(prefix="/api/lignes", tags=["Lignes de production"])


def ligne_out(l: models.LigneProduction) -> dict:
    return {
        "num_ligne": l.num_ligne,
        "nb_operateurs_necessaires": l.nb_operateurs_necessaires,
        "num_atelier": l.num_atelier,
        "atelier_libelle": l.atelier.libelle,
        "nb_machines": len(l.machines),
        "nb_lots": len(l.lots),
    }


@router.get("", response_model=list[LigneOut], summary="Liste des lignes de production")
def lister(atelier: int | None = None, db: Session = Depends(get_db), _=Depends(get_current_user)):
    requete = select(models.LigneProduction).options(
        selectinload(models.LigneProduction.atelier),
        selectinload(models.LigneProduction.machines),
        selectinload(models.LigneProduction.lots),
    )
    if atelier is not None:
        requete = requete.where(models.LigneProduction.num_atelier == atelier)
    lignes = db.scalars(requete.order_by(models.LigneProduction.num_ligne)).all()
    return [ligne_out(l) for l in lignes]


@router.get("/{num_ligne}", response_model=LigneDetail, summary="Détail d'une ligne : machines et lots")
def detail(num_ligne: int, db: Session = Depends(get_db), _=Depends(get_current_user)):
    ligne = obtenir_ou_404(db, models.LigneProduction, num_ligne, "Ligne de production introuvable.")
    return {
        **ligne_out(ligne),
        "machines": [
            {"num_machine": m.num_machine, "designation": m.designation}
            for m in sorted(ligne.machines, key=lambda m: m.num_machine)
        ],
        "lots": [lot_court(lot) for lot in sorted(ligne.lots, key=lambda x: x.date_production, reverse=True)],
    }


@router.post("", response_model=LigneOut, status_code=status.HTTP_201_CREATED, summary="Créer une ligne")
def creer(donnees: LigneIn, db: Session = Depends(get_db), _=Depends(autoriser("lignes", CREER))):
    if db.get(models.LigneProduction, donnees.num_ligne):
        raise conflit(f"Une ligne de production porte déjà le numéro {donnees.num_ligne}.")
    obtenir_ou_404(db, models.Atelier, donnees.num_atelier, f"Atelier {donnees.num_atelier} introuvable.")
    ligne = models.LigneProduction(**donnees.model_dump())
    db.add(ligne)
    db.commit()
    db.refresh(ligne)
    return ligne_out(ligne)


@router.put("/{num_ligne}", response_model=LigneOut, summary="Modifier une ligne")
def modifier(
    num_ligne: int,
    donnees: LigneUpdate,
    db: Session = Depends(get_db),
    _=Depends(autoriser("lignes", MODIFIER)),
):
    ligne = obtenir_ou_404(db, models.LigneProduction, num_ligne, "Ligne de production introuvable.")
    obtenir_ou_404(db, models.Atelier, donnees.num_atelier, f"Atelier {donnees.num_atelier} introuvable.")
    ligne.nb_operateurs_necessaires = donnees.nb_operateurs_necessaires
    ligne.num_atelier = donnees.num_atelier
    db.commit()
    db.refresh(ligne)
    return ligne_out(ligne)


@router.delete("/{num_ligne}", status_code=status.HTTP_204_NO_CONTENT, summary="Supprimer une ligne")
def supprimer(num_ligne: int, db: Session = Depends(get_db), _=Depends(autoriser("lignes", SUPPRIMER))):
    ligne = obtenir_ou_404(db, models.LigneProduction, num_ligne, "Ligne de production introuvable.")
    if ligne.machines:
        raise conflit(f"Suppression impossible : la ligne comporte encore {len(ligne.machines)} machine(s).")
    if ligne.lots:
        raise conflit(f"Suppression impossible : {len(ligne.lots)} lot(s) de production sont rattachés à cette ligne.")
    db.delete(ligne)
    db.commit()
