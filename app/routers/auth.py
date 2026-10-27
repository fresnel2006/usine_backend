from datetime import datetime, timedelta
from threading import Lock

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import Utilisateur
from app.schemas import Jeton, LoginIn, UtilisateurConnecte
from app.security import creer_jeton, get_current_user, verifier_mot_de_passe

router = APIRouter(prefix="/api/auth", tags=["Authentification"])

MAX_ECHECS = 5
DUREE_BLOCAGE = timedelta(minutes=5)

# Échecs de connexion consécutifs par identifiant : login -> (nombre, bloqué jusqu'à)
_echecs: dict[str, tuple[int, datetime | None]] = {}
_verrou = Lock()


def _bloque_jusqua(login: str) -> datetime | None:
    with _verrou:
        _, jusqua = _echecs.get(login, (0, None))
        if jusqua and jusqua <= datetime.now():
            _echecs.pop(login, None)
            return None
        return jusqua


def _noter_echec(login: str) -> None:
    with _verrou:
        nombre, _ = _echecs.get(login, (0, None))
        nombre += 1
        _echecs[login] = (nombre, datetime.now() + DUREE_BLOCAGE if nombre >= MAX_ECHECS else None)


def reinitialiser_echecs(login: str | None = None) -> None:
    """Efface le compteur d'un identifiant (ou de tous, pour les tests)."""
    with _verrou:
        if login is None:
            _echecs.clear()
        else:
            _echecs.pop(login, None)


def utilisateur_connecte(u: Utilisateur) -> dict:
    return {
        "login": u.login,
        "role": u.role,
        "matricule": u.matricule,
        "nom_complet": u.operateur.nom_complet if u.operateur else None,
    }


@router.post("/login", response_model=Jeton, summary="Se connecter et obtenir un jeton JWT (valable 8 heures)")
def login(donnees: LoginIn, db: Session = Depends(get_db)):
    identifiant = donnees.login.lower()
    if _bloque_jusqua(identifiant):
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Trop de tentatives, réessayez dans 5 minutes.",
        )
    utilisateur = db.get(Utilisateur, identifiant)
    if utilisateur is None or not verifier_mot_de_passe(donnees.mot_de_passe, utilisateur.mot_de_passe):
        _noter_echec(identifiant)
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Identifiant ou mot de passe incorrect.",
        )
    if not utilisateur.actif:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Ce compte est désactivé. Contactez l'administrateur.",
        )
    reinitialiser_echecs(identifiant)
    return {"access_token": creer_jeton(utilisateur), "utilisateur": utilisateur_connecte(utilisateur)}


@router.get("/me", response_model=UtilisateurConnecte, summary="Utilisateur connecté")
def moi(utilisateur: Utilisateur = Depends(get_current_user)):
    return utilisateur_connecte(utilisateur)
