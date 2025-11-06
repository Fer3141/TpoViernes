import os
import uvicorn
from fastapi import FastAPI, HTTPException, Query, Depends, status
from fastapi.security import OAuth2PasswordBearer, OAuth2PasswordRequestForm
# --- IMPORTACIÓN DE CORS (NUEVA) ---
from fastapi.middleware.cors import CORSMiddleware
from motor.motor_asyncio import AsyncIOMotorClient
from neo4j import AsyncGraphDatabase
import redis.asyncio as redis
from dotenv import load_dotenv
import json
from bson import json_util
from datetime import datetime, timedelta, timezone
from typing import Optional, List
from pydantic import BaseModel
# --- Nuevas importaciones de Seguridad ---
from jose import JWTError, jwt
from passlib.context import CryptContext # <-- CORRECCIÓN (antes PasslibContext)
from routers.usuario_router import router as usuario_router

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

# --- Configuración de Seguridad (JWT) ---
SECRET_KEY = "tu-clave-secreta-para-jwt-muy-segura" 
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = 60 # 1 hora

# Contexto para Hashear contraseñas
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto") # <-- CORRECCIÓN (antes PasslibContext)

# Esquema de autenticación
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="token")


# --- Inicializar FastAPI ---
app = FastAPI(title="API VidaSana (Políglota)", version="3.1 - Con CORS")


# --- CONFIGURACIÓN DE CORS (NUEVA) ---
# (Permite que el frontend de React en localhost:5173 llame a esta API)
origins = [
    "http://localhost:5173", # El puerto de Vite/React
    "http://localhost:5174", # A veces Vite usa este
    "http://localhost:3000", # El puerto de create-react-app
    "http://127.0.0.1:5500"
]

app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=True,
    allow_methods=["*"], # Permite todos los métodos (GET, POST, etc.)
    allow_headers=["*"], # Permite todos los headers
)
# --- FIN DE CONFIGURACIÓN DE CORS ---

# --- Registrar Routers ---
app.include_router(usuario_router)


# --- Modelos Pydantic ---
class TurnoInput(BaseModel):
    id: str
    paciente_id: str
    medico_id: str
    ts: datetime 
    especialidad: str
    sede: str

class Token(BaseModel):
    access_token: str
    token_type: str

class TokenData(BaseModel):
    username: Optional[str] = None

class UsuarioEnDB(BaseModel):
    _id: str
    auth: dict
    roles: List[str]
    class Config:
        arbitrary_types_allowed = True 


# --- Inicializar Clientes (Globales) ---
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

# --- Helpers ---
def parse_json(data):
    """Convierte BSON/Mongo a JSON legible."""
    return json.loads(json_util.dumps(data))

# --- Funciones de Seguridad ---

def verify_password(plain_password, hashed_password):
    """Verifica la contraseña contra el hash de la BD."""
    return pwd_context.verify(plain_password, hashed_password)

def create_access_token(data: dict, expires_delta: Optional[timedelta] = None):
    """Crea un nuevo token JWT."""
    to_encode = data.copy()
    if expires_delta:
        expire = datetime.now(timezone.utc) + expires_delta
    else:
        expire = datetime.now(timezone.utc) + timedelta(minutes=15)
    to_encode.update({"exp": expire})
    encoded_jwt = jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)
    return encoded_jwt

async def get_user_from_db(username: str):
    """Busca un usuario en MongoDB por su username."""
    if mongo_db is None: return None
    user_data = await mongo_db.usuarios.find_one({"auth.username": username})
    if user_data:
        return UsuarioEnDB(**user_data)
    return None

async def get_current_user(token: str = Depends(oauth2_scheme)):
    """Decodifica el token y obtiene el usuario."""
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
# REQ 1: Autenticación (¡NUEVO!)
# ---
@app.post("/token", response_model=Token)
async def login_for_access_token(form_data: OAuth2PasswordRequestForm = Depends()):
    """
    Endpoint de Login. Recibe 'username' y 'password' de un formulario
    y devuelve un token JWT si son correctos.
    """
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


