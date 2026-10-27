"""Gestionnaires d'erreurs : messages en français et codes HTTP cohérents."""
from fastapi import FastAPI, Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from sqlalchemy.exc import IntegrityError

NOMS_CHAMPS = {
    "mot_de_passe": "mot de passe",
    "date_entree": "date d'entrée",
    "date_production": "date de production",
    "date_heure_debut": "date et heure de début",
    "date_achat": "date d'achat",
    "prix_vente_unitaire": "prix de vente unitaire",
    "prix_unitaire_ht": "prix unitaire HT",
    "prix_achat": "prix d'achat",
    "quantite_stock": "quantité en stock",
    "nb_operateurs_necessaires": "nombre d'opérateurs nécessaires",
    "temps_arret": "temps d'arrêt",
    "ancien_mot_de_passe": "ancien mot de passe",
    "nouveau_mot_de_passe": "nouveau mot de passe",
    "matricule_responsable": "responsable",
    "reference_piece": "pièce",
    "reference_composant": "composant",
    "code_fournisseur": "fournisseur",
    "raison_sociale": "raison sociale",
    "num_machine": "machine",
    "num_lot": "lot",
    "code_type": "type d'incident",
}


def _nombre(v) -> str:
    if isinstance(v, float) and v.is_integer():
        v = int(v)
    return f"{v:,}".replace(",", " ") if isinstance(v, int) else str(v)


def _message(erreur: dict) -> str:
    type_ = erreur.get("type", "")
    ctx = erreur.get("ctx") or {}
    if type_ == "missing":
        return "Ce champ est obligatoire."
    if type_ == "string_too_short":
        if ctx.get("min_length") == 1:
            return "Ce champ est obligatoire."
        return f"Au moins {ctx.get('min_length')} caractères."
    if type_ == "string_too_long":
        return f"Au plus {ctx.get('max_length')} caractères."
    if type_ == "greater_than":
        return f"La valeur doit être supérieure à {_nombre(ctx.get('gt'))}."
    if type_ == "greater_than_equal":
        return f"La valeur doit être supérieure ou égale à {_nombre(ctx.get('ge'))}."
    if type_ == "less_than_equal":
        return f"La valeur doit être inférieure ou égale à {_nombre(ctx.get('le'))}."
    if type_ in ("int_parsing", "int_type", "int_from_float"):
        return "Un nombre entier est attendu."
    if type_ in ("float_parsing", "decimal_parsing", "float_type", "decimal_type"):
        return "Un nombre est attendu."
    if type_ in ("decimal_max_places", "decimal_max_digits", "decimal_whole_digits"):
        return "Le nombre a trop de chiffres."
    if type_.startswith("date") and "datetime" not in type_:
        return "Date invalide (format attendu : AAAA-MM-JJ)."
    if type_.startswith("datetime"):
        return "Date et heure invalides."
    if type_ in ("too_short",):
        return f"Au moins {ctx.get('min_length')} élément(s) requis."
    if type_ in ("literal_error", "enum"):
        return "Valeur non autorisée."
    if type_ in ("bool_parsing", "bool_type"):
        return "Vrai ou faux attendu."
    if type_ == "string_pattern_mismatch":
        return "Format invalide."
    if type_ == "value_error":
        return str(erreur.get("msg", "")).removeprefix("Value error, ")
    if type_ == "json_invalid":
        return "Le corps de la requête n'est pas un JSON valide."
    return "Valeur invalide."


def installer_gestionnaires(app: FastAPI) -> None:
    @app.exception_handler(RequestValidationError)
    async def erreur_validation(_: Request, exc: RequestValidationError):
        erreurs = []
        for e in exc.errors():
            loc = [str(x) for x in e.get("loc", ()) if x not in ("body", "query", "path")]
            champ = ".".join(loc)
            erreurs.append({"champ": champ, "message": _message(e)})
        premier = erreurs[0] if erreurs else {"champ": "", "message": "Données invalides."}
        nom = NOMS_CHAMPS.get(premier["champ"].split(".")[0], premier["champ"])
        detail = f"{nom} : {premier['message']}" if nom else premier["message"]
        return JSONResponse(
            status_code=422,
            content={"detail": f"Données invalides - {detail}", "erreurs": erreurs},
        )

    @app.exception_handler(IntegrityError)
    async def erreur_integrite(_: Request, exc: IntegrityError):
        # Filet de sécurité : les routeurs vérifient déjà les cas courants avec un message précis.
        code = getattr(getattr(exc, "orig", None), "pgcode", None)
        if code == "23505":
            message = "Cet enregistrement existe déjà (doublon)."
        elif code == "23503":
            message = "Opération impossible : cet enregistrement est lié à d'autres données."
        elif code == "23514":
            message = "Une valeur ne respecte pas les règles de la base (valeur négative ou nulle)."
        else:
            message = "Opération refusée par la base de données."
        return JSONResponse(status_code=status.HTTP_409_CONFLICT, content={"detail": message})
