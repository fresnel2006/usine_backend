from fastapi import APIRouter, Depends, status
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app import models
from app.config import settings
from app.database import get_db
from app.schemas import (
    ComposantIn,
    ComposantUpdate,
    Nomenclature,
    PieceDetail,
    PieceIn,
    PieceOut,
    PieceUpdate,
)
from app.security import CREER, MODIFIER, SUPPRIMER, autoriser, get_current_user
from app.serializers import achat_out, conflit, obtenir_ou_404, piece_out, requete_invalide

router = APIRouter(prefix="/api/pieces", tags=["Pièces et stock"])


def obtenir_piece(db: Session, reference: str) -> models.Piece:
    return obtenir_ou_404(db, models.Piece, reference.upper(), "Pièce introuvable.")


def _liens(db: Session) -> list[models.Nomenclature]:
    return db.scalars(select(models.Nomenclature)).all()


def arbre(db: Session, piece: models.Piece) -> dict:
    """Composants (descendants) et pièces qui l'utilisent (ascendants), en arbre dépliable."""
    liens = _liens(db)
    pieces = {p.reference: p for p in db.scalars(select(models.Piece))}
    enfants: dict[str, list[models.Nomenclature]] = {}
    parents: dict[str, list[models.Nomenclature]] = {}
    for lien in liens:
        enfants.setdefault(lien.reference_composee, []).append(lien)
        parents.setdefault(lien.reference_composant, []).append(lien)

    def noeud(reference: str, quantite: int, index: dict, attribut: str, chemin: frozenset) -> dict:
        p = pieces[reference]
        suite = [] if reference in chemin else [
            noeud(getattr(l, attribut), l.quantite, index, attribut, chemin | {reference})
            for l in sorted(index.get(reference, []), key=lambda l: getattr(l, attribut))
        ]
        return {
            "reference": p.reference,
            "libelle": p.libelle,
            "quantite": quantite,
            "quantite_stock": p.quantite_stock,
            "composants": suite,
        }

    racine = frozenset({piece.reference})
    return {
        "reference": piece.reference,
        "libelle": piece.libelle,
        "composants": [
            noeud(l.reference_composant, l.quantite, enfants, "reference_composant", racine)
            for l in sorted(enfants.get(piece.reference, []), key=lambda l: l.reference_composant)
        ],
        "utilisee_dans": [
            noeud(l.reference_composee, l.quantite, parents, "reference_composee", racine)
            for l in sorted(parents.get(piece.reference, []), key=lambda l: l.reference_composee)
        ],
    }


def contient(db: Session, composee: str, cherchee: str) -> bool:
    """Vrai si la pièce « composee » contient « cherchee », directement ou non."""
    enfants: dict[str, list[str]] = {}
    for lien in _liens(db):
        enfants.setdefault(lien.reference_composee, []).append(lien.reference_composant)
    a_voir, vues = [composee], set()
    while a_voir:
        courante = a_voir.pop()
        if courante == cherchee:
            return True
        if courante not in vues:
            vues.add(courante)
            a_voir.extend(enfants.get(courante, []))
    return False


@router.get("", response_model=list[PieceOut], summary="Liste des pièces (filtre : stock faible)")
def lister(stock_faible: bool = False, db: Session = Depends(get_db), _=Depends(get_current_user)):
    requete = select(models.Piece).order_by(models.Piece.reference)
    if stock_faible:
        requete = requete.where(models.Piece.quantite_stock <= settings.seuil_stock_faible)
    nb = dict(
        db.execute(
            select(models.Nomenclature.reference_composee, func.count()).group_by(models.Nomenclature.reference_composee)
        ).all()
    )
    return [piece_out(p, nb.get(p.reference, 0)) for p in db.scalars(requete).all()]


@router.get("/{reference}", response_model=PieceDetail, summary="Fiche d'une pièce : nomenclature, achats, maintenances")
def detail(reference: str, db: Session = Depends(get_db), _=Depends(get_current_user)):
    piece = obtenir_piece(db, reference)
    nomenclature = arbre(db, piece)
    achats = db.scalars(
        select(models.Achat).where(models.Achat.reference_piece == piece.reference).order_by(models.Achat.date_achat)
    ).all()
    consommations = db.scalars(
        select(models.Consommer).where(models.Consommer.reference_piece == piece.reference)
    ).all()
    return {
        **piece_out(piece, len(nomenclature["composants"])),
        "nomenclature": nomenclature,
        "achats": [achat_out(a) for a in achats],
        "maintenances": sorted(
            (
                {
                    "num_maintenance": c.maintenance.num_maintenance,
                    "date_heure_debut": c.maintenance.date_heure_debut,
                    "duree": c.maintenance.duree,
                    "num_machine": c.maintenance.num_machine,
                    "designation_machine": c.maintenance.machine.designation,
                    "quantite": c.quantite,
                }
                for c in consommations
            ),
            key=lambda m: m["date_heure_debut"],
            reverse=True,
        ),
    }


