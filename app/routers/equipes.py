from fastapi import APIRouter, Depends, status
from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app import models
from app.database import get_db
from app.schemas import EquipeIn, EquipeOut, EquipeUpdate, OperateurCourt
from app.security import CREER, MODIFIER, SUPPRIMER, autoriser, get_current_user
from app.serializers import conflit, obtenir_ou_404, operateur_court

router = APIRouter(prefix="/api/equipes", tags=["Équipes"])


def equipe_out(e: models.Equipe) -> dict:
    membres = sorted(e.operateurs, key=lambda o: (o.nom, o.prenom))
    return {
        "num_equipe": e.num_equipe,
        "libelle": e.libelle,
        "matricule_responsable": e.matricule_responsable,
        "responsable": operateur_court(e.responsable),
        "nb_operateurs": len(membres),
        "operateurs": [operateur_court(o) for o in membres],
    }


def verifier_responsable(db: Session, matricule: str | None, num_equipe: int | None) -> None:
    """Une équipe a un seul collaborateur responsable, qui ne dirige pas déjà une autre équipe."""
    if not matricule:
        return
    obtenir_ou_404(db, models.Operateur, matricule, f"Opérateur {matricule} introuvable.")
    autre = db.scalar(select(models.Equipe).where(models.Equipe.matricule_responsable == matricule))
    if autre is not None and autre.num_equipe != num_equipe:
        raise conflit(f"L'opérateur {matricule} est déjà responsable de l'équipe {autre.libelle}.")


@router.get("", response_model=list[EquipeOut], summary="Liste des équipes")
def lister(db: Session = Depends(get_db), _=Depends(get_current_user)):
    equipes = db.scalars(
        select(models.Equipe)
        .options(selectinload(models.Equipe.responsable), selectinload(models.Equipe.operateurs))
        .order_by(models.Equipe.num_equipe)
    ).all()
    return [equipe_out(e) for e in equipes]


@router.get(
    "/responsables-disponibles",
    response_model=list[OperateurCourt],
    summary="Opérateurs pouvant être désignés responsables d'équipe",
)
def responsables_disponibles(equipe: int | None = None, db: Session = Depends(get_db), _=Depends(get_current_user)):
    deja = select(models.Equipe.matricule_responsable).where(models.Equipe.matricule_responsable.is_not(None))
    if equipe is not None:
        deja = deja.where(models.Equipe.num_equipe != equipe)
    operateurs = db.scalars(
        select(models.Operateur)
        .where(models.Operateur.matricule.not_in(deja))
        .order_by(models.Operateur.nom, models.Operateur.prenom)
    ).all()
    return [operateur_court(o) for o in operateurs]


@router.get("/{num_equipe}", response_model=EquipeOut, summary="Détail d'une équipe et de ses membres")
def detail(num_equipe: int, db: Session = Depends(get_db), _=Depends(get_current_user)):
    return equipe_out(obtenir_ou_404(db, models.Equipe, num_equipe, "Équipe introuvable."))


@router.post("", response_model=EquipeOut, status_code=status.HTTP_201_CREATED, summary="Créer une équipe")
def creer(donnees: EquipeIn, db: Session = Depends(get_db), _=Depends(autoriser("equipes", CREER))):
    if db.get(models.Equipe, donnees.num_equipe):
        raise conflit(f"Une équipe porte déjà le numéro {donnees.num_equipe}.")
    verifier_responsable(db, donnees.matricule_responsable, None)
    equipe = models.Equipe(
        num_equipe=donnees.num_equipe,
        libelle=donnees.libelle,
        matricule_responsable=donnees.matricule_responsable or None,
    )
    db.add(equipe)
    db.commit()
    db.refresh(equipe)
    return equipe_out(equipe)


@router.put("/{num_equipe}", response_model=EquipeOut, summary="Modifier une équipe ou désigner son responsable")
def modifier(
    num_equipe: int,
    donnees: EquipeUpdate,
    db: Session = Depends(get_db),
    _=Depends(autoriser("equipes", MODIFIER)),
):
    equipe = obtenir_ou_404(db, models.Equipe, num_equipe, "Équipe introuvable.")
    verifier_responsable(db, donnees.matricule_responsable, num_equipe)
    equipe.libelle = donnees.libelle
    equipe.matricule_responsable = donnees.matricule_responsable or None
    db.commit()
    db.refresh(equipe)
    return equipe_out(equipe)


@router.delete("/{num_equipe}", status_code=status.HTTP_204_NO_CONTENT, summary="Supprimer une équipe")
def supprimer(num_equipe: int, db: Session = Depends(get_db), _=Depends(autoriser("equipes", SUPPRIMER))):
    equipe = obtenir_ou_404(db, models.Equipe, num_equipe, "Équipe introuvable.")
    if equipe.operateurs:
        raise conflit(f"Impossible : l'équipe compte encore {len(equipe.operateurs)} opérateur(s).")
    db.delete(equipe)
    db.commit()
