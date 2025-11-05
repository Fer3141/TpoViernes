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
    {"id": "usr-002", "nombre": "Maria Lopez", "rol": "Paciente"}, # Nuevo paciente
    {"id": "usr-003", "nombre": "Ana Gomez", "rol": "Medico"},
]

# --- Nodos de Riesgo (Req 5) ---
NODOS_RIESGO = [
    {"tipo": "diabetes"},
    {"tipo": "hipertension"},
    {"tipo": "obesidad"}
]

# --- Relaciones ---
RELACIONES = [
    # Relación Médico-Paciente (Req 3)
    {"u1": "usr-001", "rel": "ES_PACIENTE_DE", "u2": "usr-003"},
    {"u1": "usr-002", "rel": "ES_PACIENTE_DE", "u2": "usr-003"},
    
    # Relación Familiar (Req 5)
    {"u1": "usr-001", "rel": "ES_FAMILIAR_DE", "u2": "usr-002"}, # Juan y Maria son familia
    {"u1": "usr-002", "rel": "ES_FAMILIAR_DE", "u2": "usr-001"},
    
    # Relación de Riesgo (Req 5)
    {"u": "usr-002", "rel": "TIENE_RIESGO", "r_tipo": "diabetes"} # Maria tiene diabetes
]

# --- Funciones de Carga ---
def cargar_nodos(tx):
    print("Cargando nodos de Usuario en Neo4j...")
    for nodo in NODOS_USUARIO:
        # --- CORRECCIÓN AQUÍ ---
        # Determina la etiqueta dinámicamente (Paciente o Medico)
        label = "Paciente" if nodo['rol'] == "Paciente" else "Medico"
        
        # Agrega la etiqueta :Paciente o :Medico usando SET
        tx.run(f"""
            MERGE (u:Usuario {{userId: $id}})
            ON CREATE SET u.nombre = $nombre, u.rol = $rol
            ON MATCH SET u.nombre = $nombre, u.rol = $rol
            SET u :{label} 
            """, id=nodo['id'], nombre=nodo['nombre'], rol=nodo['rol'])

def cargar_relaciones(tx):
    print("Cargando relaciones en Neo4j...")
    for rel in RELACIONES:
        if rel['rel'] == "ES_PACIENTE_DE":
            tx.run(f"""
                MATCH (a:Usuario {{userId: $u1}})
                MATCH (b:Usuario {{userId: $u2}})
                MERGE (a)-[:ES_PACIENTE_DE]->(b)
                """, u1=rel['u1'], u2=rel['u2'])
        
        elif rel['rel'] == "ES_FAMILIAR_DE":
            tx.run(f"""
                MATCH (a:Usuario {{userId: $u1}})
                MATCH (b:Usuario {{userId: $u2}})
                MERGE (a)-[:ES_FAMILIAR_DE]->(b)
                """, u1=rel['u1'], u2=rel['u2'])

        elif rel['rel'] == "TIENE_RIESGO":
            tx.run(f"""
                MATCH (u:Usuario {{userId: $u}})
                MATCH (r:Riesgo {{tipo: $r_tipo}})
                MERGE (u)-[:TIENE_RIESGO]->(r)
                """, u=rel['u'], r_tipo=rel['r_tipo'])

# --- Script de Carga ---
try:
    print(f"Conectando a Neo4j Aura ({URI})...")
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