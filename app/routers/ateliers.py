from fastapi import APIRouter, Depends, status
from sqlalchemy import func, select
from sqlalchemy.orm import Session, selectinload

from app import models
from app.database import get_db
from app.schemas import AtelierIn, AtelierOut, AtelierUpdate, OperateurCourt
from app.security import CREER, MODIFIER, SUPPRIMER, autoriser, get_current_user
from app.serializers import conflit, obtenir_ou_404, operateur_court

router = APIRouter(prefix="/api/ateliers", tags=["Ateliers"])


def atelier_out(a: models.Atelier) -> dict:
    return {
        "num_atelier": a.num_atelier,
        "libelle": a.libelle,
        "matricule_responsable": a.matricule_responsable,
        "responsable": operateur_court(a.responsable),
        "nb_lignes": len(a.lignes),
    }


def verifier_responsable(db: Session, matricule: str, num_atelier: int | None) -> None:
    """Un atelier a un seul responsable, et un opérateur ne dirige qu'un seul atelier."""
    obtenir_ou_404(db, models.Operateur, matricule, f"Opérateur {matricule} introuvable.")
    autre = db.scalar(select(models.Atelier).where(models.Atelier.matricule_responsable == matricule))
    if autre is not None and autre.num_atelier != num_atelier:
        raise conflit(
            f"L'opérateur {matricule} est déjà responsable de l'atelier "
            f"{autre.num_atelier} ({autre.libelle})."
        )


@router.get("", response_model=list[AtelierOut], summary="Liste des ateliers")
def lister(db: Session = Depends(get_db), _=Depends(get_current_user)):
    ateliers = db.scalars(
        select(models.Atelier)
        .options(selectinload(models.Atelier.responsable), selectinload(models.Atelier.lignes))
        .order_by(models.Atelier.num_atelier)
    ).all()
    return [atelier_out(a) for a in ateliers]


@router.get(
    "/responsables-disponibles",
    response_model=list[OperateurCourt],
    summary="Opérateurs pouvant être désignés responsables",
)
def responsables_disponibles(
    atelier: int | None = None, db: Session = Depends(get_db), _=Depends(get_current_user)
):
    """Opérateurs qui ne sont pas déjà responsables d'un autre atelier que celui indiqué."""
    deja = select(models.Atelier.matricule_responsable)
    if atelier is not None:
        deja = deja.where(models.Atelier.num_atelier != atelier)
    operateurs = db.scalars(
        select(models.Operateur)
        .where(models.Operateur.matricule.not_in(deja))
        .order_by(models.Operateur.nom, models.Operateur.prenom)
    ).all()
    return [operateur_court(o) for o in operateurs]


@router.get("/{num_atelier}", response_model=AtelierOut, summary="Détail d'un atelier")
def detail(num_atelier: int, db: Session = Depends(get_db), _=Depends(get_current_user)):
    return atelier_out(obtenir_ou_404(db, models.Atelier, num_atelier, "Atelier introuvable."))


@router.post("", response_model=AtelierOut, status_code=status.HTTP_201_CREATED, summary="Créer un atelier")
def creer(donnees: AtelierIn, db: Session = Depends(get_db), _=Depends(autoriser("ateliers", CREER))):
    if db.get(models.Atelier, donnees.num_atelier):
        raise conflit(f"Un atelier porte déjà le numéro {donnees.num_atelier}.")
    verifier_responsable(db, donnees.matricule_responsable, None)
    atelier = models.Atelier(**donnees.model_dump())
    db.add(atelier)
    db.commit()
    db.refresh(atelier)
    return atelier_out(atelier)


@router.put("/{num_atelier}", response_model=AtelierOut, summary="Modifier un atelier")
def modifier(
    num_atelier: int,
    donnees: AtelierUpdate,
    db: Session = Depends(get_db),
    _=Depends(autoriser("ateliers", MODIFIER)),
):
    atelier = obtenir_ou_404(db, models.Atelier, num_atelier, "Atelier introuvable.")
    verifier_responsable(db, donnees.matricule_responsable, num_atelier)
    atelier.libelle = donnees.libelle
    atelier.matricule_responsable = donnees.matricule_responsable
    db.commit()
    db.refresh(atelier)
    return atelier_out(atelier)


@router.delete("/{num_atelier}", status_code=status.HTTP_204_NO_CONTENT, summary="Supprimer un atelier")
def supprimer(num_atelier: int, db: Session = Depends(get_db), _=Depends(autoriser("ateliers", SUPPRIMER))):
    atelier = obtenir_ou_404(db, models.Atelier, num_atelier, "Atelier introuvable.")
    nb_lignes = db.scalar(
        select(func.count()).select_from(models.LigneProduction).where(models.LigneProduction.num_atelier == num_atelier)
    )
    if nb_lignes:
        raise conflit(
            f"Suppression impossible : l'atelier contient encore {nb_lignes} ligne(s) de production."
        )
    db.delete(atelier)
    db.commit()
