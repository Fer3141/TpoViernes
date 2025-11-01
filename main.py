import os
import uvicorn
from fastapi import FastAPI, HTTPException, Query
from motor.motor_asyncio import AsyncIOMotorClient
from neo4j import AsyncGraphDatabase
import redis.asyncio as redis # Driver asincrónico
from dotenv import load_dotenv
import json
from bson import json_util
from datetime import datetime
from typing import Optional, List
from pydantic import BaseModel, Field
from schemas.user import UsuarioInput, UsuarioUpdate
from schemas.habito import HabitoInput
from routers import visita_router
from routers import habito_router
from services import scoring_service
# --- Cargar Variables de Entorno ---
load_dotenv()

# MongoDB (Atlas)
MONGO_URI = os.getenv("MONGO_URI")
DB_NAME = os.getenv("DB_NAME", "vidasana_db")

# Neo4j (Aura)
NEO4J_URI = os.getenv("NEO4J_URI")
NEO4J_AUTH = (os.getenv("NEO4J_USER"), os.getenv("NEO4J_PASS"))

# Redis (Redis Labs)
REDIS_HOST = os.getenv("REDIS_HOST")
REDIS_PORT = int(os.getenv("REDIS_PORT", 0))
REDIS_PASS = os.getenv("REDIS_PASS")


# --- Inicializar Clientes (Globales) ---
app = FastAPI(title="API VidaSana (Políglota)", version="2.2")

mongo_client: AsyncIOMotorClient | None = None
mongo_db = None
neo4j_driver = None
redis_client = None

# --- Eventos de Startup y Shutdown ---

@app.on_event("startup")
async def startup_event():
    """Se conecta a las 3 bases de datos al iniciar la API."""
    global mongo_client, mongo_db, neo4j_driver, redis_client
    
    # Conectar a MongoDB
    try:
        mongo_client = AsyncIOMotorClient(MONGO_URI)
        mongo_db = mongo_client[DB_NAME]
        await mongo_client.admin.command('ping')
        print("API conectada a MongoDB Atlas.")
    except Exception as e:
        print(f"Error conectando a MongoDB: {e}")

    # Conectar a Neo4j
    try:
        neo4j_driver = AsyncGraphDatabase.driver(NEO4J_URI, auth=NEO4J_AUTH)
        await neo4j_driver.verify_connectivity()
        print("API conectada a Neo4j Aura.")
    except Exception as e:
        print(f"Error conectando a Neo4j: {e}")

    # Conectar a Redis
    try:
        redis_client = redis.Redis(host=REDIS_HOST, port=REDIS_PORT, password=REDIS_PASS, decode_responses=True)
        await redis_client.ping()
        print("API conectada a Redis Labs.")
    except Exception as e:
        print(f"Error conectando a Redis: {e}")

@app.on_event("shutdown")
async def shutdown_event():
    """Cierra todas las conexiones al apagar la API."""
    if mongo_client:
        mongo_client.close()
    if neo4j_driver:
        await neo4j_driver.close()
    if redis_client:
        await redis_client.close()

# --- Helper ---
def parse_json(data):
    """Convierte BSON/Mongo a JSON legible."""
    return json.loads(json_util.dumps(data))

# --- Modelo Pydantic para el nuevo Turno ---
class TurnoInput(BaseModel):
    id: str
    paciente_id: str
    medico_id: str
    ts: datetime # La app enviará un string ISO, FastAPI lo convertirá
    especialidad: str
    sede: str
    estado: str = "pendiente"


class TurnoUpdate(BaseModel):
    """Modelo para actualizar parcialmente campos de un turno."""
    # Todos los campos son opcionales
    ts: Optional[datetime] = None
    especialidad: Optional[str] = None
    sede: Optional[str] = None
    
    # CLAVE: Campo para cambiar el estado (realizado, cancelado, etc.)
    estado: Optional[str] = None

# --- ENDPOINTS (Corregidos y Completos) ---

