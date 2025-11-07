import os
import asyncio
import json
import redis.asyncio as redis
from neo4j import AsyncGraphDatabase
from dotenv import load_dotenv

# --- Cargar Variables de Entorno ---
load_dotenv()
NEO4J_URI = os.getenv("NEO4J_URI")
NEO4J_AUTH = (os.getenv("NEO4J_USER"), os.getenv("NEO4J_PASS"))
REDIS_HOST = os.getenv("REDIS_HOST")
REDIS_PORT = int(os.getenv("REDIS_PORT", 0))
REDIS_PASS = os.getenv("REDIS_PASS")

# Canal de Redis que la API usa para publicar tareas
CANAL_TAREAS_NEO4J = "neo4j_tasks"

# --- Queries de Neo4j ---

# Query para crear un nodo de usuario (Paciente o Médico)
async def crear_nodo_usuario(session, label, user_id, nombre):
    # Validamos la etiqueta para evitar inyección de Cypher
    if label not in ["Paciente", "Medico"]:
        print(f"[WORKER] Error: Etiqueta no válida recibida: {label}")
        return
        
    print(f"[WORKER] Procesando: Creando Nodo {label} ({nombre})...")
    # Usamos f-string de forma SEGURA solo para la ETIQUETA
    query = f"""
    MERGE (u:Usuario {{userId: $id}})
    SET u.nombre = $nombre, u:{label}
    """
    try:
        await session.run(query, id=user_id, nombre=nombre)
        print(f"[WORKER] Éxito: Nodo {label} ({nombre}) creado/actualizado.")
    except Exception as e:
        print(f"[WORKER] Error al ejecutar Cypher (crear_nodo_usuario): {e}")

# Query para crear la relación Paciente -> Médico
async def crear_rel_paciente_medico(session, paciente_id, medico_id):
    print(f"[WORKER] Procesando: Asignando Paciente ({paciente_id}) a Médico ({medico_id})...")
    query = """
    MATCH (p:Usuario:Paciente {userId: $paciente_id})
    MATCH (m:Usuario:Medico {userId: $medico_id})
    MERGE (p)-[r:ES_PACIENTE_DE]->(m)
    """
    try:
        await session.run(query, paciente_id=paciente_id, medico_id=medico_id)
        print(f"[WORKER] Éxito: Relación Paciente-Médico creada.")
    except Exception as e:
        print(f"[WORKER] Error al ejecutar Cypher (crear_rel_paciente_medico): {e}")

# Query para crear la relación Paciente -> Riesgo
async def crear_rel_paciente_riesgo(session, paciente_id, tipo_riesgo):
    print(f"[WORKER] Procesando: Asignando Riesgo ({tipo_riesgo}) a Paciente ({paciente_id})...")
    query = """
    MATCH (p:Usuario:Paciente {userId: $paciente_id})
    MERGE (r:Riesgo {tipo: $tipo_riesgo})
    MERGE (p)-[rel:TIENE_RIESGO]->(r)
    """
    try:
        await session.run(query, paciente_id=paciente_id, tipo_riesgo=tipo_riesgo)
        print(f"[WORKER] Éxito: Relación Paciente-Riesgo creada.")
    except Exception as e:
        print(f"[WORKER] Error al ejecutar Cypher (crear_rel_paciente_riesgo): {e}")


# --- Función Principal del Worker ---

async def run_worker():
    """
    Se conecta a Redis y Neo4j y procesa tareas de forma asíncrona.
    """
    print("Iniciando Worker de Neo4j...")
    
    # Conectar a Redis
    try:
        redis_client = redis.Redis(host=REDIS_HOST, port=REDIS_PORT, password=REDIS_PASS, decode_responses=True)
        await redis_client.ping()
        pubsub = redis_client.pubsub()
        await pubsub.subscribe(CANAL_TAREAS_NEO4J)
        print(f"Worker conectado a Redis. Escuchando canal '{CANAL_TAREAS_NEO4J}'...")
    except Exception as e:
        print(f"Error fatal: No se pudo conectar a Redis. {e}")
        return

    # Conectar a Neo4j
    try:
        neo4j_driver = AsyncGraphDatabase.driver(NEO4J_URI, auth=NEO4J_AUTH)
        await neo4j_driver.verify_connectivity()
        print("Worker conectado a Neo4j Aura.")
    except Exception as e:
        print(f"Error fatal: No se pudo conectar a Neo4j. {e}")
        await redis_client.close()
        return

    # Bucle principal: escuchar mensajes de Redis
    try:
        async for message in pubsub.listen():
            if message['type'] == 'message':
                data = json.loads(message['data'])
                action = data.get('action')
                
                async with neo4j_driver.session(database="neo4j") as session:
                    # Enrutador de Tareas
                    if action == "create_user_node":
                        await crear_nodo_usuario(session, data['label'], data['id'], data['nombre'])
                        
                    elif action == "create_rel_paciente_medico":
                        await crear_rel_paciente_medico(session, data['paciente_id'], data['medico_id'])
                        
                    elif action == "create_rel_paciente_riesgo":
                        await crear_rel_paciente_riesgo(session, data['paciente_id'], data['tipo_riesgo'])
                        
                    else:
                        print(f"[WORKER] Advertencia: Acción desconocida recibida: {action}")

    except KeyboardInterrupt:
        print("\nApagando worker...")
    finally:
        await pubsub.close()
        await redis_client.close()
        await neo4j_driver.close()
        print("Worker desconectado.")

if __name__ == "__main__":
    try:
        asyncio.run(run_worker())
    except KeyboardInterrupt:
        print("\nWorker detenido por el usuario.")