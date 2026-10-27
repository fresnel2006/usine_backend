from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.orm import Session

from app import models
from app.database import get_db
from app.schemas import ChangementMotDePasse, Message, ProfilOut
from app.security import LIRE, MODIFIER, autoriser, hacher_mot_de_passe, verifier_mot_de_passe
from app.serializers import requete_invalide

router = APIRouter(prefix="/api/profil", tags=["Mon profil"])


def profil_out(db: Session, u: models.Utilisateur) -> dict:
    o = u.operateur
    atelier = equipe = None
    if o is not None:
        atelier = db.scalar(select(models.Atelier).where(models.Atelier.matricule_responsable == o.matricule))
        equipe = db.scalar(select(models.Equipe).where(models.Equipe.matricule_responsable == o.matricule))
    return {
        "login": u.login,
        "role": u.role,
        "matricule": u.matricule,
        "nom": o.nom if o else None,
        "prenom": o.prenom if o else None,
        "date_entree": o.date_entree if o else None,
        "num_equipe": o.num_equipe if o else None,
        "equipe_libelle": o.equipe.libelle if o else None,
        "atelier_responsable": {"numero": atelier.num_atelier, "libelle": atelier.libelle} if atelier else None,
        "equipe_responsable": {"numero": equipe.num_equipe, "libelle": equipe.libelle} if equipe else None,
    }


@router.get("", response_model=ProfilOut, summary="Mes informations")
def lire(db: Session = Depends(get_db), utilisateur: models.Utilisateur = Depends(autoriser("profil", LIRE))):
    return profil_out(db, utilisateur)


@router.put("/mot-de-passe", response_model=Message, summary="Changer mon mot de passe")
def changer_mot_de_passe(
    donnees: ChangementMotDePasse,
    db: Session = Depends(get_db),
    utilisateur: models.Utilisateur = Depends(autoriser("profil", MODIFIER)),
):
    if not verifier_mot_de_passe(donnees.ancien_mot_de_passe, utilisateur.mot_de_passe):
        raise requete_invalide("L'ancien mot de passe est incorrect.")
    if donnees.nouveau_mot_de_passe != donnees.confirmation:
        raise requete_invalide("La confirmation ne correspond pas au nouveau mot de passe.")
    if donnees.nouveau_mot_de_passe == donnees.ancien_mot_de_passe:
        raise requete_invalide("Le nouveau mot de passe doit être différent de l'ancien.")
    utilisateur.mot_de_passe = hacher_mot_de_passe(donnees.nouveau_mot_de_passe)
    db.commit()
    return {"detail": "Mot de passe modifié avec succès."}