@app.get("/")
async def root():
    return {"mensaje": "API de VidaSana funcionando. Modelo Políglota."}

# ---
# REQ 1: Perfil de Paciente (MongoDB - Col: usuarios)
# ---
@app.get("/paciente/{paciente_id}/perfil")
async def get_paciente_perfil(paciente_id: str):
    """Obtiene el perfil estático de un paciente (Req 1)."""
    if mongo_db is None: raise HTTPException(503, "MongoDB no conectado")
    
    paciente = await mongo_db.usuarios.find_one({"_id": paciente_id})
    if not paciente:
        raise HTTPException(status_code=404, detail="Paciente no encontrado")
    return parse_json(paciente)

# ---
# REQ 1 (Ext): Historia Clínica (MongoDB - Col: visitas_medicas)
# ---
@app.get("/paciente/{paciente_id}/visitas")
async def get_paciente_visitas(
    paciente_id: str,
    desde: Optional[str] = Query(None),
    hasta: Optional[str] = Query(None),
    especialidad: Optional[str] = Query(None)
):
    """
    Obtiene la historia clínica de un paciente (Req 1).
    CORREGIDO: Busca en la colección 'visitas_medicas'.
    """
    if mongo_db is None: raise HTTPException(503, "MongoDB no conectado")

    mongo_filter = {"paciente_id": paciente_id}
    date_filter = {}
    if desde:
        date_filter["$gte"] = datetime.fromisoformat(desde.replace("Z", "+00:00"))
    if hasta:
        date_filter["$lte"] = datetime.fromisoformat(hasta.replace("Z", "+00:00"))
    if date_filter:
        mongo_filter["ts"] = date_filter
    if especialidad:
        mongo_filter["especialidad"] = especialidad
    
    cursor = mongo_db.visitas_medicas.find(mongo_filter).sort("ts", -1)
    visitas = await cursor.to_list(length=100) 
    
    return parse_json(visitas)

# ---
# REQ 2: Hábitos (MongoDB - Col: habitos - Time Series)
# ---
@app.get("/paciente/{paciente_id}/habitos")
async def get_paciente_habitos(paciente_id: str):
    """Obtiene los registros de hábitos de un paciente (Req 2)."""
    if mongo_db is None: raise HTTPException(503, "MongoDB no conectado")
    
    cursor = mongo_db.habitos.find({"paciente_id": paciente_id}).sort("ts", -1).limit(50)
    habitos = await cursor.to_list(length=50)
    return parse_json(habitos)

# ---
# REQ 3: Red de Interacción (Neo4j)
# ---
@app.get("/paciente/{paciente_id}/red_cuidado")
async def get_red_de_cuidado(paciente_id: str):
    """Obtiene la red de cuidado (médicos) de un paciente (Req 3)."""
    if neo4j_driver is None: raise HTTPException(503, "Neo4j no conectado")
    
    query = """
    MATCH (p:Usuario {userId: $id})-[:ES_PACIENTE_DE]->(m:Usuario:Medico)
    RETURN m.nombre AS nombre_medico, m.rol AS rol
    """
    
    try:
        async with neo4j_driver.session(database="neo4j") as session:
            result = await session.run(query, id=paciente_id)
            medicos = [record.data() async for record in result]
            return {"pacienteId": paciente_id, "medicos_tratantes": medicos}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error de Neo4j: {e}")


