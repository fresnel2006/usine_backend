from datetime import date

from fastapi import APIRouter, Depends, status
from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app import models
from app.database import get_db
from app.schemas import LotIn, LotOut, LotUpdate
from app.security import CREER, MODIFIER, SUPPRIMER, autoriser, get_current_user
from app.serializers import charger_operateurs, conflit, lot_out, obtenir_ou_404

router = APIRouter(prefix="/api/lots", tags=["Lots de production"])

CHARGEMENT_LOT = (
    selectinload(models.LotProduction.ligne).selectinload(models.LigneProduction.atelier),
    selectinload(models.LotProduction.produit),
    selectinload(models.LotProduction.operateurs),
    selectinload(models.LotProduction.incidents),
)


def verifier_references(db: Session, donnees: LotIn | LotUpdate) -> list[models.Operateur]:
    obtenir_ou_404(db, models.LigneProduction, donnees.num_ligne, f"Ligne de production {donnees.num_ligne} introuvable.")
    obtenir_ou_404(db, models.Produit, donnees.reference_produit, f"Produit {donnees.reference_produit} introuvable.")
    return charger_operateurs(db, donnees.operateurs)


@router.get("", response_model=list[LotOut], summary="Liste des lots (filtres : période, ligne, produit)")
def lister(
    debut: date | None = None,
    fin: date | None = None,
    ligne: int | None = None,
    produit: str | None = None,
    db: Session = Depends(get_db),
    _=Depends(get_current_user),
):
    requete = select(models.LotProduction).options(*CHARGEMENT_LOT)
    if debut:
        requete = requete.where(models.LotProduction.date_production >= debut)
    if fin:
        requete = requete.where(models.LotProduction.date_production <= fin)
    if ligne is not None:
        requete = requete.where(models.LotProduction.num_ligne == ligne)
    if produit:
        requete = requete.where(models.LotProduction.reference_produit == produit.upper())
    lots = db.scalars(
        requete.order_by(models.LotProduction.date_production.desc(), models.LotProduction.num_lot.desc())
    ).all()
    return [lot_out(lot) for lot in lots]


@router.get("/{num_lot}", response_model=LotOut, summary="Détail d'un lot")
def detail(num_lot: int, db: Session = Depends(get_db), _=Depends(get_current_user)):
    return lot_out(obtenir_ou_404(db, models.LotProduction, num_lot, "Lot de production introuvable."))


@router.post("", response_model=LotOut, status_code=status.HTTP_201_CREATED, summary="Enregistrer un lot")
def creer(donnees: LotIn, db: Session = Depends(get_db), _=Depends(autoriser("lots", CREER))):
    if db.get(models.LotProduction, donnees.num_lot):
        raise conflit(f"Un lot porte déjà le numéro {donnees.num_lot}.")
    operateurs = verifier_references(db, donnees)
    lot = models.LotProduction(**donnees.model_dump(exclude={"operateurs"}))
    lot.operateurs = operateurs
    db.add(lot)
    db.commit()
    db.refresh(lot)
    return lot_out(lot)


@router.put("/{num_lot}", response_model=LotOut, summary="Modifier un lot")
def modifier(
    num_lot: int,
    donnees: LotUpdate,
    db: Session = Depends(get_db),
    _=Depends(autoriser("lots", MODIFIER)),
):
    lot = obtenir_ou_404(db, models.LotProduction, num_lot, "Lot de production introuvable.")
    operateurs = verifier_references(db, donnees)
    lot.date_production = donnees.date_production
    lot.num_ligne = donnees.num_ligne
    lot.reference_produit = donnees.reference_produit
    lot.operateurs = operateurs
    db.commit()
    db.refresh(lot)
    return lot_out(lot)


@router.delete("/{num_lot}", status_code=status.HTTP_204_NO_CONTENT, summary="Supprimer un lot")
def supprimer(num_lot: int, db: Session = Depends(get_db), _=Depends(autoriser("lots", SUPPRIMER))):
    lot = obtenir_ou_404(db, models.LotProduction, num_lot, "Lot de production introuvable.")
    if lot.incidents:
        raise conflit(f"Impossible : {len(lot.incidents)} incident(s) sont rattachés à ce lot.")
    db.delete(lot)
    db.commit()
