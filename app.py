from flask import Flask, request, jsonify, render_template
from flask_sqlalchemy import SQLAlchemy
from datetime import datetime
import http.client
import json
from openai import OpenAI
import os
from dotenv import load_dotenv
from langchain_openai import OpenAI as LangChainOpenAI
from langchain.agents import create_sql_agent
from langchain.agents.agent_toolkits import SQLDatabaseToolkit
from langchain_community.utilities import SQLDatabase
from langchain.agents import AgentExecutor
from langchain_core.prompts import PromptTemplate

load_dotenv()
client = OpenAI(api_key=os.getenv('OPENAI_API_KEY'))

app = Flask(__name__)
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///metapython.db'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
db = SQLAlchemy(app)

class Log(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    fecha_y_hora = db.Column(db.DateTime, default=datetime.utcnow)
    texto = db.Column(db.TEXT)

with app.app_context():
    db.create_all()

def setup_sql_agent():
    try:
        db = SQLDatabase.from_uri("sqlite:///metapython.db")
        llm = LangChainOpenAI(temperature=0, api_key=os.getenv('OPENAI_API_KEY'))
        toolkit = SQLDatabaseToolkit(db=db, llm=llm)
        
        custom_prompt = """Eres un agente que interpreta lenguaje natural y genera consultas SQL.
        SOLO puedes realizar operaciones SELECT o INSERT en la tabla 'log'.
        Para consultas de tipo "mostrar", "ver", "buscar": Genera un SELECT.
        Para consultas de tipo "agregar", "añadir", "crear": Genera un INSERT.
        La tabla 'log' tiene las columnas: id, fecha_y_hora (tipo DateTime), texto (tipo TEXT).
        
        Human: {input}
        Assistant: Analizaré tu consulta y generaré el SQL apropiado."""
        
        agent = create_sql_agent(
            llm=llm,
            toolkit=toolkit,
            verbose=True,
            agent_type="zero-shot-react-description",
            prefix=custom_prompt
        )
        return agent
    except Exception as e:
        print(f"Error en setup_sql_agent: {str(e)}")
        return None

def natural_to_sql(text):
    print(f"Procesando texto: {text}")
    try:
        with app.app_context():
            if "mostrar" in text.lower() or "ver" in text.lower():
                try:
                    registros = Log.query.order_by(Log.fecha_y_hora.desc()).limit(5).all()
                    print(f"Registros encontrados: {len(registros)}")
                    mensajes = []
                    for r in registros:
                        msg = f"📝 {r.fecha_y_hora.strftime('%Y-%m-%d %H:%M')}: {r.texto}"
                        mensajes.append(msg)
                    return "📋 Últimos registros:\n\n" + "\n".join(mensajes) if mensajes else "No hay registros para mostrar"
                except Exception as e:
                    print(f"Error al consultar registros: {str(e)}")
                    return "Error al consultar registros"
            
            elif "agregar" in text.lower() or "añadir" in text.lower():
                try:
                    nuevo = Log(texto=text)
                    db.session.add(nuevo)
                    db.session.commit()
                    return "✅ Registro agregado correctamente"
                except Exception as e:
                    print(f"Error al agregar registro: {str(e)}")
                    return "Error al agregar registro"
            
            return "Comando no reconocido. Usa 'ver registros' o 'agregar mensaje'"
            
    except Exception as e:
        print(f"Error general en natural_to_sql: {str(e)}")
        return f"Error al procesar la consulta: {str(e)}"

def ordenar_por_fecha_y_hora(registros):
    return sorted(registros, key=lambda x: x.fecha_y_hora, reverse=True)

@app.route('/')
def index():
    registros = Log.query.all()
    registros_ordenados = ordenar_por_fecha_y_hora(registros)
    return render_template('index.html', registros=registros_ordenados)

mensajes_log = []

def get_chatgpt_response(texto):
    try:
        response = client.chat.completions.create(
            model="gpt-3.5-turbo",
            messages=[{"role": "user", "content": texto}],
            max_tokens=150
        )
        return response.choices[0].message.content
    except Exception as e:
        return f"Error: {str(e)}"

def agregar_mensajes_log(texto):
    mensajes_log.append(texto)
    nuevo_registro = Log(texto=texto)
    db.session.add(nuevo_registro)
    db.session.commit()
    
TOKEN_ANDERCODE = "ANDERCODE"

@app.route('/webhook', methods=['GET','POST'])
def webhook():
    if request.method == 'GET':
        return verificar_token(request)
    return recibir_mensajes(request)

def verificar_token(req):
    token = req.args.get('hub.verify_token')
    challenge = req.args.get('hub.challenge')
    if challenge and token == TOKEN_ANDERCODE:
        return challenge
    return jsonify({'error':'Token Invalido'}), 401

def recibir_mensajes(req):
    try:
        body = request.get_json()
        entry = body['entry'][0]
        changes = entry['changes'][0]
        value = changes['value']
        mensaje = value['messages'][0]
        
        if mensaje:
            if "type" in mensaje:
                tipo = mensaje["type"]
                agregar_mensajes_log(json.dumps(mensaje))

                if tipo == "interactive":
                    tipo_interactivo = mensaje["interactive"]["type"]
                    if tipo_interactivo == "button_reply":
                        text = mensaje["interactive"]["button_reply"]["id"]
                        numero = mensaje["from"]
                        enviar_mensajes_whatsapp(text, numero)
                    elif tipo_interactivo == "list_reply":
                        text = mensaje["interactive"]["list_reply"]["id"]
                        numero = mensaje["from"]
                        enviar_mensajes_whatsapp(text, numero)

                if "text" in mensaje:
                    text = mensaje["text"]["body"]
                    numero = mensaje["from"]
                    enviar_mensajes_whatsapp(text, numero)

        return jsonify({'status': 'ok'})
    except Exception as e:
        print(f"Error en recibir_mensajes: {str(e)}")
        return jsonify({'status': 'error', 'error': str(e)})

def enviar_mensajes_whatsapp(texto, number):
    texto = texto.lower()
    palabras_consulta = ['mostrar', 'ver', 'buscar', 'muestra', 'dime', 'agregar', 'añadir', 'crear']
    
    if any(palabra in texto for palabra in palabras_consulta):
        response = natural_to_sql(texto)
        data = {
            "messaging_product": "whatsapp",
            "recipient_type": "individual",
            "to": number,
            "type": "text",
            "text": {
                "preview_url": False,
                "body": response
            }
        }
    elif "hola" in texto:
        data = {
            "messaging_product": "whatsapp",
            "recipient_type": "individual",
            "to": number,
            "type": "text",
            "text": {
                "preview_url": False,
                "body": "🚀 ¡Hola! ¿Cómo estás? Bienvenido.\n\nPuedes usar comandos como:\n- Ver mensajes\n- Agregar mensaje\n- Mostrar registros"
            }
        }
    elif "1" in texto:
        data = {
            "messaging_product": "whatsapp",
            "recipient_type": "individual",
            "to": number,
            "type": "text",
            "text": {
                "preview_url": False,
                "body": "Lorem Ipsum is simply dummy text of the printing and typesetting industry. Lorem Ipsum has been the industry's standard dummy text ever since the 1500s, when an unknown printer took a galley of type and scrambled it to make a type specimen book."
            }
        }
    elif "2" in texto:
        data = {
            "messaging_product": "whatsapp",
            "to": number,
            "type": "location",
            "location": {
                "latitude": "-12.067158831865067",
                "longitude": "-77.03377940839486",
                "name": "Estadio Nacional del Perú",
                "address": "Cercado de Lima"
            }
        }
    elif "3" in texto:
        data = {
            "messaging_product": "whatsapp",
            "recipient_type": "individual",
            "to": number,
            "type": "document",
            "document": {
                "link": "https://www.turnerlibros.com/wp-content/uploads/2021/02/ejemplo.pdf",
                "caption": "Temario del Curso #001"
            }
        }
    elif "4" in texto:
        data = {
            "messaging_product": "whatsapp",
            "recipient_type": "individual",
            "to": number,
            "type": "audio",
            "audio": {
                "link": "https://filesamples.com/samples/audio/mp3/sample1.mp3"
            }
        }
    elif "5" in texto:
        data = {
            "messaging_product": "whatsapp",
            "to": number,
            "text": {
                "preview_url": True,
                "body": "Introduccion al curso! https://youtu.be/6ULOE2tGlBM"
            }
        }
    elif "6" in texto:
        data = {
            "messaging_product": "whatsapp",
            "recipient_type": "individual",
            "to": number,
            "type": "text",
            "text": {
                "preview_url": False,
                "body": "🤝 En breve me pondre en contacto contigo. 🤓"
            }
        }
    elif "7" in texto:
        data = {
            "messaging_product": "whatsapp",
            "recipient_type": "individual",
            "to": number,
            "type": "text",
            "text": {
                "preview_url": False,
                "body": "📅 Horario de Atención : Lunes a Viernes. \n🕜 Horario : 9:00 am a 5:00 pm 🤓"
            }
        }
    elif "0" in texto:
        data = {
            "messaging_product": "whatsapp",
            "recipient_type": "individual",
            "to": number,
            "type": "text",
            "text": {
                "preview_url": False,
                "body": "🚀 Hola, visita mi web anderson-bastidas.com para más información.\n \n📌Por favor, ingresa un número #️⃣ para recibir información.\n \n1️⃣. Información del Curso. ❔\n2️⃣. Ubicación del local. 📍\n3️⃣. Enviar temario en PDF. 📄\n4️⃣. Audio explicando curso. 🎧\n5️⃣. Video de Introducción. ⏯️\n6️⃣. Hablar con AnderCode. 🙋‍♂️\n7️⃣. Horario de Atención. 🕜 \n0️⃣. Regresar al Menú. 🕜"
            }
        }
    elif "boton" in texto:
        data = {
            "messaging_product": "whatsapp",
            "recipient_type": "individual",
            "to": number,
            "type": "interactive",
            "interactive": {
                "type": "button",
                "body": {
                    "text": "¿Confirmas tu registro?"
                },
                "footer": {
                    "text": "Selecciona una de las opciones"
                },
                "action": {
                    "buttons": [
                        {
                            "type": "reply",
                            "reply": {
                                "id": "btnsi",
                                "title": "Si"
                            }
                        },
                        {
                            "type": "reply",
                            "reply": {
                                "id": "btnno",
                                "title": "No"
                            }
                        },
                        {
                            "type": "reply",
                            "reply": {
                                "id": "btntalvez",
                                "title": "Tal Vez"
                            }
                        }
                    ]
                }
            }
        }
    elif "btnsi" in texto:
        data = {
            "messaging_product": "whatsapp",
            "recipient_type": "individual",
            "to": number,
            "type": "text",
            "text": {
                "preview_url": False,
                "body": "Muchas Gracias por Aceptar."
            }
        }
    elif "btnno" in texto:
        data = {
            "messaging_product": "whatsapp",
            "recipient_type": "individual",
            "to": number,
            "type": "text",
            "text": {
                "preview_url": False,
                "body": "Es una Lastima."
            }
        }
    elif "btntalvez" in texto:
        data = {
            "messaging_product": "whatsapp",
            "recipient_type": "individual",
            "to": number,
            "type": "text",
            "text": {
                "preview_url": False,
                "body": "Estare a la espera."
            }
        }
    elif "lista" in texto:
        data = {
            "messaging_product": "whatsapp",
            "to": number,
            "type": "interactive",
            "interactive": {
                "type": "list",
                "body": {
                    "text": "Selecciona Alguna Opción"
                },
                "footer": {
                    "text": "Selecciona una de las opciones para poder ayudarte"
                },
                "action": {
                    "button": "Ver Opciones",
                    "sections": [
                        {
                            "title": "Compra y Venta",
                            "rows": [
                                {
                                    "id": "btncompra",
                                    "title": "Comprar",
                                    "description": "Compra los mejores articulos de tecnologia"
                                },
                                {
                                    "id": "btnvender",
                                    "title": "Vender",
                                    "description": "Vende lo que ya no estes usando"
                                }
                            ]
                        },
                        {
                            "title": "Distribución y Entrega",
                            "rows": [
                                {
                                    "id": "btndireccion",
                                    "title": "Local",
                                    "description": "Puedes visitar nuestro local."
                                },
                                {
                                    "id": "btnentrega",
                                    "title": "Entrega",
                                    "description": "La entrega se realiza todos los dias."
                                }
                            ]
                        }
                    ]
                }
            }
        }
    elif "btncompra" in texto:
        data = {
            "messaging_product": "whatsapp",
            "recipient_type": "individual",
            "to": number,
            "type": "text",
            "text": {
                "preview_url": False,
                "body": "Los mejos articulos top en ofertas."
            }
        }
    elif "btnvender" in texto:
        data = {
            "messaging_product": "whatsapp",
            "recipient_type": "individual",
            "to": number,
            "type": "text",
            "text": {
                "preview_url": False,
                "body": "Excelente elección."
            }
        }
    else:
        respuesta = get_chatgpt_response(texto)
        data = {
            "messaging_product": "whatsapp",
            "recipient_type": "individual",
            "to": number,
            "type": "text",
            "text": {
                "preview_url": False,
                "body": respuesta
            }
        }

    data = json.dumps(data)
    headers = {
        "Content-Type": "application/json",
        "Authorization": "Bearer EAAI8epaNZBKABO7mmsDmFCAVkeWiBIf6QyiJEEI0pJ3AmY5GPXtFwcwiNoC1bzmE8UJJrO6ysZBT2OoM378RS91hFmVqQWCiY1YqMc1ikGSJNPztxDzoYoANiAeABBl2raKLGZBEpsr4BEtNRQpdC7pMMQkWfwXzsYuyOFO6ou2y3MMkihnXfZAWZAnZCdM4jpTGTnzdQ1PtF7mxtxZAEDWHxJZBkdqJB948wBcZD"
    }
    
    connection = http.client.HTTPSConnection("graph.facebook.com")
    try:
        connection.request("POST", "/v21.0/484107578125461/messages", data, headers)
        response = connection.getresponse()
        print(response.status, response.reason)
    except Exception as e:
        agregar_mensajes_log(json.dumps(str(e)))
    finally:
        connection.close()

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=80, debug=True)        