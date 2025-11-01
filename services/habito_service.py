# services/habito_service.py

from fastapi import HTTPException
from motor.motor_asyncio import AsyncIOMotorClient
from datetime import datetime
from bson import json_util
import json

# Helper (Asumimos que parse_json está disponible en el ámbito)
def parse_json(data):
    """Convierte BSON/Mongo a JSON legible."""
    return json.loads(json_util.dumps(data))

async def registrar_habito(mongo_db: AsyncIOMotorClient, habito_dict: dict):
    """
    Inserta un registro de hábito o sintomatología en la colección Time Series 'habitos' (Req 2).
    """
    
    # MongoDB asigna automáticamente el _id en colecciones Time Series
    try:
        resultado = await mongo_db.habitos.insert_one(habito_dict)
        
        # Opcional: Actualizar el perfil del paciente con la última actualización
        await mongo_db.usuarios.update_one(
            {"_id": habito_dict["paciente_id"]},
            {"$set": {"paciente.habitos_ultima_actualizacion": datetime.now().isoformat()}}
        )

        return {
            "status": "hábito/síntoma registrado", 
            "inserted_id": str(resultado.inserted_id), 
            "paciente_id": habito_dict["paciente_id"]
        }
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error al guardar el hábito en Time Series: {e}")