import os
import uvicorn
from fastapi import FastAPI, HTTPException, Query, Depends, status
from fastapi.security import OAuth2PasswordBearer, OAuth2PasswordRequestForm
from fastapi.middleware.cors import CORSMiddleware
from motor.motor_asyncio import AsyncIOMotorClient
from neo4j import AsyncGraphDatabase
import redis.asyncio as redis
from dotenv import load_dotenv
import json
from bson import json_util
from datetime import datetime, timedelta, timezone
from typing import Optional, List, Dict, Any
from pydantic import BaseModel, Field
from jose import JWTError, jwt
from passlib.context import CryptContext

# --- Cargar Variables de Entorno ---
load_dotenv()
MONGO_URI = os.getenv("MONGO_URI")
DB_NAME = os.getenv("DB_NAME", "vidasana_db")
NEO4J_URI = os.getenv("NEO4J_URI")
NEO4J_AUTH = (os.getenv("NEO4J_USER"), os.getenv("NEO4J_PASS"))
REDIS_HOST = os.getenv("REDIS_HOST")
REDIS_PORT = int(os.getenv("REDIS_PORT", 0))
REDIS_PASS = os.getenv("REDIS_PASS")

# --- Configuración de Seguridad (JWT) ---
SECRET_KEY = "tu-clave-secreta-para-jwt-muy-segura" 
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = 60 
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="token")

# --- Inicializar FastAPI ---
app = FastAPI(title="API VidaSana (Políglota)", version="4.3.1 - Perfil Paciente Corregido")

# --- Configuración de CORS ---
origins = [
    "http://localhost:5173",
    "http://127.0.0.1:5500",
    "null" # Permite "file://"
]
app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=True,
    allow_methods=["*"], 
    allow_headers=["*"],
)

# --- Modelos Pydantic (¡ACTUALIZADOS!) ---

class Token(BaseModel):
    access_token: str
    token_type: str

class TokenData(BaseModel):
    username: Optional[str] = None

class UsuarioEnDB(BaseModel):
    id: str = Field(..., alias="_id") 
    auth: dict
    roles: List[str]
    class Config:
        arbitrary_types_allowed = True 
        populate_by_name = True

class TurnoInput(BaseModel):
    id: str = Field(..., alias="_id") 
    paciente_id: str
    medico_id: str
    ts: datetime 
    especialidad: str
    sede: str
    class Config:
        populate_by_name = True 

class TurnoUpdate(BaseModel):
    estado: str 

# (¡ACTUALIZADO!) Modelo PII ahora más rico
class PII(BaseModel):
    dni: str
    nombre: str
    email: str
    fecha_nac: str
    telefono: Optional[str] = None
    direccion: Optional[str] = None
    pais: Optional[str] = None
    genero: Optional[str] = None

# (¡ACTUALIZADO!) Modelo PacienteData ahora más rico
class PacienteData(BaseModel):
    obra_social: Optional[str] = None
    numero_afiliado: Optional[str] = None # <-- ¡NUEVO!
    clinico: Optional[dict] = None # (Ej: grupo_sanguineo, alergias)

class MedicoData(BaseModel):
    perfil: Optional[dict] = None

class UsuarioCreate(BaseModel): 
    _id: str
    username: str
    password: str 
    roles: List[str] 
    pii: PII
    paciente: Optional[PacienteData] = None
    medico: Optional[MedicoData] = None

# --- ¡AQUÍ ESTÁ LA CORRECCIÓN! ---
# (¡ACTUALIZADO!) Modelo para que el Paciente actualice su perfil
class PacienteUpdate(BaseModel):
    # Campos PII (de pii.*)
    telefono: Optional[str] = None
    direccion: Optional[str] = None
    pais: Optional[str] = None
    genero: Optional[str] = None
    
    # Campos Paciente (de paciente.*)
    obra_social: Optional[str] = None
    numero_afiliado: Optional[str] = None
    clinico: Optional[Dict[str, Any]] = None
# --- Fin de la corrección ---

# Modelo para Auto-Registro de Paciente
class PacienteRegister(BaseModel):
    username: str
    password: str 
    pii: PII 
    obra_social: Optional[str] = None
    numero_afiliado: Optional[str] = None

# Modelo para Creación de Médico (Admin)
class MedicoCreate(BaseModel):
    username: str
    password: str 
    pii: PII 
    perfil: MedicoData 

class AsignarPaciente(BaseModel):
    paciente_id: str

