# routers/usuario_router.py

from fastapi import APIRouter, HTTPException, Depends
from motor.motor_asyncio import AsyncIOMotorClient
from typing import Annotated
from schemas.user import UsuarioInput
from services import user_service

# Dependency Injection (usa el mongo_db global de main.py)
def get_mongo_db():
    from main import mongo_db
    if mongo_db is None:
        raise HTTPException(status_code=503, detail="MongoDB no conectado")
    return mongo_db

router = APIRouter(tags=["Usuarios"])

@router.post("/usuarios")
async def crear_usuario(
    usuario: UsuarioInput,
    db: Annotated[AsyncIOMotorClient, Depends(get_mongo_db)]
):
    return await user_service.crear_usuario(db, usuario)
