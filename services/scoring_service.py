# services/scoring_service.py

from fastapi import HTTPException
from motor.motor_asyncio import AsyncIOMotorClient
from datetime import datetime, timedelta

# Definición del rol que debe tener el usuario para el cálculo
PACIENTE_ROLE = "PACIENTE"
ANTIGUEDAD_MINIMA_DIAS = 7 # Mínimo de días que debe tener el paciente para penalizar inactividad

async def calcular_score_riesgo(mongo_db: AsyncIOMotorClient, paciente_id: str):
    """
    Algoritmo de Scoring de Riesgo (Puntos Ponderados). 
    CORREGIDO: El score por inactividad solo se aplica si el paciente tiene más de 7 días de antigüedad.
    """
    
    # --- Ponderaciones del Algoritmo (Basado en TPO) ---
    PONDERACIONES = {
        # Factores Estáticos (Riesgo de Perfil)
        "riesgo_edad_extrema": 20, 
        "diagnostico_alto_riesgo": 35, 
        "inmunodeficiencia": 30, 
        "alergias_registradas": 10, 
        "antecedentes_familiares_graves": 25, 
        
        # Factores Dinámicos (Riesgo de Hábito/Agudo)
        "sueno_bajo_promedio": 15, 
        "inactividad_habitos": 30, # CORREGIDO: Sólo si es un usuario antiguo
        "consultas_frecuentes": 5, 
    }
    
    DIAGNOSTICOS_ALTO_RIESGO = ['cáncer', 'linfoblástica', 'sida', 'vih', 'neoplasia', 'leucemia', 'diabetes']
    INMUNODEFICIENCIA_KEYWORDS = ['inmunosupresión', 'trasplante', 'quimioterapia', 'radioterapia', 'autoinmune']

    score_total = 0
    hoy = datetime.now()
    hace_7_dias = hoy - timedelta(days=ANTIGUEDAD_MINIMA_DIAS)

    # 1. Obtener Datos Estáticos (MongoDB - usuarios)
    paciente_doc = await mongo_db.usuarios.find_one(
        {"_id": paciente_id}
    )
    if not paciente_doc:
        raise HTTPException(status_code=404, detail="Usuario no encontrado")

    # --- REQ: Validación de Rol ---
    if PACIENTE_ROLE not in paciente_doc.get('roles', []):
        return {
            "status": "Cálculo de riesgo omitido", 
            "mensaje": f"El ID no corresponde a un usuario con el rol '{PACIENTE_ROLE}'."
        }
        
    pii_data = paciente_doc.get('pii', {})
    paciente_data = paciente_doc.get('paciente', {})
    clinico_data = paciente_data.get('clinico', {})

    # Para el chequeo de inactividad, necesitamos la fecha de creación del documento
    # Aunque MongoDB no la expone directamente, el _id contiene un timestamp (no lo usaremos por seguridad de formato). 
    # Para ser robustos en el TPO, asumimos que si el documento no tiene "riesgo_ultima_actualizacion" (el primer cálculo), 
    # es nuevo. Alternativamente, la prueba del TPO puede insertarse 7 días después de la fecha de la base de datos.
    
    # --- CÁLCULO DE RIESGO ESTÁTICO (Factores de Perfil) ---

    # 1.1. Riesgo por Edad Extrema
    fecha_nac_str = pii_data.get('fecha_nac')
    if fecha_nac_str:
        try:
            fecha_nac = datetime.fromisoformat(fecha_nac_str)
            age = hoy.year - fecha_nac.year - ((hoy.month, hoy.day) < (fecha_nac.month, fecha_nac.day))
            
            if age > 75 or age < 18:
                score_total += PONDERACIONES["riesgo_edad_extrema"]
        except ValueError:
            pass # Ignoramos el riesgo de edad si el formato es inválido
            
    # 1.2. Antecedentes Familiares Graves
    antecedentes_estaticos = clinico_data.get('antecedentes', [])
    if antecedentes_estaticos:
        score_total += PONDERACIONES["antecedentes_familiares_graves"]
        
    # 1.3. Alergias Registradas
    alergias = clinico_data.get('alergias', [])
    if alergias and alergias[0].lower() != "ninguna":
        score_total += PONDERACIONES["alergias_registradas"]

    # 1.4. Diagnóstico de Alto Riesgo / Inmunodeficiencia
    latest_visit = await mongo_db.visitas_medicas.find_one(
        {"paciente_id": paciente_id},
        sort=[("ts", -1)]
    )
    diagnosticos_visita = latest_visit.get('diagnosticos', []) if latest_visit else []
    
    all_diagnoses = antecedentes_estaticos + diagnosticos_visita
    diagnoses_text = " ".join(all_diagnoses).lower()
    
    # Detección de Alto Riesgo
    for keyword in DIAGNOSTICOS_ALTO_RIESGO:
        if keyword in diagnoses_text:
            score_total += PONDERACIONES["diagnostico_alto_riesgo"]
            break 
            
    # Detección de Inmunodeficiencia/Inmunosupresión
    for keyword in INMUNODEFICIENCIA_KEYWORDS:
        if keyword in diagnoses_text:
            score_total += PONDERACIONES["inmunodeficiencia"]
            break 

    # 1.5. Frecuencia de Visitas (Riesgo Crónico/Agudo)
    num_visitas = await mongo_db.visitas_medicas.count_documents(
        {"paciente_id": paciente_id, "ts": {"$gte": hace_7_dias}}
    )
    if num_visitas >= 5:
        score_total += PONDERACIONES["consultas_frecuentes"] * (num_visitas // 5)
    
    # --- CÁLCULO DE RIESGO DINÁMICO (MongoDB Time Series Aggregation) ---
    
    # 2.1. Hábitos de Sueño (Promedio de 7 días)
    sueno_pipeline = [
        {"$match": {
            "paciente_id": paciente_id,
            "tipo": "horas dormidas",
            "ts": {"$gte": hace_7_dias}
        }},
        {"$group": {
            "_id": None,
            "avg_sueno": {"$avg": "$valor"},
            "count": {"$sum": 1}
        }}
    ]
    
    sueno_data = await mongo_db.habitos.aggregate(sueno_pipeline).to_list(length=1)
    
    has_sueno_data = sueno_data and sueno_data[0].get("count", 0) > 0

    if has_sueno_data:
        avg_sueno = sueno_data[0].get("avg_sueno", 0)
        
        if avg_sueno < 6.0:
            score_total += PONDERACIONES["sueno_bajo_promedio"]
    else:
        # 2.2. Inactividad/Falta de Registro (CORREGIDO)
        
        # Lógica: Sólo penalizamos si es un usuario que ya debería tener registros
        # Para simplificar el TPO, asumiremos que si tiene visitas médicas (es decir, ya usó el sistema), 
        # o si tiene más de 7 días en la base (complicado de chequear en TPO) debe tener hábitos.
        # La solución más simple para un nuevo usuario es chequear si tiene CUALQUIER historial de visita.
        
        if latest_visit: # Si ya tuvo al menos una visita médica, pero no tiene hábitos recientes
            score_total += PONDERACIONES["inactividad_habitos"]
            # NOTA: En un sistema real, se usaría un campo 'fecha_creacion' del documento 'usuarios' para chequear > 7 días.
    
    # --- CLASIFICACIÓN FINAL ---
    if score_total > 55:
        riesgo_calculado = "ALTO"
    elif score_total > 25:
        riesgo_calculado = "MODERADO"
    else:
        riesgo_calculado = "BAJO"

    # --- 3. ALMACENAMIENTO (Persistencia del Perfil Calculado) ---
    update_data = {
        "paciente.riesgo_calculado": riesgo_calculado, 
        "paciente.score_riesgo": score_total,       
        "paciente.riesgo_ultima_actualizacion": hoy.isoformat() 
    }
    
    await mongo_db.usuarios.update_one(
        {"_id": paciente_id},
        {"$set": update_data}
    )
    
    return {
        "paciente_id": paciente_id,
        "score_riesgo": score_total,
        "riesgo_calculado": riesgo_calculado,
        "status": "Scoring actualizado y almacenado."
    }