class RiesgoAsignar(BaseModel):
    tipo: str 

class HabitoCreate(BaseModel):
    tipo: str 
    valor: float | str 
    notas: Optional[str] = None


# --- Inicializar Clientes (Globales) ---
mongo_client: AsyncIOMotorClient | None = None
mongo_db = None
neo4j_driver = None
redis_client = None

# --- Eventos de Startup y Shutdown ---
@app.on_event("startup")
async def startup_event():
    global mongo_client, mongo_db, neo4j_driver, redis_client
    try:
        mongo_client = AsyncIOMotorClient(MONGO_URI)
        mongo_db = mongo_client[DB_NAME]
        await mongo_client.admin.command('ping')
        print("API conectada a MongoDB Atlas.")
    except Exception as e: print(f"Error conectando a MongoDB: {e}")
    try:
        neo4j_driver = AsyncGraphDatabase.driver(NEO4J_URI, auth=NEO4J_AUTH)
        await neo4j_driver.verify_connectivity()
        print("API conectada a Neo4j Aura.")
    except Exception as e: print(f"Error conectando a Neo4j: {e}")
    try:
        redis_client = redis.Redis(host=REDIS_HOST, port=REDIS_PORT, password=REDIS_PASS, decode_responses=True)
        await redis_client.ping()
        print("API conectada a Redis Labs.")
    except Exception as e: print(f"Error conectando a Redis: {e}")

@app.on_event("shutdown")
async def shutdown_event():
    if mongo_client: mongo_client.close()
    if neo4j_driver: await neo4j_driver.close()
    if redis_client: await redis_client.close()

# --- Helpers ---
def parse_json(data):
    return json.loads(json_util.dumps(data))

# --- Funciones de Seguridad ---
def verify_password(plain_password, hashed_password):
    return pwd_context.verify(plain_password, hashed_password)

def get_password_hash(password):
    return pwd_context.hash(password)

def create_access_token(data: dict, expires_delta: Optional[timedelta] = None):
    to_encode = data.copy()
    if expires_delta:
        expire = datetime.now(timezone.utc) + expires_delta
    else:
        expire = datetime.now(timezone.utc) + timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
    to_encode.update({"exp": expire})
    encoded_jwt = jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)
    return encoded_jwt

async def get_user_from_db(username: str):
    if mongo_db is None: return None
    user_data = await mongo_db.usuarios.find_one({"auth.username": username})
    if user_data:
        return UsuarioEnDB(**user_data)
    return None

async def get_current_user(token: str = Depends(oauth2_scheme)):
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="No se pudieron validar las credenciales",
        headers={"WWW-Authenticate": "Bearer"},
    )
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        username: str = payload.get("sub")
        if username is None:
            raise credentials_exception
        token_data = TokenData(username=username)
    except JWTError:
        raise credentials_exception
    
    user = await get_user_from_db(username=token_data.username)
    if user is None:
        raise credentials_exception
    return user

# --- ENDPOINTS ---

@app.get("/")
async def root():
    return {"mensaje": "API de VidaSana funcionando. Modelo Políglota con Seguridad."}

# ---
# REQ 1: Gestión de Pacientes y Profesionales
# ---

@app.post("/token", response_model=Token)
async def login_for_access_token(form_data: OAuth2PasswordRequestForm = Depends()):
    user = await get_user_from_db(form_data.username)
    if not user or not verify_password(form_data.password, user.auth.get("password_hash")):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Usuario o contraseña incorrectos",
            headers={"WWW-Authenticate": "Bearer"},
        )
    
    access_token_expires = timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
    access_token = create_access_token(
        data={"sub": user.auth.get("username"), "roles": user.roles}, 
        expires_delta=access_token_expires
    )
    return {"access_token": access_token, "token_type": "bearer"}

