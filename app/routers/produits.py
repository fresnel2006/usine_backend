from fastapi import APIRouter, Depends, status
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app import models
from app.database import get_db
from app.schemas import ProduitIn, ProduitOut, ProduitUpdate
from app.security import CREER, MODIFIER, SUPPRIMER, autoriser, get_current_user
from app.serializers import conflit, obtenir_ou_404

router = APIRouter(prefix="/api/produits", tags=["Produits"])


@router.get("", response_model=list[ProduitOut], summary="Liste des produits")
def lister(db: Session = Depends(get_db), _=Depends(get_current_user)):
    return db.scalars(select(models.Produit).order_by(models.Produit.reference)).all()


@router.get("/{reference}", response_model=ProduitOut, summary="Détail d'un produit")
def detail(reference: str, db: Session = Depends(get_db), _=Depends(get_current_user)):
    return obtenir_ou_404(db, models.Produit, reference.upper(), "Produit introuvable.")


@router.post("", response_model=ProduitOut, status_code=status.HTTP_201_CREATED, summary="Créer un produit")
def creer(donnees: ProduitIn, db: Session = Depends(get_db), _=Depends(autoriser("produits", CREER))):
    if db.get(models.Produit, donnees.reference):
        raise conflit(f"La référence produit {donnees.reference} existe déjà.")
    produit = models.Produit(**donnees.model_dump())
    db.add(produit)
    db.commit()
    db.refresh(produit)
    return produit


@router.put("/{reference}", response_model=ProduitOut, summary="Modifier un produit")
def modifier(
    reference: str,
    donnees: ProduitUpdate,
    db: Session = Depends(get_db),
    _=Depends(autoriser("produits", MODIFIER)),
):
    produit = obtenir_ou_404(db, models.Produit, reference.upper(), "Produit introuvable.")
    for champ, valeur in donnees.model_dump().items():
        setattr(produit, champ, valeur)
    db.commit()
    db.refresh(produit)
    return produit


@router.delete("/{reference}", status_code=status.HTTP_204_NO_CONTENT, summary="Supprimer un produit")
def supprimer(reference: str, db: Session = Depends(get_db), _=Depends(autoriser("produits", SUPPRIMER))):
    produit = obtenir_ou_404(db, models.Produit, reference.upper(), "Produit introuvable.")
    nb_lots = db.scalar(
        select(func.count()).select_from(models.LotProduction).where(models.LotProduction.reference_produit == produit.reference)
    )
    if nb_lots:
        raise conflit(f"Suppression impossible : {nb_lots} lot(s) de production concernent ce produit.")
    db.delete(produit)
    db.commit()
