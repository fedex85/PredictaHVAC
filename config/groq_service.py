import logging
import os

from django.conf import settings
from django.utils import timezone
from groq import Groq

logger = logging.getLogger(__name__)

def consultar_groq(prompt_usuario, historial=None):
    """
    Consulta a Groq utilizando los modelos de lenguaje activos verificados en la cuenta,
    especializado en diagnóstico por marca, códigos de error y fallas HVAC.
    `historial`: turnos previos [{role, content}] ya validados.
    """
    # 1. Obtener la clave API desde settings o variables de entorno
    api_key = getattr(settings, 'GROQ_API_KEY', None) or os.getenv('GROQ_API_KEY')
    
    if not api_key or not str(api_key).startswith("gsk_"):
        return None, "Error: La clave GROQ_API_KEY no está configurada correctamente en el archivo .env (debe comenzar con 'gsk_')."

    # 2. Obtener fecha y hora local del servidor Django
    ahora_local = timezone.localtime(timezone.now())
    fecha_actual = ahora_local.strftime("%d/%m/%Y")
    hora_actual = ahora_local.strftime("%H:%M:%S")
    dias_semana = ["Lunes", "Martes", "Miércoles", "Jueves", "Viernes", "Sábado", "Domingo"]
    dia_semana = dias_semana[ahora_local.weekday()]

    # 3. Instrucción de sistema especializada en HVAC, marcas y códigos de error
    system_instruction = (
        f"Eres un asistente técnico especializado en sistemas HVAC, refrigeración y climatización.\n"
        f"Tienes conocimientos avanzados en mantenimiento, fallas comunes, ciclos de refrigeración, termodinámica y componentes de HVAC.\n"
        f"INFORMACIÓN DEL SISTEMA EN TIEMPO REAL: Hoy es {dia_semana}, {fecha_actual}. La hora actual es {hora_actual}.\n"
        f"Si el usuario te pregunta por la hora o fecha actual, utiliza ÚNICAMENTE este dato real suministrado.\n\n"
        f"REGLAS DE RESPUESTA DE DIAGNÓSTICO:\n"
        f"1. Si el usuario menciona un código de error y una marca (ej. Carrier, Daikin, LG, York, Trane, Midea, Mirage), "
        f"proporciona la interpretación específica del código para esa marca.\n"
        f"2. Si no especifica marca, entrega las causas más comunes para las principales marcas de HVAC e indícale que precise la marca para mayor precisión.\n"
        f"3. Para fallas generales (presión alta/baja, congelamiento, ruidos, sobreconsumo), da una guía estructurada.\n"
        f"4. Responde SIEMPRE en el siguiente formato claro y profesional:\n"
        f"   - 🔍 **Causa Probable:** Explicación breve del problema o del código de error.\n"
        f"   - 🛠️ **Verificaciones Técnicas:** Lista puntual de lecturas de presión, voltaje, amperaje o componentes a revisar.\n"
        f"   - ✅ **Solución Recomendada:** Pasos de corrección en orden de prioridad.\n"
        f"   - ⚠️ **Precaución de Seguridad:** Advertencia relevante si involucra alta tensión o manejo de refrigerante.\n"
        f"5. No te presentes ni abras con saludos o frases sobre quién eres: responde directamente a la consulta. "
        f"Solo si el usuario te saluda sin hacer una pregunta, responde exactamente: \"¡Hola! Soy tu asistente técnico de HVAC. ¿En qué te puedo ayudar?\"\n"
        f"\n"
        f"6. Si el usuario hace una pregunta de seguimiento, usa la conversación previa. Si la pregunta no es sobre HVAC, "
        f"mantenimiento, indica amablemente que solo puedes ayudar con esos temas."
    )
    try:
        client = Groq(api_key=api_key, timeout=30.0)

        # 4. Modelos de chat activos confirmados por el diagnóstico
        modelos_verificados = [
            "openai/gpt-oss-120b",
            "openai/gpt-oss-20b"
        ]

        ultimo_error = None
        for modelo in modelos_verificados:
            try:
                completion = client.chat.completions.create(
                    model=modelo,
                    messages=[{"role": "system", "content": system_instruction}, *(historial or []),
                              {"role": "user", "content": prompt_usuario}],
                    temperature=0.3
                )
                respuesta = completion.choices[0].message.content
                logger.info("Respuesta generada con el modelo %s", modelo)
                return respuesta, None
            except Exception as e:
                ultimo_error = str(e)
                logger.warning("Falló el modelo %s: %s", modelo, ultimo_error)
                continue

        return None, f"Error al conectar con Groq: {ultimo_error}"

    except Exception as e:
        return None, f"Error inesperado en el cliente Groq: {str(e)}"