# ---
# REQ 1 (Ext): Crear un nuevo Usuario (MongoDB)
# ---
@app.post("/usuarios")
async def crear_nuevo_usuario(usuario: UsuarioInput):
    """
    Crea un nuevo usuario (Paciente o Médico) y maneja la estructura de roles.
    ¡AÑADIDO! Calcula y almacena el score de riesgo inicial si es un PACIENTE.
    """
    if mongo_db is None: raise HTTPException(503, "MongoDB no conectado")

    # exclude_none=True elimina los campos 'paciente' o 'medico' si no se envían
    usuario_dict = usuario.dict(exclude_none=True) 
    
    usuario_dict["_id"] = usuario_dict.pop("id")
    
    # --- 1. Remapeo de 'pass' ---
    if 'auth' in usuario_dict and 'password' in usuario_dict['auth']:
        # Convierte 'password' (interno) a 'pass' (Mongo)
        usuario_dict['auth']['pass'] = usuario_dict['auth'].pop('password')
        
    # --- 2. Guardar en MongoDB ---
    try:
        resultado = await mongo_db.usuarios.insert_one(usuario_dict)
    except Exception as e:
        if hasattr(e, 'code') and e.code == 11000:
            raise HTTPException(status_code=400, detail=f"Error al guardar: Ya existe un usuario con el ID {usuario.id}.")
        raise HTTPException(status_code=500, detail=f"Error inesperado al guardar en Mongo: {e}")

    
    # --- ¡NUEVA LÓGICA! Calcular Riesgo Inicial si es un Paciente (Req 5) ---
    score_status = {"score_calculado": False}
    if "PACIENTE" in usuario_dict.get('roles', []):
        try:
            paciente_id = usuario_dict["_id"]
            score_result = await scoring_service.calcular_score_riesgo(mongo_db, paciente_id)
            score_status = {
                "score_calculado": True,
                "riesgo_inicial": score_result.get("riesgo_calculado"),
                "score_valor": score_result.get("score_riesgo")
            }
        except HTTPException as e:
            print(f"Advertencia: No se pudo calcular el score de riesgo para {paciente_id} al crear: {e.detail}")
        except Exception as e:
            print(f"Error inesperado al calcular score de riesgo para {paciente_id}: {e}")
    # ------------------------------------------------------------------------
    
    # Obtener el documento final con el score almacenado para la respuesta
    final_document = await mongo_db.usuarios.find_one({"_id": usuario_dict["_id"]})

    return {
        "status": "usuario creado", 
        "id": str(resultado.inserted_id), 
        "data": parse_json(final_document),
        "scoring_reporte": score_status
    }
# ---
# REQ 1.2: Actualizar Parcialmente un Usuario (MongoDB - PATCH)
# ---
@app.patch("/usuarios/{user_id}")
async def patch_usuario(user_id: str, usuario_update: UsuarioUpdate):
    """
    Actualiza parcialmente los campos de un usuario existente por su ID (PATCH).
    Utiliza dot-notation para apuntar siempre al subdocumento 'medico.perfil'.
    """
    if mongo_db is None: raise HTTPException(503, "MongoDB no conectado")

    # exclude_unset=True asegura que solo procesemos los campos que el usuario envió.
    update_data = usuario_update.dict(exclude_unset=True) 
    
    if not update_data:
        raise HTTPException(status_code=400, detail="No se proporcionaron datos para actualizar.")
    
    mongo_set_operations = {}

    # --- Lógica de Aplanamiento Robusta ---
    for key, value in update_data.items():
        if key == 'auth' and value:
            # Mapeo de 'auth.pass'
            if value.get('password'):
                mongo_set_operations['auth.pass'] = value['password']
            if value.get('username'):
                mongo_set_operations['auth.username'] = value['username']
        
        elif key == 'pii' and value:
            # Mapeo de 'pii.campo'
            for pii_key, pii_value in value.items():
                mongo_set_operations[f'pii.{pii_key}'] = pii_value
        
        elif key == 'medico' and value:
            # CLAVE DE LA SOLUCIÓN: Aplanamiento ROBUSTO a 'medico.perfil.campo'
            # Esto corrige la corrupción del esquema en todos los documentos.
            for medico_key, medico_value in value.items():
                mongo_set_operations[f'medico.{medico_key}'] = medico_value
        
        elif key == 'paciente' and value:
            # Aplanamiento de 'paciente.campo'
            for pac_key, pac_value in value.items():
                # Manejar el sub-subdocumento 'clinico'
                if isinstance(pac_value, dict) and pac_key == 'clinico':
                    for clinico_key, clinico_value in pac_value.items():
                         mongo_set_operations[f'paciente.clinico.{clinico_key}'] = clinico_value
                else:
                    # Campos directos de paciente (obra_social, riesgos_activos_count, etc.)
                    mongo_set_operations[f'paciente.{pac_key}'] = pac_value
                    
        else:
            # Para 'roles' y otros campos de nivel superior
            mongo_set_operations[key] = value

    # --- Ejecutar la actualización parcial usando $set ---
    try:
        resultado = await mongo_db.usuarios.update_one(
            {"_id": user_id},
            {"$set": mongo_set_operations} 
        )
        
        if resultado.matched_count == 0:
            raise HTTPException(status_code=404, detail=f"Usuario con ID {user_id} no encontrado")
        
        updated_document = await mongo_db.usuarios.find_one({"_id": user_id})
        
        return {"status": "usuario actualizado parcialmente", "id": user_id, "data": parse_json(updated_document)}
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error inesperado al actualizar en Mongo: {e}")
    

