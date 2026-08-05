from flask import Flask, render_template, request, jsonify
import requests
import os
from dotenv import load_dotenv
#asesoria financiero basico IA
load_dotenv()

app = Flask(__name__)

OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY")
    
@app.route("/")
def index():
    return render_template("index.html")


@app.route("/chat", methods=["POST"])
def chat():
    data = request.get_json()
    user_message = data.get("message", "")

    if not user_message:
        return jsonify({"reply": "Escribe una pregunta primero."})

    try:
        response = requests.post(
            "https://openrouter.ai/api/v1/chat/completions",
            headers={
                "Authorization": f"Bearer {OPENROUTER_API_KEY}",
                "Content-Type": "application/json",
                "HTTP-Referer": "http://localhost:5000",
                "X-OpenRouter-Title": "Mi Chatbot Flask"
            },
            json={
                "model": "openrouter/free",
                "messages": [
                    {
                    "role": "system",
                    "content": """
                    Eres un asesor virtual especializado en agencias de autos.
                    
                    Reglas:
                    - Responde únicamente preguntas relacionadas con agencias de autos y el sector automotriz.
                    - Puedes hablar sobre compra de vehículos (nuevos/seminuevos), financiamiento, crédito, seguros, garantías, mantenimiento, servicios de agencia, marcas y modelos.
                    - Sé servicial, dinámico y profesional. Evita respuestas robóticas; si te piden un estimado o costo, proporciona un rango numérico aproximado basado en tu conocimiento.
                    - Mantén tus respuestas breves y al grano, idealmente entre 60 y 100 palabras, para dar información útil sin aburrir al usuario.
                    - Si la pregunta no está relacionada con el tema, responde exactamente: 'Lo siento, solo puedo ayudar con temas relacionados con agencias de autos y vehículos.'
                    """
                    },
                    {
                        "role": "user",
                        "content": user_message
                    }
                ]
            }
        )

        result = response.json()
        print(result)

        if "choices" in result:
            reply = result["choices"][0]["message"]["content"]
        else:
            reply = result.get("error", {}).get("message", "Error desconocido de OpenRouter")

        return jsonify({"reply": reply})

    except Exception as e:
        return jsonify({"reply": f"Error: {str(e)}"})


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=True)
