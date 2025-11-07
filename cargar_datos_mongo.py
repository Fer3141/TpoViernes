import os
import pymongo
from pymongo import ReplaceOne
from datetime import datetime
from dotenv import load_dotenv
from passlib.context import CryptContext 

# --- Configuración de Hash ---
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto") 

def get_password_hash(password):
    """Genera un hash bcrypt para la contraseña."""
    return pwd_context.hash(password)

# Cargar variables de entorno del archivo .env
load_dotenv()
MONGO_URI = os.getenv("MONGO_URI")
DB_NAME = os.getenv("DB_NAME")

# --- Datos de ejemplo (¡MODELO DE DATOS ACTUALIZADO!) ---
USUARIOS = [
    {
      "_id": "usr-001", 
      "auth": {"username": "ljuan", "password_hash": get_password_hash("pass123")}, 
      "roles": ["PACIENTE"],
      "pii": {
          "dni": "12345678", 
          "nombre": "Juan Lopez",
          "email": "juan@example.com",
          "fecha_nac": "1997-12-20",
          "telefono": "+54-11-5555-1234",
          "direccion": "Av. Rivadavia 742, Buenos Aires",
          "pais": "AR",
          "genero": "M"
      },
      "paciente": {
        "obra_social": "OSDE 210",
        "numero_afiliado": "123456789-01",
        "clinico": {
            "alergias": ["penicilina"],
            "grupo_sanguineo": "O+"
        },
        "resumen": {"ultima_visita_id": "enc-002"}
      }
    },
    {
      "_id": "usr-002", 
      "auth": {"username": "mlopez", "password_hash": get_password_hash("pass123")}, 
      "roles": ["PACIENTE"],
      "pii": {
          "dni": "23456789", 
          "nombre": "Maria Lopez",
          "email": "maria@example.com",
          "fecha_nac": "1990-05-15",
          "telefono": "+54-11-5555-5678",
          "direccion": "Calle Falsa 123, CABA",
          "pais": "AR",
          "genero": "F"
      },
      "paciente": {
        "obra_social": "Swiss Medical",
        "numero_afiliado": "987654321-02",
        "clinico": {
            "antecedentes": ["diabetes"],
            "grupo_sanguineo": "A+"
        },
        "resumen": {}
      }
    },
    {
      "_id": "usr-003", 
      "auth": {"username": "agomez", "password_hash": get_password_hash("pass123")}, 
      "roles": ["MEDICO"],
      "pii": {
          "dni": "25111222", 
          "nombre": "Ana Gomez",
          "email": "agomez@vidasana.com",
          "fecha_nac": "1985-10-01",
          "telefono": "+54-11-5555-9012",
          "direccion": "Av. Corrientes 2030, Buenos Aires",
          "pais": "AR",
          "genero": "F"
      },
      "medico": {
          "perfil": {
              "matricula": "MP-12345", 
              "especialidad": "cardiología"
            }
        }
    },
    {
      "_id": "usr-admin", 
      "auth": {"username": "admin", "password_hash": get_password_hash("adminpass")}, 
      "roles": ["ADMINISTRADOR"],
      "pii": {
          "dni": "00000000", 
          "nombre": "Admin General",
          "email": "admin@vidasana.com",
          "fecha_nac": "1980-01-01"
        }
    }
]
# (Resto de las colecciones: VISITAS_MEDICAS, HABITOS_DATA, TURNOS... quedan igual)
# ... (PEGAR EL RESTO DE TU SCRIPT DE CARGA AQUÍ) ...

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

# --- Script de Carga (¡MODIFICADO!) ---
try:
    print(f"Conectando a MongoDB Atlas (DB: {DB_NAME})...")
    client = pymongo.MongoClient(MONGO_URI)
    db = client[DB_NAME]
    client.admin.command('ping')
    print("¡Conexión a Mongo exitosa!")
    
    # Limpiamos las colecciones de datos de EJEMPLO.
    db.visitas_medicas.delete_many({})
    db.habitos.drop() 
    db.turnos.delete_many({})
    print("Contenido de colecciones (visitas, habitos, turnos) limpiado.")

    print("Actualizando usuarios base (Juan, Maria, Ana, Admin)...")
    user_ops = [
        ReplaceOne({"_id": user["_id"]}, user, upsert=True) for user in USUARIOS
    ]
    if user_ops:
        db.usuarios.bulk_write(user_ops)
        print(f"{len(user_ops)} usuarios base actualizados/creados.")
    
    db.visitas_medicas.insert_many(VISITAS_MEDICAS)
    db.turnos.insert_many(TURNOS)
    
    try:
        db.create_collection("habitos", 
            timeseries={"timeField": "ts", "metaField": "paciente_id", "granularity": "hours"}
        )
        print("Colección 'habitos' (Time Series) creada.")
    except pymongo.errors.CommandError:
        print("Colección 'habitos' ya existe.")
        
    db.habitos.insert_many(HABITOS_DATA)
    print("¡Datos de MongoDB cargados/actualizados exitosamente!")

except Exception as e:
    print(f"ERROR cargando MongoDB: {e}")
finally:
    if 'client' in locals():
        client.close()