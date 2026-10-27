"""
Muestra las claves VAPID en el formato que se debe pegar en las
variables de entorno de Render (o cualquier hosting).

En Render no existe el archivo vapid_private.pem (está en .gitignore),
por eso la clave privada se configura como texto (base64url, 32 bytes),
formato que pywebpush acepta directamente.

Uso:  py exportar_clave_render.py
NO compartas ni subas a GitHub la clave privada.
"""
import base64
import os
from pathlib import Path

from cryptography.hazmat.primitives import serialization
from dotenv import load_dotenv

load_dotenv()

public_key = os.getenv("VAPID_PUBLIC_KEY", "").strip()
private_path = Path(
    os.getenv("VAPID_PRIVATE_KEY", "vapid_private.pem")
).resolve()

if not private_path.is_file():
    print("ERROR: no se encuentra el archivo de clave privada:", private_path)
    raise SystemExit(1)

private_key = serialization.load_pem_private_key(
    private_path.read_bytes(),
    password=None
)

raw_private = private_key.private_numbers().private_value.to_bytes(32, "big")
private_b64 = base64.urlsafe_b64encode(raw_private).rstrip(b"=").decode("ascii")

print("Copia estas variables en Render > tu servicio > Environment:\n")
print("VAPID_PUBLIC_KEY=" + public_key)
print("VAPID_PRIVATE_KEY=" + private_b64)
print("VAPID_EMAIL=" + os.getenv("VAPID_EMAIL", "mailto:admin@example.com"))
print("OPENROUTER_API_KEY=(la misma de tu archivo .env)")
