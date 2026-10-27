
from flask import Flask, render_template, request, jsonify, send_from_directory
from pywebpush import webpush, WebPushException
from py_vapid import Vapid
from cryptography.hazmat.primitives import serialization
from pathlib import Path
from dotenv import load_dotenv
import requests
import base64
import hmac
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
VAPID_PUBLIC_KEY = os.getenv("VAPID_PUBLIC_KEY", "").strip()
VAPID_PRIVATE_KEY = os.getenv("VAPID_PRIVATE_KEY", "").strip()
VAPID_EMAIL = os.getenv("VAPID_EMAIL", "mailto:admin@example.com").strip()
# Token opcional para enviar una notificación a todos los suscriptores
PUSH_ADMIN_TOKEN = os.getenv("PUSH_ADMIN_TOKEN", "").strip()

if VAPID_EMAIL and not VAPID_EMAIL.startswith(("mailto:", "https://")):
    VAPID_EMAIL = "mailto:" + VAPID_EMAIL

SUBSCRIPTIONS_FILE = BASE_DIR / "subscriptions.json"


def load_vapid():
    """
    Carga la clave privada VAPID desde cualquiera de estos formatos:
    - Ruta a un archivo .pem (desarrollo local).
    - Contenido PEM completo pegado en la variable (con saltos o con \\n).
    - Texto base64url (raw de 32 bytes o DER), ideal para Render.
    Si VAPID_PUBLIC_KEY no está configurada, se calcula desde la privada.
    """
    if not VAPID_PRIVATE_KEY:
        return None, VAPID_PUBLIC_KEY

    try:
        key_path = (BASE_DIR / VAPID_PRIVATE_KEY)

        if len(VAPID_PRIVATE_KEY) < 260 and key_path.is_file():
            vapid = Vapid.from_file(str(key_path))
        elif "-----BEGIN" in VAPID_PRIVATE_KEY:
            pem = VAPID_PRIVATE_KEY.replace("\\n", "\n").encode()
            vapid = Vapid.from_pem(pem)
        else:
            vapid = Vapid.from_string(VAPID_PRIVATE_KEY)

        public_bytes = vapid.public_key.public_bytes(
            encoding=serialization.Encoding.X962,
            format=serialization.PublicFormat.UncompressedPoint
        )
        derived_public = base64.urlsafe_b64encode(
            public_bytes
        ).rstrip(b"=").decode("ascii")

        if VAPID_PUBLIC_KEY and VAPID_PUBLIC_KEY != derived_public:
            app.logger.warning(
                "VAPID_PUBLIC_KEY no corresponde a la clave privada; "
                "se usará la clave pública calculada."
            )

        return vapid, derived_public

    except Exception:
        app.logger.exception("VAPID_PRIVATE_KEY no es válida")
        return None, VAPID_PUBLIC_KEY


VAPID, VAPID_PUBLIC_KEY = load_vapid()

if not VAPID:
    app.logger.warning(
        "Notificaciones push desactivadas: configura VAPID_PRIVATE_KEY."
    )


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
    if not VAPID or not VAPID_PUBLIC_KEY:
        return jsonify({
            "error": (
                "Las notificaciones push no están configuradas en el "
                "servidor (falta VAPID_PRIVATE_KEY)."
            )
        }), 503

    return jsonify({"publicKey": VAPID_PUBLIC_KEY})


def is_valid_subscription(subscription):
    if not isinstance(subscription, dict):
        return False

    keys = subscription.get("keys")

    return bool(
        isinstance(subscription.get("endpoint"), str)
        and subscription["endpoint"].startswith("https://")
        and isinstance(keys, dict)
        and keys.get("p256dh")
        and keys.get("auth")
    )


def send_push(subscription, payload):
    """
    Envía una notificación. Devuelve (ok, status_code).
    status_code 404/410 indica una suscripción caducada.
    """
    try:
        webpush(
            subscription_info=subscription,
            data=json.dumps(payload),
            vapid_private_key=VAPID,
            vapid_claims={"sub": VAPID_EMAIL},
            ttl=60,
            timeout=15
        )
        return True, 201

    except WebPushException as error:
        status_code = getattr(
            getattr(error, "response", None),
            "status_code",
            None
        )
        app.logger.warning("Error al enviar push (%s): %s", status_code, error)
        return False, status_code

    except Exception:
        app.logger.exception("Error inesperado enviando push")
        return False, None


# Registrar una suscripción del navegador
@app.route("/api/push/subscribe", methods=["POST"])
def subscribe():
    subscription = request.get_json(silent=True)

    if not is_valid_subscription(subscription):
        return jsonify({
            "error": "Suscripción inválida o incompleta."
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


# Enviar una notificación push de prueba SOLO al usuario que la solicita
@app.route("/api/push/test", methods=["POST"])
def test_push():
    if not VAPID:
        return jsonify({
            "error": "Las notificaciones push no están configuradas en el servidor."
        }), 503

    subscription = request.get_json(silent=True)

    if not is_valid_subscription(subscription):
        return jsonify({
            "error": "Envía la suscripción de este navegador para la prueba."
        }), 400

    ok, status_code = send_push(subscription, {
        "title": "FinanIA Autos",
        "body": "¡Tu asesoría financiera está lista!",
        "url": "/"
    })

    if ok:
        return jsonify({
            "message": "Notificación push enviada a este dispositivo."
        })

    if status_code in (404, 410):
        return jsonify({
            "error": "La suscripción caducó. Vuelve a activar las notificaciones.",
            "expired": True
        }), 410

    return jsonify({
        "error": (
            "No se pudo enviar la notificación. "
            "Revisa las claves VAPID y los registros del servidor."
        )
    }), 502


# Enviar una notificación a TODOS los suscriptores (solo administrador)
# Uso: POST /api/push/broadcast  con cabecera  Authorization: Bearer <PUSH_ADMIN_TOKEN>
#      cuerpo JSON opcional: {"title": "...", "body": "...", "url": "/"}
@app.route("/api/push/broadcast", methods=["POST"])
def broadcast_push():
    if not PUSH_ADMIN_TOKEN:
        return jsonify({"error": "Envío masivo desactivado."}), 404

    auth = request.headers.get("Authorization", "")
    token = auth.removeprefix("Bearer ").strip()

    if not hmac.compare_digest(token, PUSH_ADMIN_TOKEN):
        return jsonify({"error": "No autorizado."}), 401

    if not VAPID:
        return jsonify({"error": "Configura las claves VAPID."}), 503

    data = request.get_json(silent=True) or {}
    payload = {
        "title": str(data.get("title") or "FinanIA Autos")[:80],
        "body": str(data.get("body") or "Consulta las novedades de tu asesoría.")[:200],
        "url": "/"
    }

    subscriptions = load_subscriptions()
    sent = 0
    remaining = []

    for subscription in subscriptions:
        ok, status_code = send_push(subscription, payload)

        if ok:
            sent += 1

        # Eliminar suscripciones caducadas o inválidas
        if status_code not in (404, 410):
            remaining.append(subscription)

    try:
        save_subscriptions(remaining)
    except OSError:
        app.logger.exception(
            "No se pudieron guardar las suscripciones actualizadas"
        )

    return jsonify({
        "message": f"Notificación enviada a {sent} de {len(subscriptions)} suscripción(es)."
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
