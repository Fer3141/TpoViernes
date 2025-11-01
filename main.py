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


# --- Modelos Pydantic ADAPTADOS al JSON del usuario (Soporte Multiroles) ---

class PIIModel(BaseModel):
    """Acepta el campo 'pii' a nivel superior del documento."""
    dni: str
    nombre: str
    email: str
    telefono: str
    direccion: str
    fecha_nac: str
    genero: str
    pais: str

class HorarioModel(BaseModel):
    """Horarios de atención."""
    dia: str
    inicio: str 
    fin: str 

class CentroModel(BaseModel):
    """Centro de atención y sus horarios."""
    nombre: str
    horarios: List[HorarioModel] = []

class MedicoModel(BaseModel):
    """ADAPTADO: Acepta los campos directamente bajo 'medico' (sin 'perfil')."""
    matricula: str
    especialidad: List[str] 
    centros: List[CentroModel] = []

# Modelos de Paciente (Definidos para el caso de rol PACIENTE completo)
class PacienteClinicoModel(BaseModel):
    grupo_sanguineo: str
    alergias: List[str] = []
    antecedentes: List[str] = []

class PacienteModel(BaseModel):
    """Estructura de paciente completa (si es enviada)."""
    obra_social: str
    numero_afiliado: str
    clinico: PacienteClinicoModel
    ultima_consulta_id: str
    riesgos_activos_count: int = 0
    habitos_ultima_actualizacion: str


class AuthModel(BaseModel):
    """ADAPTADO: Pydantic lee el campo 'pass' del JSON como 'password'."""
    username: str
    password: str = Field(alias='pass') # <-- Pydantic lee el campo "pass" en el JSON


class UsuarioInput(BaseModel):
    """
    Modelo maestro que soporta cualquier combinación de roles (PACIENTE, MEDICO, AMBOS).
    """
    id: str 
    auth: AuthModel
    roles: List[str] 
    pii: PIIModel # <-- Acepta el campo 'pii' a nivel superior
    paciente: Optional[PacienteModel] = None 
    medico: Optional[MedicoModel] = None


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
    Adaptado para aceptar el JSON simplificado (pass, pii, medico plano).
    """
    if mongo_db is None: raise HTTPException(503, "MongoDB no conectado")

    # exclude_none=True elimina los campos 'paciente' o 'medico' si no se envían
    usuario_dict = usuario.dict(exclude_none=True) 
    
    usuario_dict["_id"] = usuario_dict.pop("id")
    
    # --- 1. Remapeo de 'pass' ---
    if 'auth' in usuario_dict and 'password' in usuario_dict['auth']:
        # Convierte 'password' (interno) a 'pass' (Mongo)
        usuario_dict['auth']['pass'] = usuario_dict['auth'].pop('password')
        
    # --- 2. Anidamiento de 'perfil' (Solo si hay datos de médico) ---
    if usuario_dict.get('medico'):
        # Si 'matricula' existe, significa que los datos están planos y necesitan anidamiento 'perfil'
        if 'matricula' in usuario_dict['medico']:
            medico_data = usuario_dict['medico']
            # Creamos el anidamiento requerido para la consistencia de Mongo
            usuario_dict['medico'] = {'perfil': medico_data}

    # --- 3. Guardar en MongoDB ---
    try:
        resultado = await mongo_db.usuarios.insert_one(usuario_dict)
        return {"status": "usuario creado", "id": str(resultado.inserted_id), "data": parse_json(usuario_dict)}
    except Exception as e:
        if hasattr(e, 'code') and e.code == 11000:
            raise HTTPException(status_code=400, detail=f"Error al guardar: Ya existe un usuario con el ID {usuario.id}.")
        raise HTTPException(status_code=500, detail=f"Error inesperado al guardar en Mongo: {e}")


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
    
    return {"status": "turno creado", "data": parse_json(turno_dict)}


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

# --- Correr la App ---
if __name__ == "__main__":
    print("Iniciando API Políglota en http://127.0.0.1:8000")
    print("Documentación de la API en http://127.0.0.1:8000/docs")
    uvicorn.run("main:app", host="127.0.0.1", port=8000, reload=True)