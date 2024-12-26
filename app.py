from flask import Flask, request, jsonify, render_template
from flask_sqlalchemy import SQLAlchemy
from datetime import datetime
import http.client
import json
from openai import OpenAI
import os
from dotenv import load_dotenv

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

def ordenar_por_fecha_y_hora(registros):
    return sorted(registros, key=lambda x: x.fecha_y_hora, reverse=True)

@app.route('/')
def index():
    registros = Log.query.all()
    registros_ordenados = ordenar_por_fecha_y_hora(registros)
    return render_template('index.html', registros=registros_ordenados)

mensajes_log = []

def natural_to_sql(text):
    print(f"Procesando texto: {text}")
    try:
        with app.app_context():
            if "mostrar" in text or "ver" in text:
                registros = Log.query.order_by(Log.fecha_y_hora.desc()).limit(5).all()
                mensajes = [f"- {r.fecha_y_hora.strftime('%Y-%m-%d %H:%M')}: {r.texto}" for r in registros]
                return "Últimos registros:\n" + "\n".join(mensajes)
            elif "agregar" in text or "añadir" in text:
                nuevo = Log(texto=text)
                db.session.add(nuevo)
                db.session.commit()
                return "✅ Registro agregado correctamente"
    except Exception as e:
        print(f"Error en natural_to_sql: {str(e)}")
        return f"❌ Error al procesar la consulta: {str(e)}"

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

@app.route('/webhook', methods=['GET', 'POST'])
def webhook():
    if request.method == 'GET':
        return verificar_token(request)
    return recibir_mensajes(request)

def verificar_token(req):
    token = req.args.get('hub.verify_token')
    challenge = req.args.get('hub.challenge')
    if challenge and token == TOKEN_ANDERCODE:
        return challenge
    return jsonify({'error': 'Token Invalido'}), 401

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
    
    try:
        if any(palabra in texto for palabra in palabras_consulta):
            response = natural_to_sql(texto)
            data = {
                "messaging_product": "whatsapp",
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
                "to": number,
                "type": "text",
                "text": {
                    "preview_url": False,
                    "body": "🚀 ¡Hola! ¿Cómo estás? Bienvenido.\n\nPuedes usar comandos como:\n- Ver mensajes\n- Agregar mensaje\n- Mostrar registros"
                }
            }
        else:
            respuesta = get_chatgpt_response(texto)
            data = {
                "messaging_product": "whatsapp",
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
            "Authorization": "Bearer EAAI8epaNZBKABO2y05KV992fooZCdvZBMwaF0qvCFSQ5IhGEKyoSAXavSIefZBRcVaDQ8YWBAShiWqZBTZCJOjjqe02B8JZASfJNBPFrUzZAD7FSkjOfxWS9Ii2tsDBmp66vF4ZCgc7ip6xvzEiFe38bYcZCmdeUZARfCJ0JRFewaQAW2ZAnidhJbijX48BXOji155xwiLB1YeF5Fcdz8Tvym5jZCfYr8FDimW8foni4ZD"
        }
        
        connection = http.client.HTTPSConnection("graph.facebook.com")
        connection.request("POST", "/v21.0/484107578125461/messages", data, headers)
        response = connection.getresponse()
        print(f"Status: {response.status}, Reason: {response.reason}")
        
    except Exception as e:
        print(f"Error en enviar_mensajes_whatsapp: {str(e)}")
    finally:
        if 'connection' in locals():
            connection.close()

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=80, debug=True)   