# --- Endpoint de Auto-Registro Público para Pacientes ---
@app.post("/register/paciente", status_code=status.HTTP_201_CREATED)
async def register_paciente(user_in: PacienteRegister):
    if mongo_db is None: raise HTTPException(503, "MongoDB no conectado")
    if neo4j_driver is None: raise HTTPException(503, "Neo4j no conectado")

    existing_user = await mongo_db.usuarios.find_one({
        "$or": [{"auth.username": user_in.username}, {"pii.dni": user_in.pii.dni}]
    })
    if existing_user:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, 
            detail="El nombre de usuario o DNI ya están registrados.")

    user_id = f"usr-p-{user_in.pii.dni}"
    hashed_password = get_password_hash(user_in.password)
    
    user_doc = {
        "_id": user_id,
        "auth": {
            "username": user_in.username,
            "password_hash": hashed_password
        },
        "roles": ["PACIENTE"], 
        "pii": user_in.pii.dict(exclude_none=True), 
        "paciente": {
            "obra_social": user_in.obra_social,
            "numero_afiliado": user_in.numero_afiliado, 
            "clinico": {}
        }
    }
    
    try:
        await mongo_db.usuarios.insert_one(user_doc)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error al guardar en Mongo: {e}")

    query = "MERGE (u:Usuario:Paciente {userId: $id}) SET u.nombre = $nombre"
    try:
        async with neo4j_driver.session(database="neo4j") as session:
            await session.run(query, id=user_id, nombre=user_in.pii.nombre)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error al crear nodo en Neo4j: {e}")

    return {"status": "paciente registrado exitosamente", "_id": user_id}

# --- Endpoint para que el Admin cree Médicos ---
@app.post("/admin/crear_medico", status_code=status.HTTP_201_CREATED)
async def admin_crear_medico(
    user_in: MedicoCreate, 
    current_user: UsuarioEnDB = Depends(get_current_user)
):
    if "ADMINISTRADOR" not in current_user.roles:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Acción no autorizada. Se requiere rol de Administrador.")

    if mongo_db is None: raise HTTPException(503, "MongoDB no conectado")
    if neo4j_driver is None: raise HTTPException(503, "Neo4j no conectado")

    existing_user = await mongo_db.usuarios.find_one({
        "$or": [{"auth.username": user_in.username}, {"pii.dni": user_in.pii.dni}]
    })
    if existing_user:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, 
            detail="El nombre de usuario o DNI ya están registrados.")

    user_id = f"usr-m-{user_in.pii.dni}"
    hashed_password = get_password_hash(user_in.password)
    
    user_doc = {
        "_id": user_id,
        "auth": {"username": user_in.username, "password_hash": hashed_password},
        "roles": ["MEDICO"], 
        "pii": user_in.pii.dict(exclude_none=True), 
        "paciente": None,
        "medico": user_in.perfil.dict(exclude_none=True)
    }
    
    try:
        await mongo_db.usuarios.insert_one(user_doc)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error al guardar en Mongo: {e}")

    query = "MERGE (u:Usuario:Medico {userId: $id}) SET u.nombre = $nombre"
    try:
        async with neo4j_driver.session(database="neo4j") as session:
            await session.run(query, id=user_id, nombre=user_in.pii.nombre)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error al crear nodo en Neo4j: {e}")

    return {"status": "médico registrado exitosamente", "_id": user_id}

@app.get("/usuarios/me")
async def read_users_me(current_user: UsuarioEnDB = Depends(get_current_user)):
    if mongo_db is None: raise HTTPException(503, "MongoDB no conectado")
    user_data = await mongo_db.usuarios.find_one({"_id": current_user.id})
    if not user_data:
        raise HTTPException(status_code=404, detail="Usuario no encontrado")
    return parse_json(user_data)

@app.patch("/paciente/{paciente_id}/perfil")
async def actualizar_perfil_paciente(
    paciente_id: str, 
    update_data: PacienteUpdate, # <-- ¡Este modelo ahora está corregido!
    current_user: UsuarioEnDB = Depends(get_current_user)
):
    if mongo_db is None: raise HTTPException(503, "MongoDB no conectado")
    if "PACIENTE" in current_user.roles and current_user.id != paciente_id:
        # (Permitir que médicos vean perfiles)
        if "MEDICO" not in current_user.roles:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="No autorizado")

    update_fields = {}
    # (¡ACTUALIZADO!) Pydantic ahora entrega todos los campos
    update_data_dict = update_data.dict(exclude_unset=True) 
    
    for key, value in update_data_dict.items():
        # (Esta lógica ahora funciona porque 'telefono', 'direccion', etc. SÍ LLEGAN)
        if key in ["obra_social", "clinico", "numero_afiliado"]:
             update_fields[f"paciente.{key}"] = value
        elif key in ["telefono", "direccion", "pais", "genero"]: 
             update_fields[f"pii.{key}"] = value
             
    if not update_fields:
        raise HTTPException(status_code=400, detail="No hay campos para actualizar")
    
    result = await mongo_db.usuarios.update_one(
        {"_id": paciente_id},
        {"$set": update_fields}
    )
    if result.matched_count == 0:
        raise HTTPException(status_code=404, detail="Paciente no encontrado")
    return {"status": "perfil de paciente actualizado"}

