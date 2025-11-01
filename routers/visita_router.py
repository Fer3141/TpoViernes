# routers/visita_router.py

from fastapi import APIRouter, HTTPException, Depends
from motor.motor_asyncio import AsyncIOMotorClient
from typing import Annotated
from schemas.visita import VisitaInput # Importamos el nuevo modelo
from services import visita_service # Importamos el nuevo servicio

# ----------------------------------------------------
# Dependency Injection (Asumimos que main.py define get_mongo_db)
# ----------------------------------------------------
def get_mongo_db():
    from main import mongo_db
    if mongo_db is None: 
        raise HTTPException(503, "MongoDB no conectado")
    return mongo_db
# ----------------------------------------------------

router = APIRouter(tags=["Visitas y Historia Clínica"])

@router.post("/visitas")
async def registrar_visita(
    visita: VisitaInput, 
    db: Annotated[AsyncIOMotorClient, Depends(get_mongo_db)]
):
    """
    Registra una nueva visita médica en el sistema de Historia Clínica.
    Actualiza el campo 'ultima_consulta_id' en el documento del paciente (Req 1).
    """
    # Usamos by_alias=True para asegurarnos de que el campo 'id' se convierte en '_id'
    visita_dict = visita.dict(exclude_none=True, by_alias=True)
    
    return await visita_service.crear_visita(db, visita_dict)