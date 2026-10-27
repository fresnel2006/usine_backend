from fastapi import APIRouter, Depends, status
from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app import models
from app.database import get_db
from app.schemas import OperateurDetail, OperateurIn, OperateurOut, OperateurUpdate
from app.security import CREER, MODIFIER, SUPPRIMER, autoriser, get_current_user
from app.serializers import conflit, lot_court, maintenance_courte, obtenir_ou_404

router = APIRouter(prefix="/api/operateurs", tags=["Opérateurs"])


def operateur_out(o: models.Operateur, ateliers: dict[str, models.Atelier], comptes: dict[str, str]) -> dict:
    atelier = ateliers.get(o.matricule)
    return {
        "matricule": o.matricule,
        "nom": o.nom,
        "prenom": o.prenom,
        "date_entree": o.date_entree,
        "num_equipe": o.num_equipe,
        "equipe_libelle": o.equipe.libelle,
        "est_responsable_equipe": o.equipe.matricule_responsable == o.matricule,
        "atelier_responsable": f"{atelier.num_atelier} - {atelier.libelle}" if atelier else None,
        "compte": comptes.get(o.matricule),
    }


def _contexte(db: Session) -> tuple[dict[str, models.Atelier], dict[str, str]]:
    """Ateliers dirigés et comptes liés, indexés par matricule (deux requêtes pour toute la liste)."""
    ateliers = {a.matricule_responsable: a for a in db.scalars(select(models.Atelier))}
    comptes = {
        u.matricule: u.login for u in db.scalars(select(models.Utilisateur).where(models.Utilisateur.matricule.is_not(None)))
    }
    return ateliers, comptes


@router.get("", response_model=list[OperateurOut], summary="Liste des opérateurs")
def lister(equipe: int | None = None, db: Session = Depends(get_db), _=Depends(get_current_user)):
    requete = select(models.Operateur).options(selectinload(models.Operateur.equipe))
    if equipe is not None:
        requete = requete.where(models.Operateur.num_equipe == equipe)
    operateurs = db.scalars(requete.order_by(models.Operateur.nom, models.Operateur.prenom)).all()
    ateliers, comptes = _contexte(db)
    return [operateur_out(o, ateliers, comptes) for o in operateurs]


@router.get("/{matricule}", response_model=OperateurDetail, summary="Fiche d'un opérateur : lots et maintenances")
def detail(matricule: str, db: Session = Depends(get_db), _=Depends(get_current_user)):
    o = obtenir_ou_404(db, models.Operateur, matricule.upper(), "Opérateur introuvable.")
    ateliers, comptes = _contexte(db)
    return {
        **operateur_out(o, ateliers, comptes),
        "lots": [lot_court(lot) for lot in sorted(o.lots, key=lambda x: x.date_production, reverse=True)],
        "maintenances": [
            maintenance_courte(m) for m in sorted(o.maintenances, key=lambda m: m.date_heure_debut, reverse=True)
        ],
    }


@router.post("", response_model=OperateurOut, status_code=status.HTTP_201_CREATED, summary="Ajouter un opérateur")
def creer(donnees: OperateurIn, db: Session = Depends(get_db), _=Depends(autoriser("operateurs", CREER))):
    if db.get(models.Operateur, donnees.matricule):
        raise conflit(f"Le matricule {donnees.matricule} est déjà attribué.")
    obtenir_ou_404(db, models.Equipe, donnees.num_equipe, f"Équipe {donnees.num_equipe} introuvable.")
    operateur = models.Operateur(**donnees.model_dump())
    db.add(operateur)
    db.commit()
    db.refresh(operateur)
    return operateur_out(operateur, *_contexte(db))


@router.put("/{matricule}", response_model=OperateurOut, summary="Modifier un opérateur")
def modifier(
    matricule: str,
    donnees: OperateurUpdate,
    db: Session = Depends(get_db),
    _=Depends(autoriser("operateurs", MODIFIER)),
):
    operateur = obtenir_ou_404(db, models.Operateur, matricule.upper(), "Opérateur introuvable.")
    obtenir_ou_404(db, models.Equipe, donnees.num_equipe, f"Équipe {donnees.num_equipe} introuvable.")
    if donnees.num_equipe != operateur.num_equipe and operateur.equipe.matricule_responsable == operateur.matricule:
        raise conflit(
            f"{operateur.nom_complet} est responsable de l'équipe {operateur.equipe.libelle} : "
            "désignez d'abord un autre responsable avant de le changer d'équipe."
        )
    for champ, valeur in donnees.model_dump().items():
        setattr(operateur, champ, valeur)
    db.commit()
    db.refresh(operateur)
    return operateur_out(operateur, *_contexte(db))


@router.delete("/{matricule}", status_code=status.HTTP_204_NO_CONTENT, summary="Supprimer un opérateur")
def supprimer(matricule: str, db: Session = Depends(get_db), _=Depends(autoriser("operateurs", SUPPRIMER))):
    operateur = obtenir_ou_404(db, models.Operateur, matricule.upper(), "Opérateur introuvable.")
    atelier = db.scalar(select(models.Atelier).where(models.Atelier.matricule_responsable == operateur.matricule))
    if atelier:
        raise conflit(f"Impossible : cet opérateur est responsable de l'atelier {atelier.libelle}.")
    equipe = db.scalar(select(models.Equipe).where(models.Equipe.matricule_responsable == operateur.matricule))
    if equipe:
        raise conflit(f"Impossible : cet opérateur est responsable de l'équipe {equipe.libelle}.")
    if operateur.lots or operateur.maintenances:
        raise conflit(
            f"Impossible : cet opérateur a participé à {len(operateur.lots)} lot(s) "
            f"et {len(operateur.maintenances)} maintenance(s)."
        )
    compte = db.scalar(select(models.Utilisateur).where(models.Utilisateur.matricule == operateur.matricule))
    if compte:
        raise conflit(f"Impossible : le compte utilisateur « {compte.login} » est lié à cet opérateur.")
    db.delete(operateur)
    db.commit()