@app.get("/paciente/{paciente_id}/perfil")
async def get_paciente_perfil(paciente_id: str, current_user: UsuarioEnDB = Depends(get_current_user)):
    if mongo_db is None: raise HTTPException(503, "MongoDB no conectado")
    if "PACIENTE" in current_user.roles and current_user.id != paciente_id:
        if "MEDICO" not in current_user.roles:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="No autorizado")
    
    paciente = await mongo_db.usuarios.find_one({"_id": paciente_id})
    if not paciente:
        raise HTTPException(status_code=404, detail="Paciente no encontrado")
    return parse_json(paciente)

@app.get("/paciente/{paciente_id}/visitas")
async def get_paciente_visitas(
    paciente_id: str,
    current_user: UsuarioEnDB = Depends(get_current_user), 
):
    if mongo_db is None: raise HTTPException(503, "MongoDB no conectado")
    if "PACIENTE" in current_user.roles and current_user.id != paciente_id:
        if "MEDICO" not in current_user.roles:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="No autorizado")
    
    mongo_filter = {"paciente_id": paciente_id}
    cursor = mongo_db.visitas_medicas.find(mongo_filter).sort("ts", -1)
    visitas = await cursor.to_list(length=100) 
    return parse_json(visitas)

# ---
# REQ 2: Seguimiento de Hábitos y Sintomatología
# ---

@app.post("/habitos", status_code=status.HTTP_201_CREATED)
async def registrar_habito(
    habito_in: HabitoCreate, 
    current_user: UsuarioEnDB = Depends(get_current_user)
):
    if mongo_db is None: raise HTTPException(503, "MongoDB no conectado")
    if redis_client is None: raise HTTPException(503, "Redis no conectado")
    if "PACIENTE" not in current_user.roles:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Solo los pacientes pueden registrar hábitos")
    habito_doc = habito_in.dict()
    habito_doc["paciente_id"] = current_user.id
    habito_doc["ts"] = datetime.now(timezone.utc)
    try:
        await mongo_db.habitos.insert_one(habito_doc)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error al guardar en Mongo Time Series: {e}")
    if habito_in.tipo == "sintoma":
        mensaje = json.dumps(parse_json(habito_doc))
        await redis_client.publish("alertas_riesgo_sintomas", mensaje)
    return {"status": "hábito registrado", "data": parse_json(habito_doc)}


@app.get("/paciente/{paciente_id}/habitos")
async def get_paciente_habitos(paciente_id: str, current_user: UsuarioEnDB = Depends(get_current_user)):
    if mongo_db is None: raise HTTPException(503, "MongoDB no conectado")
    if "PACIENTE" in current_user.roles and current_user.id != paciente_id:
        if "MEDICO" not in current_user.roles:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="No autorizado")
    cursor = mongo_db.habitos.find({"paciente_id": paciente_id}).sort("ts", -1).limit(50)
    habitos = await cursor.to_list(length=50)
    return parse_json(habitos)

# ---
# REQ 3: Red de Interacción Médico-Paciente
# ---

@app.post("/medico/{medico_id}/asignar_paciente", status_code=status.HTTP_201_CREATED)
async def asignar_paciente_a_medico(
    medico_id: str, 
    data: AsignarPaciente, 
    current_user: UsuarioEnDB = Depends(get_current_user)
):
    if neo4j_driver is None: raise HTTPException(503, "Neo4j no conectado")
    if "MEDICO" not in current_user.roles or current_user.id != medico_id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="No autorizado")
    query = """
    MATCH (p:Usuario:Paciente {userId: $paciente_id})
    MATCH (m:Usuario:Medico {userId: $medico_id})
    MERGE (p)-[r:ES_PACIENTE_DE]->(m)
    RETURN r
    """
    try:
        async with neo4j_driver.session(database="neo4j") as session:
            result = await session.run(query, paciente_id=data.paciente_id, medico_id=medico_id)
            summary = await result.consume()
            if not summary.counters.relationships_created and not summary.counters.relationships_matched:
                 raise HTTPException(status_code=404, detail="Paciente o Médico no encontrado en Neo4j")
    except Exception as e:
        if isinstance(e, HTTPException): raise e
        raise HTTPException(status_code=500, detail=f"Error de Neo4j: {e}")
    return {"status": "paciente asignado al médico en la red"}

