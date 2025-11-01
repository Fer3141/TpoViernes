# routers/habito_router.py

from fastapi import APIRouter, HTTPException, Depends
from motor.motor_asyncio import AsyncIOMotorClient
from typing import Annotated
from schemas.habito import HabitoInput 
from services import habito_service 

# ----------------------------------------------------
# Dependency Injection 
# ----------------------------------------------------
def get_mongo_db():
    from main import mongo_db
    if mongo_db is None: 
        raise HTTPException(503, "MongoDB no conectado")
    return mongo_db
# ----------------------------------------------------

router = APIRouter(tags=["Hábitos y Sintomatología (Time Series)"])

@router.post("/habitos")
async def registrar_registro_diario(
    habito: HabitoInput, 
    db: Annotated[AsyncIOMotorClient, Depends(get_mongo_db)]
):
    """
    Registra un nuevo hábito o síntoma diario en la colección Time Series 'habitos' (Req 2).
    """
    habito_dict = habito.dict(exclude_none=True)
    
    return await habito_service.registrar_habito(db, habito_dict)