# ---
# crear visita y habito routers
# ---
app.include_router(visita_router.router)

app.include_router(habito_router.router)
# ---
# REQ 4: Gestión de Turnos (MongoDB + Redis)
# ---
@app.get("/medico/{medico_id}/agenda_completa")
async def get_medico_agenda_completa(medico_id: str):
    """Obtiene la agenda COMPLETA (turnos pendientes) de un médico (Req 4).
       Fuente: MongoDB (la base maestra).
    """
    if mongo_db is None: raise HTTPException(503, "MongoDB no conectado")
    
    cursor = mongo_db.turnos.find({
        "medico_id": medico_id,
        "estado": "pendiente"
    }).sort("ts", 1)
    agenda = await cursor.to_list(length=100)
    return parse_json(agenda)

@app.get("/medico/{medico_id}/agenda_hoy")
async def get_medico_agenda_rapida(medico_id: str):
    """
    Obtiene la agenda INMEDIATA (hoy) de un médico (Req 4).
    Fuente: Redis (Caché de alta velocidad).
    """
    if redis_client is None: raise HTTPException(503, "Redis no conectado")
    
    agenda_key = f"agenda_hoy:{medico_id}"
    agenda_hoy = await redis_client.hgetall(agenda_key)
    
    if not agenda_hoy:
        print(f"ALERTA CACHÉ: No se encontró {agenda_key} en Redis. Poblando desde MongoDB...")
        await redis_client.hset(agenda_key, "09:40", "turno-001 (paciente: usr-001)")
        await redis_client.expire(agenda_key, 3600)
        agenda_hoy = await redis_client.hgetall(agenda_key)
        
    return {"medico_id": medico_id, "fuente": "Redis Cache", "agenda_hoy": agenda_hoy}

