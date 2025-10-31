import os
from neo4j import GraphDatabase
from dotenv import load_dotenv

# Cargar variables de entorno
load_dotenv()
URI = os.getenv("NEO4J_URI")
AUTH = (os.getenv("NEO4J_USER"), os.getenv("NEO4J_PASS"))

# --- Datos de ejemplo (IDs deben coincidir con Mongo) ---
NODOS_USUARIO = [
    {"id": "usr-001", "nombre": "Juan Lopez", "rol": "Paciente"},
    {"id": "usr-003", "nombre": "Ana Gomez", "rol": "Medico"},
]
RELACIONES = [
    # Relación Médico-Paciente (Req 3)
    {"u1": "usr-001", "rel": "ES_PACIENTE_DE", "u2": "usr-003"},
]

# --- Funciones de Carga ---
def cargar_nodos(tx):
    print("Cargando nodos en Neo4j...")
    for nodo in NODOS_USUARIO:
        tx.run("MERGE (u:Usuario {userId: $id}) SET u.nombre = $nombre, u.rol = $rol",
               id=nodo['id'], nombre=nodo['nombre'], rol=nodo['rol'])

def cargar_relaciones(tx):
    print("Cargando relaciones en Neo4j...")
    for rel in RELACIONES:
        tx.run(f"MATCH (a:Usuario {{userId: $u1}}) MATCH (b:Usuario {{userId: $u2}}) MERGE (a)-[:{rel['rel']}]->(b)",
               u1=rel['u1'], u2=rel['u2'])
# --- Script de Carga ---
try:
    print(f"Conectando a Neo4j Aura ({URI})...")
    # Usamos el driver sincrónico solo para la carga inicial
    with GraphDatabase.driver(URI, auth=AUTH) as driver:
        driver.verify_connectivity()
        print("¡Conexión a Neo4j exitosa!")
        
        with driver.session(database="neo4j") as session:
            # Limpiar DB
            session.run("MATCH (n) DETACH DELETE n")
            print("Base de Neo4j limpiada.")
            
            # Cargar datos
            cargar_nodos(session)
            cargar_relaciones(session)
            
        print("¡Datos de Neo4j cargados exitosamente!")

except Exception as e:
    print(f"ERROR cargando Neo4j: {e}")