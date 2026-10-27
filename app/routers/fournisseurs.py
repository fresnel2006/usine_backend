from fastapi import APIRouter, Depends, status
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app import models
from app.database import get_db
from app.schemas import FournisseurDetail, FournisseurIn, FournisseurOut, FournisseurUpdate
from app.security import CREER, MODIFIER, SUPPRIMER, autoriser, get_current_user
from app.serializers import achat_out, conflit, obtenir_ou_404

router = APIRouter(prefix="/api/fournisseurs", tags=["Fournisseurs"])


def fournisseur_out(f: models.Fournisseur, nb_pieces: int, nb_achats: int) -> dict:
    return {
        "code_fournisseur": f.code_fournisseur,
        "raison_sociale": f.raison_sociale,
        "adresse": f.adresse,
        "telephone": f.telephone,
        "nb_pieces": nb_pieces,
        "nb_achats": nb_achats,
    }


def obtenir_fournisseur(db: Session, code: str) -> models.Fournisseur:
    return obtenir_ou_404(db, models.Fournisseur, code.upper(), "Fournisseur introuvable.")


def achats_de(db: Session, code: str) -> list[models.Achat]:
    return db.scalars(
        select(models.Achat).where(models.Achat.code_fournisseur == code).order_by(models.Achat.date_achat.desc())
    ).all()


@router.get("", response_model=list[FournisseurOut], summary="Liste des fournisseurs")
def lister(db: Session = Depends(get_db), _=Depends(get_current_user)):
    # Nombre de pièces différentes fournies et nombre d'achats, par fournisseur
    comptes = {
        code: (nb_pieces, nb_achats)
        for code, nb_pieces, nb_achats in db.execute(
            select(
                models.Achat.code_fournisseur,
                func.count(func.distinct(models.Achat.reference_piece)),
                func.count(),
            ).group_by(models.Achat.code_fournisseur)
        ).all()
    }
    fournisseurs = db.scalars(select(models.Fournisseur).order_by(models.Fournisseur.code_fournisseur)).all()
    return [fournisseur_out(f, *comptes.get(f.code_fournisseur, (0, 0))) for f in fournisseurs]


@router.get("/{code}", response_model=FournisseurDetail, summary="Fiche d'un fournisseur : pièces fournies et achats")
def detail(code: str, db: Session = Depends(get_db), _=Depends(get_current_user)):
    fournisseur = obtenir_fournisseur(db, code)
    achats = achats_de(db, fournisseur.code_fournisseur)
    pieces: dict[str, dict] = {}
    for a in sorted(achats, key=lambda a: a.date_achat):
        p = pieces.setdefault(
            a.reference_piece,
            {"reference_piece": a.reference_piece, "libelle": a.piece.libelle, "nb_achats": 0, "quantite_totale": 0},
        )
        p["nb_achats"] += 1
        p["quantite_totale"] += a.quantite
        p["dernier_prix"] = float(a.prix_achat)
        p["derniere_date"] = a.date_achat
    return {
        **fournisseur_out(fournisseur, len(pieces), len(achats)),
        "pieces": sorted(pieces.values(), key=lambda p: p["reference_piece"]),
        "achats": [achat_out(a) for a in achats],
    }


@router.post("", response_model=FournisseurOut, status_code=status.HTTP_201_CREATED, summary="Ajouter un fournisseur")
def creer(donnees: FournisseurIn, db: Session = Depends(get_db), _=Depends(autoriser("fournisseurs", CREER))):
    if db.get(models.Fournisseur, donnees.code_fournisseur):
        raise conflit(f"Le code fournisseur {donnees.code_fournisseur} existe déjà.")
    fournisseur = models.Fournisseur(
        code_fournisseur=donnees.code_fournisseur,
        raison_sociale=donnees.raison_sociale,
        adresse=donnees.adresse or None,
        telephone=donnees.telephone or None,
    )
    db.add(fournisseur)
    db.commit()
    db.refresh(fournisseur)
    return fournisseur_out(fournisseur, 0, 0)


@router.put("/{code}", response_model=FournisseurOut, summary="Modifier un fournisseur")
def modifier(
    code: str,
    donnees: FournisseurUpdate,
    db: Session = Depends(get_db),
    _=Depends(autoriser("fournisseurs", MODIFIER)),
):
    fournisseur = obtenir_fournisseur(db, code)
    fournisseur.raison_sociale = donnees.raison_sociale
    fournisseur.adresse = donnees.adresse or None
    fournisseur.telephone = donnees.telephone or None
    db.commit()
    db.refresh(fournisseur)
    achats = achats_de(db, fournisseur.code_fournisseur)
    return fournisseur_out(fournisseur, len({a.reference_piece for a in achats}), len(achats))


@router.delete("/{code}", status_code=status.HTTP_204_NO_CONTENT, summary="Supprimer un fournisseur")
def supprimer(code: str, db: Session = Depends(get_db), _=Depends(autoriser("fournisseurs", SUPPRIMER))):
    fournisseur = obtenir_fournisseur(db, code)
    achats = achats_de(db, fournisseur.code_fournisseur)
    if achats:
        raise conflit(f"Impossible : {len(achats)} achat(s) sont enregistrés chez ce fournisseur.")
    db.delete(fournisseur)
    db.commit()