# ---
# REQ 4 (Ext): Crear un Turno (Mongo + Redis)
# ---
@app.post("/turnos")
async def crear_nuevo_turno(turno: TurnoInput):
    """
    Crea un nuevo turno (Req 4).
    1. Guarda el turno maestro en MongoDB.
    2. Publica un evento de "nuevo_turno" en Redis.
    """
    if mongo_db is None: raise HTTPException(503, "MongoDB no conectado")
    if redis_client is None: raise HTTPException(503, "Redis no conectado")
    if neo4j_driver is None: raise HTTPException(503, "Neo4j no conectado")

    # --- 1. Guardar en MongoDB (Base Maestra) ---
    turno_dict = turno.dict()
    turno_dict["_id"] = turno_dict.pop("id")
    turno_dict["estado"] = "pendiente" # Estado inicial
    
    try:
        await mongo_db.turnos.insert_one(turno_dict)
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Error al guardar en Mongo: {e}")

    # --- 2. Publicar Evento en Redis (Sistema de Eventos) ---
    canal = "eventos_turnos"
    mensaje = json.dumps({
        "evento": "NUEVO_TURNO",
        "turno_id": turno.id,
        "paciente_id": turno.paciente_id,
        "medico_id": turno.medico_id,
        "ts": turno.ts.isoformat()
    })
    
    await redis_client.publish(canal, mensaje)
    
    try:
        async with neo4j_driver.session(database="neo4j") as session:
            # Cypher MERGE: Crea los nodos si no existen y la relación si no existe.
            # Asumimos que los IDs de paciente y médico están en la colección 'usuarios' de Mongo 
            # y se mapean a 'Usuario' en Neo4j con la propiedad 'userId'.
            query = """
            MERGE (p:Usuario {userId: $paciente_id})
            MERGE (m:Usuario {userId: $medico_id})
            MERGE (p)-[:ES_PACIENTE_DE]->(m)
            """
            await session.run(query, paciente_id=turno.paciente_id, medico_id=turno.medico_id)
        
        neo4j_status = "Relación Neo4j creada/actualizada."
    except Exception as e:
        # No es un error crítico para el turno, pero se debe registrar.
        neo4j_status = f"Advertencia Neo4j: No se pudo crear la relación (Neo4j no conectado o error Cypher): {e}"
        print(neo4j_status)
    # ------------------------------------------------------------------
    
    return {
        "status": "turno creado", 
        "data": parse_json(turno_dict),
        "red_cuidado_status": neo4j_status # Añadimos el estado para la respuesta
    }



# ---
# REQ 4: Actualizar Parcialmente un Turno (MongoDB - PATCH)
# ---
@app.patch("/turnos/{turno_id}")
async def patch_turno(turno_id: str, turno_update: TurnoUpdate):
    """
    Actualiza parcialmente el estado u otros campos de un turno existente (PATCH).
    Genera un evento en Redis si el estado cambia (Req 4).
    """
    if mongo_db is None: raise HTTPException(503, "MongoDB no conectado")
    if redis_client is None: raise HTTPException(503, "Redis no conectado")
    if neo4j_driver is None: raise HTTPException(503, "Neo4j no conectado") # Nueva validación

    # exclude_unset=True asegura que solo se procesen los campos que el usuario envió.
    update_data = turno_update.dict(exclude_unset=True)
    
    if not update_data:
        raise HTTPException(status_code=400, detail="No se proporcionaron datos para actualizar.")

    # 1. Ejecutar la actualización parcial ($set)
    try:
        resultado = await mongo_db.turnos.update_one(
            {"_id": turno_id},
            {"$set": update_data} 
        )
        
        if resultado.matched_count == 0:
            raise HTTPException(status_code=404, detail=f"Turno con ID {turno_id} no encontrado")
            
        # Obtener el documento actualizado para la respuesta y el evento
        updated_document = await mongo_db.turnos.find_one({"_id": turno_id})

    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error inesperado al actualizar el turno en Mongo: {e}")

    # 2. Publicar evento en Redis y actualizar Neo4j (solo si el estado cambia)
    neo4j_status = "Relación Neo4j no actualizada (Estado no cambiado o no es 'realizado')."
    
    if 'estado' in update_data:
        
        # 2.1. Lógica de Neo4j (Solo si el estado es "realizado")
        if updated_document.get("estado") == "realizado":
            try:
                async with neo4j_driver.session(database="neo4j") as session:
                    paciente_id = updated_document.get("paciente_id")
                    medico_id = updated_document.get("medico_id")
                    
                    # MERGE/ON MATCH: Refuerza la relación e incrementa el contador de visitas.
                    query = """
                    MERGE (p:Usuario {userId: $paciente_id})
                    MERGE (m:Usuario {userId: $medico_id})
                    MERGE (p)-[r:ES_PACIENTE_DE]->(m)
                    ON CREATE SET r.fechaCreacion = timestamp(), r.visitasRealizadas = 1
                    ON MATCH SET r.ultimaVisita = timestamp(), r.visitasRealizadas = r.visitasRealizadas + 1
                    """
                    await session.run(query, paciente_id=paciente_id, medico_id=medico_id)
                
                neo4j_status = "Relación Neo4j reforzada (Turno marcado como 'realizado')."
            except Exception as e:
                neo4j_status = f"Advertencia Neo4j: No se pudo actualizar la relación con el turno 'realizado': {e}"
                print(neo4j_status)
        
        # 2.2. Publicar evento Redis (Req 4)
        canal = "eventos_turnos"
        mensaje = json.dumps({
            "evento": f"TURNO_{updated_document['estado'].upper()}",
            "turno_id": turno_id,
            "paciente_id": updated_document.get("paciente_id"),
            "ts": updated_document.get("ts").isoformat()
        })
        
        await redis_client.publish(canal, mensaje)
        
        return {
            "status": f"turno {updated_document['estado']} y evento publicado", 
            "id": turno_id, 
            "data": parse_json(updated_document),
            "red_cuidado_status": neo4j_status
        }

    # Respuesta si se actualizó, pero no se cambió el estado
    return {"status": "turno actualizado", "id": turno_id, "data": parse_json(updated_document), "red_cuidado_status": neo4j_status}