@app.get("/paciente/{paciente_id}/red_cuidado")
async def get_red_de_cuidado(paciente_id: str, current_user: UsuarioEnDB = Depends(get_current_user)):
    if neo4j_driver is None: raise HTTPException(503, "Neo4j no conectado")
    query = """
    MATCH (p:Usuario:Paciente {userId: $id})-[:ES_PACIENTE_DE]->(m:Usuario:Medico)
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
# REQ 4: Gestión de Turnos y Consultas
# ---

@app.post("/turnos")
async def crear_nuevo_turno(turno: TurnoInput, current_user: UsuarioEnDB = Depends(get_current_user)):
    if mongo_db is None: raise HTTPException(503, "MongoDB no conectado")
    if redis_client is None: raise HTTPException(503, "Redis no conectado")
    if turno.ts < datetime.now(timezone.utc):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="La fecha y hora del turno no pueden ser anteriores a la actual.")
    conflicto = await mongo_db.turnos.find_one({"medico_id": turno.medico_id, "ts": turno.ts, "estado": "pendiente"})
    if conflicto:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Conflicto de horario: El médico ya tiene un turno pendiente.")
    if "PACIENTE" in current_user.roles and current_user.id != turno.paciente_id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="No puede crear turnos para otro paciente")
    turno_dict = turno.dict(by_alias=True)
    turno_dict["estado"] = "pendiente"
    try:
        await mongo_db.turnos.insert_one(turno_dict)
    except Exception as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=f"Error al guardar en Mongo: {e}")
    canal = "eventos_turnos"
    mensaje = json.dumps({"evento": "NUEVO_TURNO", "turno_id": turno_dict["_id"], "ts": turno.ts.isoformat()})
    await redis_client.publish(canal, mensaje)
    return {"status": "turno creado", "data": parse_json(turno_dict)}

@app.patch("/turnos/{turno_id}/estado")
async def actualizar_estado_turno(
    turno_id: str, 
    update: TurnoUpdate, 
    current_user: UsuarioEnDB = Depends(get_current_user)
):
    if mongo_db is None: raise HTTPException(503, "MongoDB no conectado")
    if redis_client is None: raise HTTPException(503, "Redis no conectado")
    if "MEDICO" not in current_user.roles:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Solo los médicos pueden actualizar turnos")
    result = await mongo_db.turnos.update_one(
        {"_id": turno_id, "estado": "pendiente"}, 
        {"$set": {"estado": update.estado, "updated_at": datetime.now(timezone.utc)}}
    )
    if result.matched_count == 0:
        raise HTTPException(status_code=404, detail="Turno no encontrado o ya estaba actualizado")
    canal = "eventos_turnos"
    mensaje = json.dumps({"evento": f"TURNO_{update.estado.upper()}", "turno_id": turno_id})
    await redis_client.publish(canal, mensaje)
    return {"status": f"turno actualizado a {update.estado}", "turno_id": turno_id}

# ---
# REQ 6 / REQ 3: Endpoints de Dashboard de Médico
# ---

@app.get("/medico/{medico_id}/pacientes")
async def get_pacientes_del_medico(
    medico_id: str, 
    current_user: UsuarioEnDB = Depends(get_current_user)
):
    if mongo_db is None: raise HTTPException(503, "MongoDB no conectado")
    if "MEDICO" not in current_user.roles and current_user.id != medico_id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="No autorizado")
    pipeline = [
        {"$match": {"medico_id": medico_id, "estado": "pendiente"}},
        {"$group": {"_id": "$paciente_id"}},
        {"$lookup": {"from": "usuarios", "localField": "_id", "foreignField": "_id", "as": "paciente_info"}},
        {"$unwind": "$paciente_info"},
        {"$project": {"_id": 0, "id": "$paciente_info._id", "nombre": "$paciente_info.pii.nombre"}},
        {"$sort": {"nombre": 1}}
    ]
    try:
        cursor = mongo_db.turnos.aggregate(pipeline)
        pacientes = await cursor.to_list(length=None)
        return pacientes
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error de agregación en Mongo: {e}")

@app.get("/paciente/{paciente_id}/turnos")
async def get_turnos_del_paciente(
    paciente_id: str, 
    current_user: UsuarioEnDB = Depends(get_current_user)
):
    if mongo_db is None: raise HTTPException(503, "MongoDB no conectado")
    if "PACIENTE" in current_user.roles and current_user.id != paciente_id:
        if "MEDICO" not in current_user.roles: # Permitir a Médicos ver
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="No autorizado")
    try:
        # --- LÓGICA DE ACTUALIZACIÓN DE TURNO (SIMPLE) ---
        # Usamos UTC para la comparación, ya que es la zona horaria del sistema de FastAPI/MongoDB
        ahora_utc = datetime.now(timezone.utc)
        
        # Filtro: Turnos PENDIENTES cuya fecha (ts) es anterior a AHORA
        update_filter = {
            "paciente_id": paciente_id,
            "estado": "pendiente", # <-- Usa minúsculas si así lo guardas
            "ts": {"$lt": ahora_utc} 
        }
        
        # Acción: Cambiar el estado
        update_set = {
            "$set": {"estado": "NO_ASISTIO", "updated_at": ahora_utc}
        }

        # Ejecutar la actualización masiva (esto es eficiente)
        await mongo_db.turnos.update_many(
            update_filter, 
            update_set
        )
        # ---------------------------------------------------
        
        # Consulta para devolver los turnos (ahora actualizados)
        pipeline = [
            {"$match": {"paciente_id": paciente_id}},
            {"$sort": {"ts": 1}},
            {"$lookup": {"from": "usuarios", "localField": "medico_id", "foreignField": "_id", "as": "medico_info"}},
            {"$unwind": {"path": "$medico_info", "preserveNullAndEmptyArrays": True}},
            {"$project": {
                "_id": 1, "ts": 1, "estado": 1, "especialidad": 1, "sede": 1,
                "medico_nombre": { "$ifNull": [ "$medico_info.pii.nombre", "N/A" ] }
            }}
        ]
        
        cursor = mongo_db.turnos.aggregate(pipeline)
        turnos = await cursor.to_list(length=100)
        return parse_json(turnos)
    
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error al obtener/actualizar turnos: {e}")

# ---
# REQ 5: Evaluación de Riesgos
# ---

@app.get("/paciente/{paciente_id}/familiares_con_riesgo")
async def get_familiares_con_riesgo(paciente_id: str, riesgo: str = Query("diabetes", description="Riesgo a buscar"), current_user: UsuarioEnDB = Depends(get_current_user)):
    if neo4j_driver is None: raise HTTPException(503, "Neo4j no conectado")
    query = """
    MATCH (p:Usuario {userId: $id})-[:ES_FAMILIAR_DE*1..2]-(f:Usuario)
    WHERE f.userId <> $id
    MATCH (f)-[:TIENE_RIESGO]->(r:Riesgo {tipo: $riesgo})
    RETURN DISTINCT f.nombre AS nombre_familiar, r.tipo AS riesgo
    """
    try:
        async with neo4j_driver.session(database="neo4j") as session:
            result = await session.run(query, id=paciente_id, riesgo=riesgo)
            familiares = [record.data() async for record in result]
            return {"pacienteId": paciente_id, "familiares_con_riesgo": familiares}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error de Neo4j: {e}")

@app.post("/paciente/{paciente_id}/asignar_riesgo", status_code=status.HTTP_201_CREATED)
async def asignar_riesgo_a_paciente(
    paciente_id: str, 
    riesgo_in: RiesgoAsignar, 
    current_user: UsuarioEnDB = Depends(get_current_user)
):
    if neo4j_driver is None: raise HTTPException(503, "Neo4j no conectado")
    if "MEDICO" not in current_user.roles:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="No autorizado (se requiere rol MEDICO)")
    query = """
    MATCH (p:Usuario:Paciente {userId: $paciente_id})
    MERGE (r:Riesgo {tipo: $tipo_riesgo})
    MERGE (p)-[rel:TIENE_RIESGO]->(r)
    RETURN rel
    """
    try:
        async with neo4j_driver.session(database="neo4j") as session:
            result = await session.run(query, paciente_id=paciente_id, tipo_riesgo=riesgo_in.tipo)
            summary = await result.consume()
            if not summary.counters.relationships_created and not summary.counters.relationships_matched:
                 raise HTTPException(status_code=404, detail="Paciente no encontrado en Neo4j")
    except Exception as e:
        if isinstance(e, HTTPException): raise e
        raise HTTPException(status_code=500, detail=f"Error de Neo4j: {e}")
    return {"status": "riesgo asignado al paciente en la red", "tipo": riesgo_in.tipo}

@app.post("/paciente/{paciente_id}/calcular_riesgo")
async def calcular_riesgo(
    paciente_id: str, 
    riesgo: str = Query(..., description="Tipo de riesgo a calcular (ej: 'diabetes', 'hipertension')"), 
    current_user: UsuarioEnDB = Depends(get_current_user)
):
    if mongo_db is None: raise HTTPException(503, "MongoDB no conectado")
    score = "bajo"
    motivo = "Valores normales"
    if riesgo == "diabetes":
        cursor_habitos = mongo_db.habitos.find({
            "paciente_id": paciente_id, "tipo": "glucosa",
            "ts": {"$gte": datetime.now(timezone.utc) - timedelta(days=30)}
        }).sort("ts", -1)
        cursor_visitas = mongo_db.visitas_medicas.find({
            "paciente_id": paciente_id, "diagnosticos": {"$regex": "diabetes", "$options": "i"}
        })
        habitos = await cursor_habitos.to_list(length=100)
        visita_con_diagnostico = await cursor_visitas.fetch_next
        if visita_con_diagnostico:
            score = "alto"
            motivo = "Paciente ya diagnosticado con diabetes o prediabetes."
        elif habitos:
            avg_glucosa = sum(h['valor'] for h in habitos) / len(habitos)
            if avg_glucosa > 125:
                score = "alto"
                motivo = f"Promedio de glucosa en ayunas elevado ({avg_glucosa:.0f} mg/dL)."
            elif avg_glucosa > 100:
                score = "medio"
                motivo = f"Promedio de glucosa ({avg_glucosa:.0f} mg/dL) sugiere prediabetes."
    elif riesgo == "hipertension":
        cursor_habitos = mongo_db.habitos.find({
            "paciente_id": paciente_id, "tipo": "presion_sistolica", 
            "ts": {"$gte": datetime.now(timezone.utc) - timedelta(days=30)}
        }).sort("ts", -1)
        cursor_visitas = mongo_db.visitas_medicas.find({
            "paciente_id": paciente_id, "diagnosticos": {"$regex": "hipertension", "$options": "i"}
        })
        habitos = await cursor_habitos.to_list(length=100)
        visita_con_diagnostico = await cursor_visitas.fetch_next
        if visita_con_diagnostico:
            score = "alto"
            motivo = "Paciente ya diagnosticado con hipertensión."
        elif habitos:
            avg_sistolica = sum(h['valor'] for h in habitos) / len(habitos)
            if avg_sistolica > 140:
                score = "alto"
                motivo = f"Promedio de presión sistólica elevada ({avg_sistolica:.0f} mmHg)."
            elif avg_sistolica > 130:
                score = "medio"
                motivo = f"Promedio de presión sistólica ({avg_sistolica:.0f} mmHg) en rango de prehipertensión."
        else:
             motivo = "No hay datos de presión sistólica suficientes."
    else:
        raise HTTPException(status_code=400, detail=f"El cálculo de riesgo para '{riesgo}' no está implementado.")
    riesgo_calculado = {
        "tipo": riesgo, "score": score, "motivo": motivo,
        "calculado_en": datetime.now(timezone.utc)
    }
    await mongo_db.usuarios.update_one(
        {"_id": paciente_id},
        {"$set": {f"paciente.riesgo_calculado_{riesgo}": riesgo_calculado}}
    )
    return riesgo_calculado

@app.patch("/turnos/{turno_id}/cancelar")
async def cancelar_turno_paciente(
    turno_id: str, 
    current_user: UsuarioEnDB = Depends(get_current_user)
):
    """
    Permite a un paciente cancelar su propio turno.
    Actualiza el estado a 'CANCELADO' y envía un evento a Redis.
    """
    if mongo_db is None: raise HTTPException(503, "MongoDB no conectado")
    if redis_client is None: raise HTTPException(503, "Redis no conectado")
    
    # 1. Obtener el turno para verificar que pertenezca al usuario logueado
    turno = await mongo_db.turnos.find_one({"_id": turno_id})
    if not turno:
        raise HTTPException(status_code=404, detail="Turno no encontrado")
        
    if turno.get("paciente_id") != current_user.id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="No autorizado para cancelar este turno")
        
    if turno.get("estado").upper() != "PENDIENTE":
        raise HTTPException(status_code=400, detail=f"El turno ya fue {turno.get('estado').upper()}")

    # 2. Actualizar el estado en MongoDB
    result = await mongo_db.turnos.update_one(
        {"_id": turno_id}, 
        {"$set": {"estado": "CANCELADO", "updated_at": datetime.now(timezone.utc)}}
    )

    if result.matched_count == 0:
        raise HTTPException(status_code=404, detail="Turno no encontrado o ya cancelado")

    # 3. Notificar vía Redis (Sistema de Eventos - Req 4)
    canal = "eventos_turnos"
    mensaje = json.dumps({"evento": "TURNO_CANCELADO", "turno_id": turno_id, "paciente_id": current_user.id})
    await redis_client.publish(canal, mensaje)
    
    return {"status": "turno cancelado exitosamente", "turno_id": turno_id}


@app.get("/medicos")
async def get_all_medicos(current_user: UsuarioEnDB = Depends(get_current_user)):
    """
    REQ: Obtiene la lista de todos los médicos registrados.
    """
    if mongo_db is None: raise HTTPException(503, "MongoDB no conectado")
    
    # La validación de current_user asegura que solo usuarios logueados accedan
    
    pipeline = [
        {"$match": {"roles": "MEDICO"}},
        {"$project": {
            "_id": 1, 
            "nombre": "$pii.nombre",
            # Nota: la especialidad en el modelo de carga es un campo simple, pero el esquema permite una lista.
            # Aquí asumimos que está en $medico.perfil.especialidad
            "especialidad": "$medico.perfil.especialidad" 
        }}
    ]
    try:
        cursor = mongo_db.usuarios.aggregate(pipeline)
        medicos = await cursor.to_list(length=None)
        
        # Formatear la especialidad si es una lista o nula
        for medico in medicos:
             especialidad = medico.get("especialidad")
             if isinstance(especialidad, list):
                 medico["especialidad"] = ", ".join(especialidad)
             elif not especialidad:
                 # Si el campo no existe o es None/vacío, ponemos un valor por defecto
                 medico["especialidad"] = "General"

        return parse_json(medicos)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error de agregación en Mongo: {e}")
    

@app.get("/medico/{medico_id}/turnos_del_dia")
async def get_turnos_del_dia(medico_id: str, current_user: UsuarioEnDB = Depends(get_current_user)):
    """
    Obtiene los turnos programados para el día de hoy del médico especificado.
    """
    if mongo_db is None: raise HTTPException(503, "MongoDB no conectado")

    # Control de acceso: Solo el médico o un administrador pueden ver sus turnos
    if str(current_user.id) != medico_id and "ADMINISTRADOR" not in current_user.roles:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="No autorizado para ver estos turnos")
    
    # 1. Calcular el inicio y el fin del día actual en UTC
    now_utc = datetime.now(timezone.utc)
    today_start = now_utc.replace(hour=0, minute=0, second=0, microsecond=0)
    today_end = today_start + timedelta(days=1)
    
    # 2. Pipeline de agregación
    pipeline = [
        {"$match": {
            "medico_id": medico_id,
            "ts": {"$gte": today_start, "$lt": today_end}
        }},
        {"$sort": {"ts": 1}}, # Ordenar por hora del turno
        # Buscar la información del paciente
        {"$lookup": {"from": "usuarios", "localField": "paciente_id", "foreignField": "_id", "as": "paciente_info"}},
        {"$unwind": {"path": "$paciente_info", "preserveNullAndEmptyArrays": True}},
        {"$project": {
            "_id": 1, 
            "ts": 1, 
            "estado": 1, 
            "especialidad": 1, 
            "sede": 1,
            "paciente_id": "$paciente_info._id",
            "paciente_nombre": { "$ifNull": [ "$paciente_info.pii.nombre", "Paciente Eliminado" ] }
        }}
    ]
    
    try:
        cursor = mongo_db.turnos.aggregate(pipeline)
        turnos = await cursor.to_list(length=None)
        return parse_json(turnos)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error al obtener turnos del día: {e}")
    
# --- Correr la App ---
if __name__ == "__main__":
    print("Iniciando API Políglota v4.3.1 (Modelo Rico Corregido) en http://127.0.0.1:8000")
    print("Dashboard Profesional/Admin (Req 6) en http://127.0.0.1:5500/index.html")
    print("Dashboard Paciente (Req 1,2,4) en http://127.0.0.1:5500/paciente.html")
    uvicorn.run("main:app", host="127.0.0.1", port=8000, reload=True)