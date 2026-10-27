"""Modèles SQLAlchemy : correspondance exacte avec database/gestion_usine.sql (18 tables)."""
from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Column,
    Date,
    DateTime,
    ForeignKey,
    Integer,
    Numeric,
    String,
    Table,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base

# ---------------------------------------------------------------------
# Tables d'association simples
# ---------------------------------------------------------------------
participer = Table(
    "participer",
    Base.metadata,
    Column("num_lot", Integer, ForeignKey("lot_production.num_lot", ondelete="CASCADE"), primary_key=True),
    Column("matricule", String(10), ForeignKey("operateur.matricule"), primary_key=True),
)

effectuer = Table(
    "effectuer",
    Base.metadata,
    Column(
        "num_maintenance",
        Integer,
        ForeignKey("maintenance.num_maintenance", ondelete="CASCADE"),
        primary_key=True,
    ),
    Column("matricule", String(10), ForeignKey("operateur.matricule"), primary_key=True),
)


# ---------------------------------------------------------------------
# 1. Equipes et opérateurs
# ---------------------------------------------------------------------
class Equipe(Base):
    __tablename__ = "equipe"

    num_equipe: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=False)
    libelle: Mapped[str] = mapped_column(String(100), nullable=False)
    matricule_responsable: Mapped[str | None] = mapped_column(
        String(10),
        ForeignKey("operateur.matricule", name="fk_equipe_responsable", use_alter=True),
        unique=True,
    )

    responsable: Mapped["Operateur | None"] = relationship(foreign_keys=[matricule_responsable])
    operateurs: Mapped[list["Operateur"]] = relationship(
        back_populates="equipe", foreign_keys="Operateur.num_equipe"
    )


class Operateur(Base):
    __tablename__ = "operateur"

    matricule: Mapped[str] = mapped_column(String(10), primary_key=True)
    nom: Mapped[str] = mapped_column(String(60), nullable=False)
    prenom: Mapped[str] = mapped_column(String(80), nullable=False)
    date_entree: Mapped[date] = mapped_column(Date, nullable=False)
    num_equipe: Mapped[int] = mapped_column(Integer, ForeignKey("equipe.num_equipe"), nullable=False)

    equipe: Mapped[Equipe] = relationship(back_populates="operateurs", foreign_keys=[num_equipe])
    lots: Mapped[list["LotProduction"]] = relationship(secondary=participer, back_populates="operateurs")
    maintenances: Mapped[list["Maintenance"]] = relationship(secondary=effectuer, back_populates="operateurs")

    @property
    def nom_complet(self) -> str:
        return f"{self.nom} {self.prenom}"


# ---------------------------------------------------------------------
# 2. Ateliers, lignes de production et machines
# ---------------------------------------------------------------------
class Atelier(Base):
    __tablename__ = "atelier"

    num_atelier: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=False)
    libelle: Mapped[str] = mapped_column(String(100), nullable=False)
    matricule_responsable: Mapped[str] = mapped_column(
        String(10), ForeignKey("operateur.matricule"), nullable=False, unique=True
    )

    responsable: Mapped[Operateur] = relationship()
    lignes: Mapped[list["LigneProduction"]] = relationship(back_populates="atelier")


class LigneProduction(Base):
    __tablename__ = "ligne_production"
    __table_args__ = (CheckConstraint("nb_operateurs_necessaires > 0"),)

    num_ligne: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=False)
    nb_operateurs_necessaires: Mapped[int] = mapped_column(Integer, nullable=False)
    num_atelier: Mapped[int] = mapped_column(Integer, ForeignKey("atelier.num_atelier"), nullable=False)

    atelier: Mapped[Atelier] = relationship(back_populates="lignes")
    machines: Mapped[list["Machine"]] = relationship(back_populates="ligne")
    lots: Mapped[list["LotProduction"]] = relationship(back_populates="ligne")


class Machine(Base):
    __tablename__ = "machine"

    num_machine: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=False)
    designation: Mapped[str] = mapped_column(String(100), nullable=False)
    num_ligne: Mapped[int] = mapped_column(Integer, ForeignKey("ligne_production.num_ligne"), nullable=False)

    ligne: Mapped[LigneProduction] = relationship(back_populates="machines")
    maintenances: Mapped[list["Maintenance"]] = relationship(back_populates="machine")


# ---------------------------------------------------------------------
# 3. Produits et lots de production
# ---------------------------------------------------------------------
class Produit(Base):
    __tablename__ = "produit"
    __table_args__ = (
        CheckConstraint("prix_vente_unitaire >= 0"),
        CheckConstraint("quantite_stock >= 0"),
    )

    reference: Mapped[str] = mapped_column(String(20), primary_key=True)
    designation: Mapped[str] = mapped_column(String(100), nullable=False)
    prix_vente_unitaire: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)
    quantite_stock: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    lots: Mapped[list["LotProduction"]] = relationship(back_populates="produit")


class LotProduction(Base):
    __tablename__ = "lot_production"

    num_lot: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=False)
    date_production: Mapped[date] = mapped_column(Date, nullable=False)
    num_ligne: Mapped[int] = mapped_column(Integer, ForeignKey("ligne_production.num_ligne"), nullable=False)
    reference_produit: Mapped[str] = mapped_column(String(20), ForeignKey("produit.reference"), nullable=False)

    ligne: Mapped[LigneProduction] = relationship(back_populates="lots")
    produit: Mapped[Produit] = relationship(back_populates="lots")
    operateurs: Mapped[list[Operateur]] = relationship(secondary=participer, back_populates="lots")
    incidents: Mapped[list["Incident"]] = relationship(back_populates="lot")


