# services/visita_service.py

from fastapi import HTTPException
from motor.motor_asyncio import AsyncIOMotorClient
from bson import json_util
import json

# ----------------------------------------------------
# Helper (Asumimos que parse_json está disponible)
# ----------------------------------------------------
def parse_json(data):
    """Convierte BSON/Mongo a JSON legible."""
    return json.loads(json_util.dumps(data))
# ----------------------------------------------------

async def crear_visita(mongo_db: AsyncIOMotorClient, visita_dict: dict):
    """
    Inserta el documento de visita médica en la colección 'visitas_medicas'.
    También actualiza el campo 'ultima_consulta_id' en el documento del paciente.
    """
    
    # 1. Preparar ID y remapear '_id'
    visita_dict["_id"] = visita_dict.pop("id")
    paciente_id = visita_dict["paciente_id"]
    visita_id = visita_dict["_id"]

    # 2. Intentar guardar en 'visitas_medicas'
    try:
        await mongo_db.visitas_medicas.insert_one(visita_dict)
        
    except Exception as e:
        if hasattr(e, 'code') and e.code == 11000:
            raise HTTPException(status_code=400, detail=f"Error al guardar: Ya existe una visita con el ID {visita_id}.")
        raise HTTPException(status_code=500, detail=f"Error inesperado al guardar la visita: {e}")

    # 3. Actualizar la referencia en el documento del paciente (Req 1)
    try:
        await mongo_db.usuarios.update_one(
            {"_id": paciente_id},
            {"$set": {"paciente.ultima_consulta_id": visita_id}}
        )
    except Exception as e:
         # No es un error crítico, pero es importante registrarlo
        print(f"Advertencia: No se pudo actualizar el ID de la última consulta para {paciente_id}: {e}")

    return {"status": "visita registrada", "id": visita_id, "paciente_id": paciente_id}