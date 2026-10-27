from datetime import date

from fastapi import APIRouter, Depends, status
from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app import models
from app.database import get_db
from app.schemas import AchatGlobalIn, AchatOut, AchatUpdate
from app.security import CREER, MODIFIER, SUPPRIMER, autoriser, get_current_user
from app.serializers import achat_out, conflit, obtenir_ou_404, piece_verrouillee

router = APIRouter(prefix="/api/achats", tags=["Achats de pièces"])


def obtenir_achat(db: Session, reference: str, code: str, date_achat: date) -> models.Achat:
    return obtenir_ou_404(db, models.Achat, (reference.upper(), code.upper(), date_achat), "Achat introuvable.")


@router.get("", response_model=list[AchatOut], summary="Historique des achats (filtres : pièce, fournisseur)")
def lister(
    piece: str | None = None,
    fournisseur: str | None = None,
    db: Session = Depends(get_db),
    _=Depends(get_current_user),
):
    requete = select(models.Achat).options(selectinload(models.Achat.piece), selectinload(models.Achat.fournisseur))
    if piece:
        requete = requete.where(models.Achat.reference_piece == piece.upper())
    if fournisseur:
        requete = requete.where(models.Achat.code_fournisseur == fournisseur.upper())
    achats = db.scalars(requete.order_by(models.Achat.date_achat.desc(), models.Achat.reference_piece)).all()
    return [achat_out(a) for a in achats]


@router.post(
    "",
    response_model=AchatOut,
    status_code=status.HTTP_201_CREATED,
    summary="Enregistrer un achat de pièce (le stock augmente)",
)
def creer(donnees: AchatGlobalIn, db: Session = Depends(get_db), _=Depends(autoriser("achats", CREER))):
    obtenir_ou_404(db, models.Fournisseur, donnees.code_fournisseur, f"Fournisseur {donnees.code_fournisseur} introuvable.")
    piece = piece_verrouillee(db, donnees.reference_piece)
    if db.get(models.Achat, (donnees.reference_piece, donnees.code_fournisseur, donnees.date_achat)):
        raise conflit(
            "Un achat de cette pièce chez ce fournisseur est déjà enregistré à cette date : modifiez-le plutôt."
        )
    achat = models.Achat(**donnees.model_dump())
    piece.quantite_stock += donnees.quantite
    db.add(achat)
    db.commit()
    db.refresh(achat)
    return achat_out(achat)


@router.put(
    "/{reference}/{code_fournisseur}/{date_achat}",
    response_model=AchatOut,
    summary="Modifier un achat (le stock est ajusté de la différence)",
)
def modifier(
    reference: str,
    code_fournisseur: str,
    date_achat: date,
    donnees: AchatUpdate,
    db: Session = Depends(get_db),
    _=Depends(autoriser("achats", MODIFIER)),
):
    achat = obtenir_achat(db, reference, code_fournisseur, date_achat)
    piece = piece_verrouillee(db, achat.reference_piece)
    ecart = donnees.quantite - achat.quantite
    if piece.quantite_stock + ecart < 0:
        raise conflit(
            f"Impossible : {piece.quantite_stock} pièce(s) seulement sont encore en stock, "
            f"la quantité achetée ne peut pas descendre à {donnees.quantite}."
        )
    piece.quantite_stock += ecart
    achat.prix_achat = donnees.prix_achat
    achat.quantite = donnees.quantite
    db.commit()
    db.refresh(achat)
    return achat_out(achat)


@router.delete(
    "/{reference}/{code_fournisseur}/{date_achat}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Supprimer un achat (les pièces sont retirées du stock)",
)
def supprimer(
    reference: str,
    code_fournisseur: str,
    date_achat: date,
    db: Session = Depends(get_db),
    _=Depends(autoriser("achats", SUPPRIMER)),
):
    achat = obtenir_achat(db, reference, code_fournisseur, date_achat)
    piece = piece_verrouillee(db, achat.reference_piece)
    if piece.quantite_stock < achat.quantite:
        raise conflit(
            f"Impossible : {achat.quantite} pièce(s) achetée(s) mais {piece.quantite_stock} seulement encore en stock."
        )
    piece.quantite_stock -= achat.quantite
    db.delete(achat)
    db.commit()