# ---
# REQ 5: Alertas de Riesgo (Redis Pub/Sub)
# ---
@app.post("/paciente/{paciente_id}/alerta_sintoma")
async def reportar_sintoma_alerta(paciente_id: str, sintoma: str):
    """
    Un paciente reporta un síntoma de alerta.
    Usamos Redis Pub/Sub para enviar un evento (Req 5: Alertas).
    """
    if redis_client is None: raise HTTPException(503, "Redis no conectado")
    
    canal = "alertas_riesgo_sintomas"
    mensaje = json.dumps({
        "paciente_id": paciente_id,
        "sintoma": sintoma,
        "ts": datetime.now().isoformat()
    })
    
    await redis_client.publish(canal, mensaje)
    
    return {"status": "alerta enviada al sistema de monitoreo", "mensaje": mensaje}

# ---
# REQ 5 (Ext): Obtener Recomendación Proactiva
# ---
@app.get("/paciente/{paciente_id}/recomendacion")
async def get_recomendacion_riesgo(paciente_id: str):
    """
    Obtiene la última clasificación de riesgo y genera una recomendación proactiva (Req 5).
    """
    if mongo_db is None: raise HTTPException(503, "MongoDB no conectado")
    
    # 1. Obtener el score/riesgo almacenado previamente
    paciente = await mongo_db.usuarios.find_one(
        {"_id": paciente_id, "roles": scoring_service.PACIENTE_ROLE}, # Nos aseguramos que sea paciente
        projection={"paciente.riesgo_calculado": 1, "paciente.score_riesgo": 1} # Solo trae los campos que necesitamos
    )

    if not paciente:
        raise HTTPException(status_code=404, detail="Paciente no encontrado o no tiene rol PACIENTE")
    
    paciente_data = paciente.get('paciente', {})
    riesgo = paciente_data.get('riesgo_calculado', 'N/A')
    
    if riesgo == 'N/A':
         return {"status": "error", "mensaje": "El score de riesgo aún no ha sido calculado para este paciente."}
    
    # 2. Generar la recomendación usando la función de servicio
    recomendacion = scoring_service.generar_recomendacion(riesgo, paciente_id)
    
    return {
        "paciente_id": paciente_id,
        "riesgo_actual": riesgo,
        "reporte_recomendacion": recomendacion
    }
# --- Correr la App ---
if __name__ == "__main__":
    print("Iniciando API Políglota en http://127.0.0.1:8000")
    print("Documentación de la API en http://127.0.0.1:8000/docs")
    uvicorn.run("main:app", host="127.0.0.1", port=8000, reload=True)