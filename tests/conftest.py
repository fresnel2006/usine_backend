"""Tests sur la vraie base (celle de DATABASE_URL, ou TEST_DATABASE_URL si définie).

Chaque test s'exécute dans une transaction annulée à la fin : la base n'est jamais modifiée.
"""
import os

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.config import settings
from app.database import get_db
from app.main import app
from app.models import Utilisateur
from app.routers.auth import reinitialiser_echecs
from app.security import creer_jeton

moteur = create_engine(os.environ.get("TEST_DATABASE_URL", settings.database_url))


@pytest.fixture
def db():
    connexion = moteur.connect()
    transaction = connexion.begin()
    session = Session(bind=connexion, join_transaction_mode="create_savepoint", expire_on_commit=False)
    yield session
    session.close()
    transaction.rollback()
    connexion.close()


@pytest.fixture(autouse=True)
def compteur_de_connexion_vide():
    """Les échecs de connexion sont comptés en mémoire : chaque test repart de zéro."""
    reinitialiser_echecs()
    yield
    reinitialiser_echecs()


@pytest.fixture
def client(db):
    app.dependency_overrides[get_db] = lambda: db
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()


@pytest.fixture
def entetes(db):
    """entetes("admin") -> en-tête Authorization pour ce compte du jeu de données."""

    def fabriquer(login: str) -> dict:
        return {"Authorization": f"Bearer {creer_jeton(db.get(Utilisateur, login))}"}

    return fabriquer