@router.post("", response_model=PieceOut, status_code=status.HTTP_201_CREATED, summary="Ajouter une pièce")
def creer(donnees: PieceIn, db: Session = Depends(get_db), _=Depends(autoriser("pieces", CREER))):
    if db.get(models.Piece, donnees.reference):
        raise conflit(f"La référence pièce {donnees.reference} existe déjà.")
    piece = models.Piece(**donnees.model_dump())
    db.add(piece)
    db.commit()
    db.refresh(piece)
    return piece_out(piece)


@router.put("/{reference}", response_model=PieceOut, summary="Modifier une pièce")
def modifier(
    reference: str,
    donnees: PieceUpdate,
    db: Session = Depends(get_db),
    _=Depends(autoriser("pieces", MODIFIER)),
):
    piece = obtenir_piece(db, reference)
    for champ, valeur in donnees.model_dump().items():
        setattr(piece, champ, valeur)
    db.commit()
    db.refresh(piece)
    return piece_out(piece)


@router.delete("/{reference}", status_code=status.HTTP_204_NO_CONTENT, summary="Supprimer une pièce")
def supprimer(reference: str, db: Session = Depends(get_db), _=Depends(autoriser("pieces", SUPPRIMER))):
    piece = obtenir_piece(db, reference)
    ref = piece.reference

    def compter(modele, condition) -> int:
        return db.scalar(select(func.count()).select_from(modele).where(condition))

    if compter(models.Consommer, models.Consommer.reference_piece == ref):
        raise conflit("Impossible : cette pièce a été consommée lors de maintenances.")
    if compter(models.Achat, models.Achat.reference_piece == ref):
        raise conflit("Impossible : des achats de cette pièce sont enregistrés.")
    if compter(
        models.Nomenclature,
        (models.Nomenclature.reference_composee == ref) | (models.Nomenclature.reference_composant == ref),
    ):
        raise conflit("Impossible : cette pièce figure dans une nomenclature. Retirez d'abord ses liens.")
    db.delete(piece)
    db.commit()


# ---------------------------------------------------------------------
# Nomenclature : une pièce composée d'autres pièces
# ---------------------------------------------------------------------
@router.get("/{reference}/nomenclature", response_model=Nomenclature, summary="Nomenclature d'une pièce (arbre)")
def nomenclature(reference: str, db: Session = Depends(get_db), _=Depends(get_current_user)):
    return arbre(db, obtenir_piece(db, reference))


@router.post(
    "/{reference}/composants",
    response_model=Nomenclature,
    status_code=status.HTTP_201_CREATED,
    summary="Ajouter un composant à une pièce",
)
def ajouter_composant(
    reference: str,
    donnees: ComposantIn,
    db: Session = Depends(get_db),
    _=Depends(autoriser("nomenclature", CREER)),
):
    piece = obtenir_piece(db, reference)
    composant = obtenir_piece(db, donnees.reference_composant)
    if composant.reference == piece.reference:
        raise requete_invalide("Une pièce ne peut pas se composer d'elle-même.")
    if db.get(models.Nomenclature, (piece.reference, composant.reference)):
        raise conflit("Ce composant figure déjà dans la nomenclature : modifiez sa quantité.")
    if contient(db, composant.reference, piece.reference):
        raise conflit(
            f"Impossible : {composant.reference} contient déjà {piece.reference}, la nomenclature tournerait en boucle."
        )
    db.add(
        models.Nomenclature(
            reference_composee=piece.reference, reference_composant=composant.reference, quantite=donnees.quantite
        )
    )
    db.commit()
    return arbre(db, piece)


@router.put("/{reference}/composants/{composant}", response_model=Nomenclature, summary="Modifier la quantité d'un composant")
def modifier_composant(
    reference: str,
    composant: str,
    donnees: ComposantUpdate,
    db: Session = Depends(get_db),
    _=Depends(autoriser("nomenclature", MODIFIER)),
):
    piece = obtenir_piece(db, reference)
    lien = obtenir_ou_404(
        db, models.Nomenclature, (piece.reference, composant.upper()), "Ce composant ne figure pas dans la nomenclature."
    )
    lien.quantite = donnees.quantite
    db.commit()
    return arbre(db, piece)


@router.delete("/{reference}/composants/{composant}", response_model=Nomenclature, summary="Retirer un composant")
def retirer_composant(
    reference: str,
    composant: str,
    db: Session = Depends(get_db),
    _=Depends(autoriser("nomenclature", SUPPRIMER)),
):
    piece = obtenir_piece(db, reference)
    lien = obtenir_ou_404(
        db, models.Nomenclature, (piece.reference, composant.upper()), "Ce composant ne figure pas dans la nomenclature."
    )
    db.delete(lien)
    db.commit()
    return arbre(db, piece)
