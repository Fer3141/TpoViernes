# services/user_service.py

from fastapi import HTTPException
from motor.motor_asyncio import AsyncIOMotorClient
from passlib.context import CryptContext
from pymongo import ReturnDocument
from schemas.user import UsuarioInput
from bson import json_util
import json

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

def parse_json(data):
    return json.loads(json_util.dumps(data))

async def crear_usuario(mongo_db: AsyncIOMotorClient, usuario: UsuarioInput):
    """
    Crea un nuevo usuario en la colección 'usuarios'.
    - Valida duplicados de id y username
    - Hashea 'auth.pass' en 'auth.password_hash'
    - Remapea 'id' -> '_id'
    """
    if mongo_db is None:
        raise HTTPException(status_code=503, detail="MongoDB no conectado")

    # Determinar/Generar ID secuencial (usr-001, usr-002, ...)
    async def _get_next_user_id():
        # Si no existe el contador, sembrarlo con el mayor existente
        counters_doc = await mongo_db.counters.find_one({"_id": "usuarios"})
        if not counters_doc:
            highest = 0
            try:
                cursor = mongo_db.usuarios.find({"_id": {"$regex": r"^usr-\\d+$"}}).sort("_id", -1).limit(1)
                top_list = await cursor.to_list(length=1)
                if top_list:
                    top_id = top_list[0]["_id"]
                    try:
                        highest = int(top_id.split("-")[1])
                    except Exception:
                        highest = 0
            except Exception:
                highest = 0
            # Intentar insertar el contador inicial
            try:
                await mongo_db.counters.insert_one({"_id": "usuarios", "seq": highest})
            except Exception:
                pass

        # Obtener el próximo valor de forma atómica y asegurar que no colisione
        for _ in range(100):
            doc = await mongo_db.counters.find_one_and_update(
                {"_id": "usuarios"},
                {"$inc": {"seq": 1}},
                upsert=True,
                return_document=ReturnDocument.AFTER,
            )
            seq = int(doc.get("seq", 1))
            width = 3 if seq < 1000 else len(str(seq))
            candidate = f"usr-{str(seq).zfill(width)}"
            # Verificar colisión con usuarios existentes (p.ej. si el contador estaba desfasado)
            if not await mongo_db.usuarios.find_one({"_id": candidate}):
                return candidate
        raise HTTPException(status_code=500, detail="No se pudo generar un ID único para el usuario (reintentos agotados)")

    if usuario.id:
        # Validar que no exista ese ID
        if await mongo_db.usuarios.find_one({"_id": usuario.id}):
            raise HTTPException(status_code=400, detail=f"Ya existe un usuario con id '{usuario.id}'")
        new_id = usuario.id
    else:
        new_id = await _get_next_user_id()

    # Chequear duplicados por username
    if await mongo_db.usuarios.find_one({"auth.username": usuario.auth.username}):
        raise HTTPException(status_code=400, detail=f"El username '{usuario.auth.username}' ya está en uso")

    # Preparar documento
    user_doc = usuario.dict(by_alias=False, exclude_none=True)
    # Asegurar _id
    user_doc["_id"] = user_doc.pop("id", None) or new_id

    plain_password = user_doc.get("auth", {}).pop("password", None)
    if not plain_password:
        raise HTTPException(status_code=400, detail="El campo 'auth.pass' es requerido")

    user_doc["auth"]["password_hash"] = pwd_context.hash(plain_password)

    # Insertar
    try:
        await mongo_db.usuarios.insert_one(user_doc)
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Error al crear usuario: {e}")

    # Si se envió un ID manual mayor al contador, asegurar que el contador no retroceda
    if usuario.id:
        try:
            numeric = int(str(new_id).split("-")[1])
            await mongo_db.counters.update_one(
                {"_id": "usuarios"}, {"$max": {"seq": numeric}}, upsert=True
            )
        except Exception:
            pass

    # Respuesta segura
    safe_doc = {
        "_id": user_doc["_id"],
        "auth": {"username": user_doc["auth"]["username"]},
        "roles": user_doc.get("roles", []),
        "pii": user_doc.get("pii"),
        "paciente": user_doc.get("paciente"),
        "medico": user_doc.get("medico"),
    }
    return {"status": "usuario creado", "usuario": parse_json(safe_doc)}
