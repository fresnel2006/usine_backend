from datetime import date, datetime, time

from fastapi import APIRouter, Depends, status
from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app import models
from app.database import get_db
from app.schemas import MaintenanceIn, MaintenanceOut, MaintenanceUpdate, PieceConsommeeIn, QuantiteIn
from app.security import (
    CREER,
    MODIFIER,
    SUPPRIMER,
    autoriser,
    get_current_user,
    verifier_membre_maintenance,
)
from app.serializers import (
    charger_operateurs,
    conflit,
    maintenance_out,
    obtenir_ou_404,
    piece_verrouillee,
    stock_insuffisant,
)

router = APIRouter(prefix="/api/maintenances", tags=["Maintenances"])

CHARGEMENT_MAINTENANCE = (
    selectinload(models.Maintenance.machine),
    selectinload(models.Maintenance.operateurs),
    selectinload(models.Maintenance.consommations).selectinload(models.Consommer.piece),
)


def obtenir_maintenance(db: Session, num_maintenance: int) -> models.Maintenance:
    return obtenir_ou_404(db, models.Maintenance, num_maintenance, "Maintenance introuvable.")


@router.get("", response_model=list[MaintenanceOut], summary="Liste des maintenances (filtres : machine, opérateur, période)")
def lister(
    machine: int | None = None,
    operateur: str | None = None,
    debut: date | None = None,
    fin: date | None = None,
    db: Session = Depends(get_db),
    _=Depends(get_current_user),
):
    requete = select(models.Maintenance).options(*CHARGEMENT_MAINTENANCE)
    if machine is not None:
        requete = requete.where(models.Maintenance.num_machine == machine)
    if operateur:
        requete = requete.where(models.Maintenance.operateurs.any(models.Operateur.matricule == operateur.upper()))
    if debut:
        requete = requete.where(models.Maintenance.date_heure_debut >= datetime.combine(debut, time.min))
    if fin:
        requete = requete.where(models.Maintenance.date_heure_debut <= datetime.combine(fin, time.max))
    maintenances = db.scalars(requete.order_by(models.Maintenance.date_heure_debut.desc())).all()
    return [maintenance_out(m) for m in maintenances]


@router.get("/{num_maintenance}", response_model=MaintenanceOut, summary="Détail d'une maintenance")
def detail(num_maintenance: int, db: Session = Depends(get_db), _=Depends(get_current_user)):
    return maintenance_out(obtenir_maintenance(db, num_maintenance))


@router.post(
    "",
    response_model=MaintenanceOut,
    status_code=status.HTTP_201_CREATED,
    summary="Enregistrer une maintenance (les pièces consommées font baisser le stock)",
)
def creer(donnees: MaintenanceIn, db: Session = Depends(get_db), _=Depends(autoriser("maintenances", CREER))):
    obtenir_ou_404(db, models.Machine, donnees.num_machine, f"Machine {donnees.num_machine} introuvable.")
    operateurs = charger_operateurs(db, donnees.operateurs)

    # Tout est vérifié avant la moindre modification : la transaction est entière ou rien.
    pieces = []
    for p in donnees.pieces:
        piece = piece_verrouillee(db, p.reference_piece)
        if piece.quantite_stock < p.quantite:
            raise stock_insuffisant(piece, p.quantite)
        pieces.append((piece, p.quantite))

    maintenance = models.Maintenance(
        date_heure_debut=donnees.date_heure_debut, duree=donnees.duree, num_machine=donnees.num_machine
    )
    maintenance.operateurs = operateurs
    for piece, quantite in pieces:
        piece.quantite_stock -= quantite
        maintenance.consommations.append(models.Consommer(reference_piece=piece.reference, quantite=quantite))
    db.add(maintenance)
    db.commit()
    db.refresh(maintenance)
    return maintenance_out(maintenance)


