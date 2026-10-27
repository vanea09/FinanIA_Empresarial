
import os
from pathlib import Path
from dotenv import load_dotenv
from cryptography.hazmat.primitives import serialization
import base64

load_dotenv()

public_env = os.getenv("VAPID_PUBLIC_KEY", "").strip()
private_path = Path(
    os.getenv("VAPID_PRIVATE_KEY", "vapid_private.pem")
).resolve()

if not public_env:
    print("ERROR: falta VAPID_PUBLIC_KEY en .env")
    raise SystemExit(1)

if not private_path.is_file():
    print("ERROR: no se encuentra el archivo de clave privada.")
    print("Ruta esperada:", private_path)
    raise SystemExit(1)

try:
    private_key = serialization.load_pem_private_key(
        private_path.read_bytes(),
        password=None
    )

    public_bytes = private_key.public_key().public_bytes(
        encoding=serialization.Encoding.X962,
        format=serialization.PublicFormat.UncompressedPoint
    )

    expected_public = base64.urlsafe_b64encode(
        public_bytes
    ).rstrip(b"=").decode("ascii")

    if expected_public == public_env:
        print("CORRECTO: las claves coinciden.")
    else:
        print("ERROR: las claves pública y privada no coinciden.")

except Exception as error:
    print("ERROR al leer la clave:", type(error).__name__)
