
from flask import Flask, render_template, request, jsonify, send_from_directory
from pywebpush import webpush, WebPushException
from pathlib import Path
from dotenv import load_dotenv
import requests
import os
import json

load_dotenv()

# Configuración de las carpetas del proyecto
BASE_DIR = Path(__file__).resolve().parent

app = Flask(
    __name__,
    template_folder="templates",
    static_folder="static"
)

# Variables de entorno
OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY")
VAPID_PUBLIC_KEY = os.getenv("VAPID_PUBLIC_KEY")
VAPID_PRIVATE_KEY = os.getenv("VAPID_PRIVATE_KEY")
VAPID_EMAIL = os.getenv("VAPID_EMAIL", "mailto:admin@example.com")

SUBSCRIPTIONS_FILE = BASE_DIR / "subscriptions.json"


def load_subscriptions():
    if not SUBSCRIPTIONS_FILE.exists():
        return []

    try:
        data = json.loads(
            SUBSCRIPTIONS_FILE.read_text(encoding="utf-8")
        )
        return data if isinstance(data, list) else []
    except (json.JSONDecodeError, OSError):
        app.logger.exception("Error leyendo las suscripciones")
        return []


def save_subscriptions(subscriptions):
    SUBSCRIPTIONS_FILE.write_text(
        json.dumps(subscriptions, ensure_ascii=False, indent=2),
        encoding="utf-8"
    )


# Página principal
@app.route("/")
def index():
    return render_template("index.html")


# Service Worker disponible desde la raíz del dominio
@app.route("/sw.js")
def service_worker():
    response = app.make_response(
        send_from_directory(
            app.static_folder,
            "sw.js",
            mimetype="application/javascript"
        )
    )
    response.headers["Service-Worker-Allowed"] = "/"
    response.headers["Cache-Control"] = "no-cache"
    return response


# Clave pública para las notificaciones push
@app.route("/api/vapid-public-key", methods=["GET"])
def vapid_public_key():
    if not VAPID_PUBLIC_KEY:
        return jsonify({
            "error": "Falta configurar VAPID_PUBLIC_KEY."
        }), 503

    return jsonify({"publicKey": VAPID_PUBLIC_KEY})


# Registrar una suscripción del navegador
@app.route("/api/push/subscribe", methods=["POST"])
def subscribe():
    subscription = request.get_json(silent=True)

    if not isinstance(subscription, dict):
        return jsonify({"error": "Suscripción inválida."}), 400

    keys = subscription.get("keys")

    if (
        not subscription.get("endpoint")
        or not isinstance(keys, dict)
        or not keys.get("p256dh")
        or not keys.get("auth")
    ):
        return jsonify({
            "error": "Faltan datos de la suscripción."
        }), 400

    subscriptions = load_subscriptions()

    # Evitar suscripciones duplicadas
    subscriptions = [
        item for item in subscriptions
        if item.get("endpoint") != subscription["endpoint"]
    ]

    subscriptions.append(subscription)

    try:
        save_subscriptions(subscriptions)
    except OSError:
        app.logger.exception("Error guardando la suscripción")
        return jsonify({
            "error": "No se pudo guardar la suscripción."
        }), 500

    return jsonify({
        "message": "Suscripción guardada correctamente."
    }), 201


# Enviar una notificación push de prueba
@app.route("/api/push/test", methods=["POST"])
def test_push():
    if not VAPID_PUBLIC_KEY or not VAPID_PRIVATE_KEY:
        return jsonify({
            "error": "Configura las claves VAPID."
        }), 503

    subscriptions = load_subscriptions()

    if not subscriptions:
        return jsonify({
            "error": "No hay suscripciones. Activa primero las notificaciones."
        }), 400

    payload = json.dumps({
        "title": "FinanIA Autos",
        "body": "¡Tu asesoría financiera está lista!",
        "url": "/"
    })

    sent = 0
    remaining = []

    for subscription in subscriptions:
        try:
            webpush(
                subscription_info=subscription,
                data=payload,
                vapid_private_key=VAPID_PRIVATE_KEY,
                vapid_claims={"sub": VAPID_EMAIL},
                ttl=60
            )

            sent += 1
            remaining.append(subscription)

        except WebPushException as error:
            status_code = getattr(
                getattr(error, "response", None),
                "status_code",
                None
            )

            # Eliminar suscripciones caducadas o inválidas
            if status_code not in (404, 410):
                remaining.append(subscription)
                app.logger.warning(
                    "Error al enviar push: %s", error
                )

        except Exception:
            remaining.append(subscription)
            app.logger.exception(
                "Error inesperado enviando push"
            )

    try:
        save_subscriptions(remaining)
    except OSError:
        app.logger.exception(
            "No se pudieron guardar las suscripciones actualizadas"
        )

    if sent == 0:
        return jsonify({
            "error": (
                "No se pudo enviar la notificación. "
                "Revisa las claves VAPID y los registros del servidor."
            )
        }), 502

    return jsonify({
        "message": (
            f"Notificación push enviada a {sent} suscripción(es)."
        )
    })


# Asistente financiero con OpenRouter
@app.route("/chat", methods=["POST"])
def chat():
    data = request.get_json(silent=True) or {}
    user_message = data.get("message", "")

    if not isinstance(user_message, str) or not user_message.strip():
        return jsonify({
            "reply": "Escribe una pregunta primero."
        }), 400

    if not OPENROUTER_API_KEY:
        return jsonify({
            "reply": "Falta configurar la API de OpenRouter."
        }), 503

    try:
        response = requests.post(
            "https://openrouter.ai/api/v1/chat/completions",
            headers={
                "Authorization": f"Bearer {OPENROUTER_API_KEY}",
                "Content-Type": "application/json",
                "HTTP-Referer": "https://finania-empresarial-v251.onrender.com",
                "X-OpenRouter-Title": "FinanIA Empresarial"
            },
            json={
                "model": "openrouter/free",
                "messages": [
                    {
                        "role": "system",
                        "content": """
Eres un asesor virtual especializado en agencias de autos.

Reglas:
- Responde únicamente preguntas relacionadas con agencias de autos
  y el sector automotriz.
- Puedes hablar sobre compra de vehículos, financiamiento, crédito,
  seguros, garantías, mantenimiento, servicios, marcas y modelos.
- Sé servicial, dinámico y profesional.
- Si te piden un estimado o costo, proporciona un rango aproximado.
- Mantén tus respuestas entre 60 y 100 palabras cuando sea posible.
- Si la pregunta no está relacionada con el tema, responde exactamente:
  'Lo siento, solo puedo ayudar con temas relacionados con agencias
  de autos y vehículos.'
"""
                    },
                    {
                        "role": "user",
                        "content": user_message.strip()
                    }
                ]
            },
            timeout=60
        )

        response.raise_for_status()
        result = response.json()

        if result.get("choices"):
            reply = result["choices"][0]["message"]["content"]
        else:
            reply = result.get("error", {}).get(
                "message",
                "Error desconocido de OpenRouter."
            )

        return jsonify({"reply": reply})

    except requests.RequestException:
        app.logger.exception("Error consultando OpenRouter")
        return jsonify({
            "reply": (
                "No se pudo conectar con el servicio "
                "de inteligencia artificial."
            )
        }), 502


if __name__ == "__main__":
    app.run(
        host="0.0.0.0",
        port=int(os.getenv("PORT", 5000)),
        debug=False
    )