# ---------------------------------------------------------------------
# 4. Incidents
# ---------------------------------------------------------------------
class TypeIncident(Base):
    __tablename__ = "type_incident"

    code_type: Mapped[str] = mapped_column(String(10), primary_key=True)
    libelle: Mapped[str] = mapped_column(String(100), nullable=False)

    incidents: Mapped[list["Incident"]] = relationship(back_populates="type_incident")


class Incident(Base):
    __tablename__ = "incident"
    __table_args__ = (CheckConstraint("temps_arret > 0"),)

    num_incident: Mapped[int] = mapped_column(Integer, primary_key=True)  # SERIAL
    temps_arret: Mapped[int] = mapped_column(Integer, nullable=False)
    num_lot: Mapped[int] = mapped_column(Integer, ForeignKey("lot_production.num_lot"), nullable=False)
    code_type: Mapped[str] = mapped_column(String(10), ForeignKey("type_incident.code_type"), nullable=False)

    lot: Mapped[LotProduction] = relationship(back_populates="incidents")
    type_incident: Mapped[TypeIncident] = relationship(back_populates="incidents")


# ---------------------------------------------------------------------
# 5. Maintenance des machines
# ---------------------------------------------------------------------
class Maintenance(Base):
    __tablename__ = "maintenance"
    __table_args__ = (CheckConstraint("duree > 0"),)

    num_maintenance: Mapped[int] = mapped_column(Integer, primary_key=True)  # SERIAL
    date_heure_debut: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    duree: Mapped[int] = mapped_column(Integer, nullable=False)
    num_machine: Mapped[int] = mapped_column(Integer, ForeignKey("machine.num_machine"), nullable=False)

    machine: Mapped[Machine] = relationship(back_populates="maintenances")
    operateurs: Mapped[list[Operateur]] = relationship(secondary=effectuer, back_populates="maintenances")
    consommations: Mapped[list["Consommer"]] = relationship(
        back_populates="maintenance", cascade="all, delete-orphan", passive_deletes=True
    )


# ---------------------------------------------------------------------
# 6. Pièces, nomenclature et consommation
# ---------------------------------------------------------------------
class Piece(Base):
    __tablename__ = "piece"
    __table_args__ = (
        CheckConstraint("prix_unitaire_ht >= 0"),
        CheckConstraint("quantite_stock >= 0"),
    )

    reference: Mapped[str] = mapped_column(String(20), primary_key=True)
    libelle: Mapped[str] = mapped_column(String(100), nullable=False)
    prix_unitaire_ht: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)
    quantite_stock: Mapped[int] = mapped_column(Integer, nullable=False, default=0)


class Consommer(Base):
    __tablename__ = "consommer"
    __table_args__ = (CheckConstraint("quantite > 0"),)

    num_maintenance: Mapped[int] = mapped_column(
        Integer, ForeignKey("maintenance.num_maintenance", ondelete="CASCADE"), primary_key=True
    )
    reference_piece: Mapped[str] = mapped_column(String(20), ForeignKey("piece.reference"), primary_key=True)
    quantite: Mapped[int] = mapped_column(Integer, nullable=False)

    maintenance: Mapped[Maintenance] = relationship(back_populates="consommations")
    piece: Mapped[Piece] = relationship()


class Nomenclature(Base):
    __tablename__ = "nomenclature"
    __table_args__ = (
        CheckConstraint("quantite > 0"),
        CheckConstraint("reference_composee <> reference_composant"),
    )

    reference_composee: Mapped[str] = mapped_column(String(20), ForeignKey("piece.reference"), primary_key=True)
    reference_composant: Mapped[str] = mapped_column(String(20), ForeignKey("piece.reference"), primary_key=True)
    quantite: Mapped[int] = mapped_column(Integer, nullable=False)

    composee: Mapped[Piece] = relationship(foreign_keys=[reference_composee])
    composant: Mapped[Piece] = relationship(foreign_keys=[reference_composant])


# ---------------------------------------------------------------------
# 7. Fournisseurs et achats
# ---------------------------------------------------------------------
class Fournisseur(Base):
    __tablename__ = "fournisseur"

    code_fournisseur: Mapped[str] = mapped_column(String(10), primary_key=True)
    raison_sociale: Mapped[str] = mapped_column(String(120), nullable=False)
    adresse: Mapped[str | None] = mapped_column(String(200))
    telephone: Mapped[str | None] = mapped_column(String(20))


class Achat(Base):
    __tablename__ = "achat"
    __table_args__ = (
        CheckConstraint("prix_achat >= 0"),
        CheckConstraint("quantite > 0"),
    )

    reference_piece: Mapped[str] = mapped_column(String(20), ForeignKey("piece.reference"), primary_key=True)
    code_fournisseur: Mapped[str] = mapped_column(
        String(10), ForeignKey("fournisseur.code_fournisseur"), primary_key=True
    )
    date_achat: Mapped[date] = mapped_column(Date, primary_key=True)
    prix_achat: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)
    quantite: Mapped[int] = mapped_column(Integer, nullable=False, default=1)

    piece: Mapped[Piece] = relationship()
    fournisseur: Mapped[Fournisseur] = relationship()


# ---------------------------------------------------------------------
# 8. Comptes utilisateurs
# ---------------------------------------------------------------------
class Utilisateur(Base):
    __tablename__ = "utilisateur"

    login: Mapped[str] = mapped_column(String(40), primary_key=True)
    mot_de_passe: Mapped[str] = mapped_column(String(255), nullable=False)
    role: Mapped[str] = mapped_column(String(30), nullable=False)
    matricule: Mapped[str | None] = mapped_column(String(10), ForeignKey("operateur.matricule"))
    actif: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)

    operateur: Mapped[Operateur | None] = relationship()