@router.put("/{num_maintenance}", response_model=MaintenanceOut, summary="Modifier une maintenance")
def modifier(
    num_maintenance: int,
    donnees: MaintenanceUpdate,
    db: Session = Depends(get_db),
    utilisateur: models.Utilisateur = Depends(autoriser("maintenances", MODIFIER)),
):
    maintenance = obtenir_maintenance(db, num_maintenance)
    verifier_membre_maintenance(utilisateur, maintenance)
    obtenir_ou_404(db, models.Machine, donnees.num_machine, f"Machine {donnees.num_machine} introuvable.")
    maintenance.operateurs = charger_operateurs(db, donnees.operateurs)
    maintenance.num_machine = donnees.num_machine
    maintenance.date_heure_debut = donnees.date_heure_debut
    maintenance.duree = donnees.duree
    db.commit()
    db.refresh(maintenance)
    return maintenance_out(maintenance)


@router.delete(
    "/{num_maintenance}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Supprimer une maintenance (les pièces consommées retournent en stock)",
)
def supprimer(num_maintenance: int, db: Session = Depends(get_db), _=Depends(autoriser("maintenances", SUPPRIMER))):
    maintenance = obtenir_maintenance(db, num_maintenance)
    for c in maintenance.consommations:
        piece_verrouillee(db, c.reference_piece).quantite_stock += c.quantite
    db.delete(maintenance)
    db.commit()


# ---------------------------------------------------------------------
# Pièces consommées pendant une maintenance
# ---------------------------------------------------------------------
@router.post(
    "/{num_maintenance}/pieces",
    response_model=MaintenanceOut,
    status_code=status.HTTP_201_CREATED,
    summary="Noter une pièce consommée (le stock baisse)",
)
def ajouter_piece(
    num_maintenance: int,
    donnees: PieceConsommeeIn,
    db: Session = Depends(get_db),
    utilisateur: models.Utilisateur = Depends(autoriser("pieces_consommees", CREER)),
):
    maintenance = obtenir_maintenance(db, num_maintenance)
    verifier_membre_maintenance(utilisateur, maintenance)
    if db.get(models.Consommer, (num_maintenance, donnees.reference_piece)):
        raise conflit("Cette pièce est déjà notée pour cette maintenance : modifiez sa quantité.")
    piece = piece_verrouillee(db, donnees.reference_piece)
    if piece.quantite_stock < donnees.quantite:
        raise stock_insuffisant(piece, donnees.quantite)
    piece.quantite_stock -= donnees.quantite
    maintenance.consommations.append(
        models.Consommer(reference_piece=piece.reference, quantite=donnees.quantite)
    )
    db.commit()
    db.refresh(maintenance)
    return maintenance_out(maintenance)


@router.put(
    "/{num_maintenance}/pieces/{reference}",
    response_model=MaintenanceOut,
    summary="Modifier la quantité d'une pièce consommée (le stock est ajusté de la différence)",
)
def modifier_piece(
    num_maintenance: int,
    reference: str,
    donnees: QuantiteIn,
    db: Session = Depends(get_db),
    utilisateur: models.Utilisateur = Depends(autoriser("pieces_consommees", MODIFIER)),
):
    maintenance = obtenir_maintenance(db, num_maintenance)
    verifier_membre_maintenance(utilisateur, maintenance)
    consommation = obtenir_ou_404(
        db, models.Consommer, (num_maintenance, reference.upper()), "Cette pièce n'est pas notée pour cette maintenance."
    )
    piece = piece_verrouillee(db, consommation.reference_piece)
    ecart = donnees.quantite - consommation.quantite
    if ecart > piece.quantite_stock:
        raise stock_insuffisant(piece, ecart)
    piece.quantite_stock -= ecart
    consommation.quantite = donnees.quantite
    db.commit()
    db.refresh(maintenance)
    return maintenance_out(maintenance)


@router.delete(
    "/{num_maintenance}/pieces/{reference}",
    response_model=MaintenanceOut,
    summary="Retirer une pièce consommée (elle retourne en stock)",
)
def retirer_piece(
    num_maintenance: int,
    reference: str,
    db: Session = Depends(get_db),
    _=Depends(autoriser("pieces_consommees", SUPPRIMER)),
):
    maintenance = obtenir_maintenance(db, num_maintenance)
    consommation = obtenir_ou_404(
        db, models.Consommer, (num_maintenance, reference.upper()), "Cette pièce n'est pas notée pour cette maintenance."
    )
    piece_verrouillee(db, consommation.reference_piece).quantite_stock += consommation.quantite
    maintenance.consommations.remove(consommation)
    db.commit()
    db.refresh(maintenance)
    return maintenance_out(maintenance)
