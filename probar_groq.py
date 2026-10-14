import os

from dotenv import load_dotenv
from groq import Groq

load_dotenv()
API_KEY = os.getenv("GROQ_API_KEY")  # definida en el archivo .env

client = Groq(api_key=API_KEY)

try:
    print("1. Consultando modelos disponibles para tu API Key...")
    modelos = client.models.list()
    lista_ids = [m.id for m in modelos.data]
    print("Modelos habilitados en tu cuenta:", lista_ids)
    
    if lista_ids:
        modelo_test = lista_ids[0]
        print(f"\n2. Probando consulta con el primer modelo disponible ({modelo_test})...")
        chat = client.chat.completions.create(
            model=modelo_test,
            messages=[{"role": "user", "content": "Hola, responde OK si me escuchas."}]
        )
        print("Respuesta de Groq:", chat.choices[0].message.content)
    else:
        print("Tu API Key no tiene modelos asignados.")

except Exception as e:
    print("\nERROR DE CONEXIÓN:")
    print(e)