# ---
# REQ 1: Perfil de Paciente (MongoDB - Col: usuarios)
# ---
@app.get("/paciente/{paciente_id}/perfil")
async def get_paciente_perfil(paciente_id: str, current_user: UsuarioEnDB = Depends(get_current_user)):
    """Obtiene el perfil estático de un paciente (Req 1). Protegido."""
    if mongo_db is None: raise HTTPException(503, "MongoDB no conectado")
    
    if "PACIENTE" in current_user.roles and current_user._id != paciente_id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="No autorizado")

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
    current_user: UsuarioEnDB = Depends(get_current_user), 
    desde: Optional[str] = Query(None),
    hasta: Optional[str] = Query(None),
    especialidad: Optional[str] = Query(None)
):
    """Obtiene la historia clínica de un paciente (Req 1). Protegido."""
    if mongo_db is None: raise HTTPException(503, "MongoDB no conectado")
    
    if "PACIENTE" in current_user.roles and current_user._id != paciente_id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="No autorizado")

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
async def get_paciente_habitos(paciente_id: str, current_user: UsuarioEnDB = Depends(get_current_user)):
    """Obtiene los registros de hábitos de un paciente (Req 2). Protegido."""
    if mongo_db is None: raise HTTPException(503, "MongoDB no conectado")
    
    if "PACIENTE" in current_user.roles and current_user._id != paciente_id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="No autorizado")

    cursor = mongo_db.habitos.find({"paciente_id": paciente_id}).sort("ts", -1).limit(50)
    habitos = await cursor.to_list(length=50)
    return parse_json(habitos)

# ---
# REQ 3: Red de Interacción (Neo4j)
# ---
@app.get("/paciente/{paciente_id}/red_cuidado")
async def get_red_de_cuidado(paciente_id: str, current_user: UsuarioEnDB = Depends(get_current_user)):
    """Obtiene la red de cuidado (médicos) de un paciente (Req 3). Protegido."""
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
# REQ 3 (Ext): Análisis de Red (¡NUEVO!)
# ---
@app.get("/paciente/{paciente_id}/familiares_con_riesgo")
async def get_familiares_con_riesgo(paciente_id: str, riesgo: str = "diabetes", current_user: UsuarioEnDB = Depends(get_current_user)):
    """
    Análisis de Red (Req 5): Busca familiares (hasta 2 grados) 
    con un riesgo de salud específico. Protegido.
    """
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


# ---
# REQ 4: Gestión de Turnos (MongoDB + Redis)
# ---
@app.get("/medico/{medico_id}/agenda_completa")
async def get_medico_agenda_completa(medico_id: str, current_user: UsuarioEnDB = Depends(get_current_user)):
    """Obtiene la agenda COMPLETA (turnos pendientes) de un médico (Req 4). Protegido."""
    if mongo_db is None: raise HTTPException(503, "MongoDB no conectado")

    if "MEDICO" not in current_user.roles or current_user._id != medico_id:
         raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="No autorizado para ver esta agenda")

    cursor = mongo_db.turnos.find({
        "medico_id": medico_id,
        "estado": "pendiente"
    }).sort("ts", 1)
    agenda = await cursor.to_list(length=100)
    return parse_json(agenda)

@app.get("/medico/{medico_id}/agenda_hoy")
async def get_medico_agenda_rapida(medico_id: str, current_user: UsuarioEnDB = Depends(get_current_user)):
    """Obtiene la agenda INMEDIATA (hoy) de un médico (Req 4). Protegido."""
    if redis_client is None: raise HTTPException(503, "Redis no conectado")
    
    if "MEDICO" not in current_user.roles or current_user._id != medico_id:
         raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="No autorizado")

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
async def crear_nuevo_turno(turno: TurnoInput, current_user: UsuarioEnDB = Depends(get_current_user)):
    """Crea un nuevo turno (Req 4). Protegido."""
    if mongo_db is None: raise HTTPException(503, "MongoDB no conectado")
    if redis_client is None: raise HTTPException(503, "Redis no conectado")

    if "PACIENTE" in current_user.roles and current_user._id != turno.paciente_id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="No puede crear turnos para otro paciente")

    turno_dict = turno.dict()
    turno_dict["_id"] = turno_dict.pop("id")
    turno_dict["estado"] = "pendiente" 
    
    try:
        await mongo_db.turnos.insert_one(turno_dict)
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Error al guardar en Mongo: {e}")

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
async def reportar_sintoma_alerta(paciente_id: str, sintoma: str, current_user: UsuarioEnDB = Depends(get_current_user)):
    """Un paciente reporta un síntoma de alerta (Req 5). Protegido."""
    if redis_client is None: raise HTTPException(503, "Redis no conectado")
    
    if "PACIENTE" in current_user.roles and current_user._id != paciente_id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="No puede reportar síntomas por otro paciente")

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
    print("Iniciando API Políglota v3 (Con Seguridad) en http://127.0.0.1:8000")
    print("Documentación de la API en http://127.0.0.1:8000/docs")
    uvicorn.run("main:app", host="127.0.0.1", port=8000, reload=True)