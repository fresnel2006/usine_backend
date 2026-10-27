from fastapi import APIRouter, Depends, status
from sqlalchemy import func, select
from sqlalchemy.orm import Session, selectinload

from app import models
from app.database import get_db
from app.schemas import MotDePasseReset, UtilisateurIn, UtilisateurOut, UtilisateurUpdate
from app.security import ADMIN, CREER, LIRE, MODIFIER, SUPPRIMER, autoriser, hacher_mot_de_passe, interdit
from app.serializers import conflit, obtenir_ou_404, requete_invalide, utilisateur_out

router = APIRouter(prefix="/api/utilisateurs", tags=["Utilisateurs"])


def obtenir_utilisateur(db: Session, login: str) -> models.Utilisateur:
    return obtenir_ou_404(db, models.Utilisateur, login.lower(), "Compte introuvable.")


def verifier_matricule(db: Session, role: str, matricule: str | None, login: str | None) -> str | None:
    """Chaque compte, sauf l'Administrateur, est lié à un opérateur, et un opérateur n'a qu'un compte."""
    if role == ADMIN:
        return None
    if not matricule:
        raise requete_invalide("Choisissez l'opérateur lié à ce compte.")
    obtenir_ou_404(db, models.Operateur, matricule, f"Opérateur {matricule} introuvable.")
    autre = db.scalar(select(models.Utilisateur).where(models.Utilisateur.matricule == matricule))
    if autre is not None and autre.login != login:
        raise conflit(f"L'opérateur {matricule} a déjà un compte : « {autre.login} ».")
    return matricule


def verifier_admin_restant(db: Session, compte: models.Utilisateur) -> None:
    """Il doit toujours rester au moins un Administrateur actif."""
    if compte.role != ADMIN or not compte.actif:
        return
    autres = db.scalar(
        select(func.count())
        .select_from(models.Utilisateur)
        .where(
            models.Utilisateur.role == ADMIN,
            models.Utilisateur.actif.is_(True),
            models.Utilisateur.login != compte.login,
        )
    )
    if not autres:
        raise conflit("Impossible : il doit toujours rester au moins un Administrateur actif.")


@router.get("", response_model=list[UtilisateurOut], summary="Liste des comptes")
def lister(db: Session = Depends(get_db), _=Depends(autoriser("utilisateurs", LIRE))):
    comptes = db.scalars(
        select(models.Utilisateur)
        .options(selectinload(models.Utilisateur.operateur).selectinload(models.Operateur.equipe))
        .order_by(models.Utilisateur.login)
    ).all()
    return [utilisateur_out(u) for u in comptes]


@router.post("", response_model=UtilisateurOut, status_code=status.HTTP_201_CREATED, summary="Créer un compte")
def creer(donnees: UtilisateurIn, db: Session = Depends(get_db), _=Depends(autoriser("utilisateurs", CREER))):
    if db.get(models.Utilisateur, donnees.login):
        raise conflit(f"L'identifiant « {donnees.login} » est déjà utilisé.")
    compte = models.Utilisateur(
        login=donnees.login,
        mot_de_passe=hacher_mot_de_passe(donnees.mot_de_passe),
        role=donnees.role,
        matricule=verifier_matricule(db, donnees.role, donnees.matricule, None),
        actif=donnees.actif,
    )
    db.add(compte)
    db.commit()
    db.refresh(compte)
    return utilisateur_out(compte)


@router.put("/{login}", response_model=UtilisateurOut, summary="Modifier un compte : rôle, opérateur lié, statut")
def modifier(
    login: str,
    donnees: UtilisateurUpdate,
    db: Session = Depends(get_db),
    moi: models.Utilisateur = Depends(autoriser("utilisateurs", MODIFIER)),
):
    compte = obtenir_utilisateur(db, login)
    if compte.login == moi.login:
        if donnees.role != compte.role:
            raise interdit("Vous ne pouvez pas modifier votre propre rôle.")
        if not donnees.actif:
            raise interdit("Vous ne pouvez pas désactiver votre propre compte.")
    if donnees.role != ADMIN or not donnees.actif:
        verifier_admin_restant(db, compte)
    compte.matricule = verifier_matricule(db, donnees.role, donnees.matricule, compte.login)
    compte.role = donnees.role
    compte.actif = donnees.actif
    db.commit()
    db.refresh(compte)
    return utilisateur_out(compte)


def changer_statut(db: Session, login: str, moi: models.Utilisateur, actif: bool) -> dict:
    compte = obtenir_utilisateur(db, login)
    if compte.login == moi.login and not actif:
        raise interdit("Vous ne pouvez pas désactiver votre propre compte.")
    if not actif:
        verifier_admin_restant(db, compte)
    compte.actif = actif
    db.commit()
    db.refresh(compte)
    return utilisateur_out(compte)


@router.post("/{login}/desactiver", response_model=UtilisateurOut, summary="Désactiver un compte")
def desactiver(
    login: str, db: Session = Depends(get_db), moi: models.Utilisateur = Depends(autoriser("utilisateurs", MODIFIER))
):
    return changer_statut(db, login, moi, False)


@router.post("/{login}/reactiver", response_model=UtilisateurOut, summary="Réactiver un compte")
def reactiver(
    login: str, db: Session = Depends(get_db), moi: models.Utilisateur = Depends(autoriser("utilisateurs", MODIFIER))
):
    return changer_statut(db, login, moi, True)


@router.put("/{login}/mot-de-passe", response_model=UtilisateurOut, summary="Réinitialiser le mot de passe d'un compte")
def reinitialiser_mot_de_passe(
    login: str,
    donnees: MotDePasseReset,
    db: Session = Depends(get_db),
    _=Depends(autoriser("utilisateurs", MODIFIER)),
):
    compte = obtenir_utilisateur(db, login)
    compte.mot_de_passe = hacher_mot_de_passe(donnees.mot_de_passe)
    db.commit()
    db.refresh(compte)
    return utilisateur_out(compte)


@router.delete("/{login}", status_code=status.HTTP_204_NO_CONTENT, summary="Supprimer un compte")
def supprimer(
    login: str, db: Session = Depends(get_db), moi: models.Utilisateur = Depends(autoriser("utilisateurs", SUPPRIMER))
):
    compte = obtenir_utilisateur(db, login)
    if compte.login == moi.login:
        raise interdit("Vous ne pouvez pas supprimer votre propre compte.")
    verifier_admin_restant(db, compte)
    db.delete(compte)
    db.commit()
