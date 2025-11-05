import os
import pymongo
from datetime import datetime
from dotenv import load_dotenv
from passlib.context import CryptContext # <-- Importa la clase correcta

# --- Configuración de Hash ---
# Usa CryptContext (la clase)
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto") 

def get_password_hash(password):
    """Genera un hash bcrypt para la contraseña."""
    return pwd_context.hash(password)

# Cargar variables de entorno del archivo .env
load_dotenv()
MONGO_URI = os.getenv("MONGO_URI")
DB_NAME = os.getenv("DB_NAME")

# --- Datos de ejemplo (Modelo Escalable) ---
USUARIOS = [
    {
      "_id": "usr-001", 
      # Guarda la contraseña "pass123" hasheada
      "auth": {"username": "ljuan", "password_hash": get_password_hash("pass123")}, 
      "roles": ["PACIENTE"],
      "pii": {"dni": "12345678", "nombre": "Juan Lopez"},
      "paciente": {
        "obra_social": "OSDE 210",
        "clinico": {"alergias": ["penicilina"]},
        "resumen": {"ultima_visita_id": "enc-002"}
      }, "medico": None
    },
    {
      "_id": "usr-002", 
      # Guarda la contraseña "pass123" hasheada
      "auth": {"username": "mlopez", "password_hash": get_password_hash("pass123")}, 
      "roles": ["PACIENTE"],
      "pii": {"dni": "23456789", "nombre": "Maria Lopez"},
      "paciente": {
        "obra_social": "Swiss Medical",
        "clinico": {"antecedentes": ["diabetes"]},
        "resumen": {}
      }, "medico": None
    },
    {
      "_id": "usr-003", 
      # Guarda la contraseña "pass123" hasheada
      "auth": {"username": "agomez", "password_hash": get_password_hash("pass123")}, 
      "roles": ["MEDICO"],
      "pii": {"dni": "25111222", "nombre": "Ana Gomez"},
      "paciente": None,
      "medico": {"perfil": {"matricula": "MP-12345", "especialidad": "cardiología"}}
    }
]
VISITAS_MEDICAS = [
    {"_id": "enc-001", "paciente_id": "usr-001", "medico_id": "usr-003", "ts": datetime(2025, 9, 25, 9, 30), "especialidad": "gastroenterologia"},
    {"_id": "enc-002", "paciente_id": "usr-001", "medico_id": "usr-003", "ts": datetime(2025, 10, 15, 11, 0), "especialidad": "cardiología"},
    {"_id": "enc-003", "paciente_id": "usr-002", "medico_id": "usr-003", "ts": datetime(2025, 10, 16, 11, 0), "especialidad": "cardiología", "diagnosticos": ["Control diabetes tipo 1"]}
]
HABITOS_DATA = [
    {"ts": datetime(2025, 10, 25, 7, 0), "paciente_id": "usr-001", "tipo": "horas dormidas", "valor": 6.5},
    {"ts": datetime(2025, 10, 25, 12, 30), "paciente_id": "usr-001", "tipo": "alimentacion", "valor": 450},
    {"ts": datetime(2025, 10, 26, 8, 0), "paciente_id": "usr-002", "tipo": "glucosa", "valor": 130, "notas": "en ayunas"}
]
TURNOS = [
    {"_id": "turno-001", "ts": datetime(2025, 11, 20, 9, 40), "paciente_id": "usr-001", "medico_id": "usr-003", "estado": "pendiente"},
    {"_id": "turno-002", "ts": datetime(2025, 9, 25, 9, 30), "paciente_id": "usr-001", "medico_id": "usr-003", "estado": "realizado"}
]

# --- Script de Carga ---
try:
    print(f"Conectando a MongoDB Atlas (DB: {DB_NAME})...")
    # Usamos PyMongo (sincrónico) solo para la carga inicial
    client = pymongo.MongoClient(MONGO_URI)
    db = client[DB_NAME]
    client.admin.command('ping')
    print("¡Conexión a Mongo exitosa!")
    
    # Limpiar colecciones
    db.usuarios.drop()
    db.visitas_medicas.drop()
    db.habitos.drop()
    db.turnos.drop()
    print("Colecciones de Mongo limpiadas.")

    # Insertar datos
    db.usuarios.insert_many(USUARIOS)
    db.visitas_medicas.insert_many(VISITAS_MEDICAS)
    db.turnos.insert_many(TURNOS)
    
    # Crear Colección Time Series (Req 2)
    try:
        db.create_collection("habitos", 
            timeseries={"timeField": "ts", "metaField": "paciente_id", "granularity": "hours"}
        )
        print("Colección 'habitos' (Time Series) creada.")
    except pymongo.errors.CommandError:
        print("Colección 'habitos' ya existe.")
        
    db.habitos.insert_many(HABITOS_DATA)
    print("¡Datos de MongoDB cargados exitosamente!")

except Exception as e:
    print(f"ERROR cargando MongoDB: {e}")
finally:
    if 'client' in locals():
        client.close()