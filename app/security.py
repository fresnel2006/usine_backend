"""Authentification JWT, hachage bcrypt et contrôle des droits par rôle."""
from datetime import datetime, timedelta, timezone

import bcrypt
import jwt
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session

from app.config import settings
from app.database import get_db
from app.models import Maintenance, Utilisateur

ADMIN = "ADMINISTRATEUR"
RESP_ATELIER = "RESPONSABLE_ATELIER"
COLLAB_RESP = "COLLABORATEUR_RESPONSABLE"
OPERATEUR = "OPERATEUR"
ROLES = (ADMIN, RESP_ATELIER, COLLAB_RESP, OPERATEUR)

MESSAGE_INTERDIT = "Vous n'avez pas les droits pour effectuer cette action."

# ---------------------------------------------------------------------
# Matrice des droits (section 4 du document « Rôles, profils, pages et droits »).
# Copie conforme dans frontend/src/utils/permissions.js : les deux doivent rester identiques
# (vérifié par tests/test_droits.py).
# Le collaborateur responsable est une spécialisation de l'opérateur : il reprend tous ses droits.
# ---------------------------------------------------------------------
CREER, LIRE, MODIFIER, SUPPRIMER = "creer", "lire", "modifier", "supprimer"
TOUS = ROLES
_PRODUCTION = (ADMIN, RESP_ATELIER)
_PERSONNEL = (ADMIN, COLLAB_RESP)
_TERRAIN = (ADMIN, COLLAB_RESP, OPERATEUR)


def _crud(ecriture: tuple[str, ...], lecture: tuple[str, ...] = TOUS) -> dict[str, tuple[str, ...]]:
    return {CREER: ecriture, LIRE: lecture, MODIFIER: ecriture, SUPPRIMER: ecriture}


DROITS: dict[str, dict[str, tuple[str, ...]]] = {
    "ateliers": _crud(_PRODUCTION),
    "lignes": _crud(_PRODUCTION),
    "lots": _crud(_PRODUCTION),
    "produits": _crud(_PRODUCTION),
    "operateurs": _crud(_PERSONNEL),
    "equipes": _crud(_PERSONNEL),
    "types_incident": _crud(_PERSONNEL),
    # L'opérateur déclare un incident mais ne peut ni le modifier ni le supprimer
    "incidents": {CREER: _TERRAIN, LIRE: TOUS, MODIFIER: _PERSONNEL, SUPPRIMER: _PERSONNEL},
    "machines": _crud(_TERRAIN),
    # L'opérateur modifie seulement les maintenances qu'il a effectuées (voir verifier_membre_maintenance)
    "maintenances": {CREER: _TERRAIN, LIRE: TOUS, MODIFIER: _TERRAIN, SUPPRIMER: _PERSONNEL},
    "pieces_consommees": {CREER: _TERRAIN, LIRE: TOUS, MODIFIER: _TERRAIN, SUPPRIMER: _PERSONNEL},
    "pieces": _crud(_TERRAIN),
    "nomenclature": _crud(_TERRAIN),
    "achats": {CREER: _TERRAIN, LIRE: TOUS, MODIFIER: _TERRAIN, SUPPRIMER: _PERSONNEL},
    "fournisseurs": _crud((ADMIN,)),
    "utilisateurs": _crud((ADMIN,), lecture=(ADMIN,)),
    "profil": {CREER: (), LIRE: TOUS, MODIFIER: TOUS, SUPPRIMER: ()},
}

bearer = HTTPBearer(auto_error=False, description="Jeton obtenu via POST /api/auth/login")


def hacher_mot_de_passe(mot_de_passe: str) -> str:
    return bcrypt.hashpw(mot_de_passe.encode("utf-8"), bcrypt.gensalt(rounds=12)).decode("utf-8")


def verifier_mot_de_passe(mot_de_passe: str, empreinte: str) -> bool:
    try:
        return bcrypt.checkpw(mot_de_passe.encode("utf-8"), empreinte.encode("utf-8"))
    except ValueError:
        # Empreinte invalide (par exemple les fausses empreintes du script SQL)
        return False


def creer_jeton(utilisateur: Utilisateur) -> str:
    expiration = datetime.now(timezone.utc) + timedelta(minutes=settings.jwt_expire_minutes)
    charge = {
        "sub": utilisateur.login,
        "role": utilisateur.role,
        "matricule": utilisateur.matricule,
        "exp": expiration,
    }
    return jwt.encode(charge, settings.jwt_secret, algorithm=settings.jwt_algorithm)


def get_current_user(
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer),
    db: Session = Depends(get_db),
) -> Utilisateur:
    non_authentifie = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Authentification requise. Veuillez vous connecter.",
        headers={"WWW-Authenticate": "Bearer"},
    )
    if credentials is None:
        raise non_authentifie
    try:
        charge = jwt.decode(credentials.credentials, settings.jwt_secret, algorithms=[settings.jwt_algorithm])
    except jwt.ExpiredSignatureError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Votre session a expiré, veuillez vous reconnecter.",
            headers={"WWW-Authenticate": "Bearer"},
        )
    except jwt.PyJWTError:
        raise non_authentifie
    utilisateur = db.get(Utilisateur, charge.get("sub"))
    if utilisateur is None:
        raise non_authentifie
    if not utilisateur.actif:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Ce compte est désactivé. Contactez l'administrateur.",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return utilisateur


def interdit(detail: str = MESSAGE_INTERDIT) -> HTTPException:
    return HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=detail)


def require_roles(*roles: str):
    """Dépendance : refuse la requête (403) si le rôle de l'utilisateur n'est pas autorisé."""

    def verifier(utilisateur: Utilisateur = Depends(get_current_user)) -> Utilisateur:
        if utilisateur.role not in roles:
            raise interdit()
        return utilisateur

    return verifier


def autoriser(ressource: str, action: str):
    """Dépendance construite à partir de la matrice DROITS : autoriser("ateliers", CREER)."""
    return require_roles(*DROITS[ressource][action])


def verifier_membre_maintenance(utilisateur: Utilisateur, maintenance: Maintenance) -> None:
    """Un opérateur ne modifie que les maintenances qu'il a effectuées (table effectuer)."""
    if utilisateur.role != OPERATEUR:
        return
    if utilisateur.matricule not in {o.matricule for o in maintenance.operateurs}:
        raise interdit(
            f"{MESSAGE_INTERDIT} Vous ne pouvez modifier que les maintenances que vous avez effectuées."
        )
