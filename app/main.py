from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.config import settings
from app.errors import installer_gestionnaires
from app.routers import (
    achats,
    ateliers,
    auth,
    dashboard,
    equipes,
    fournisseurs,
    incidents,
    lignes,
    lots,
    machines,
    maintenances,
    operateurs,
    pieces,
    produits,
    profil,
    types_incident,
    utilisateurs,
)

app = FastAPI(
    title="API Gestion de l'usine",
    description=(
        "API REST de l'application de gestion de l'usine Akwaba Agro-Industrie "
        "(projet Agile TWIN 3 - ESATIC). Connectez-vous via POST /api/auth/login, "
        "puis cliquez sur Authorize et collez le jeton obtenu."
    ),
    version="1.0.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origin_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

installer_gestionnaires(app)

for module in (
    auth,
    profil,
    dashboard,
    ateliers,
    lignes,
    lots,
    produits,
    operateurs,
    equipes,
    types_incident,
    incidents,
    machines,
    maintenances,
    pieces,
    achats,
    fournisseurs,
    utilisateurs,
):
    app.include_router(module.router)


@app.get("/", tags=["Santé"], summary="Vérifier que l'API répond")
def racine():
    return {"application": "Gestion de l'usine", "statut": "en ligne", "documentation": "/docs"}
