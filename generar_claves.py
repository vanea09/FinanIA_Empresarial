
import base64
from pathlib import Path
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.hazmat.primitives import serialization

carpeta = Path(__file__).resolve().parent

# Genera un par nuevo de claves P-256.
private_key = ec.generate_private_key(ec.SECP256R1())
public_key = private_key.public_key()

# Guarda la clave privada en formato PEM.
private_pem = private_key.private_bytes(
    encoding=serialization.Encoding.PEM,
    format=serialization.PrivateFormat.PKCS8,
    encryption_algorithm=serialization.NoEncryption()
)

(carpeta / "vapid_private.pem").write_bytes(private_pem)

# Obtiene la clave pública en el formato que necesita el navegador.
public_bytes = public_key.public_bytes(
    encoding=serialization.Encoding.X962,
    format=serialization.PublicFormat.UncompressedPoint
)

public_key_b64 = base64.urlsafe_b64encode(
    public_bytes
).rstrip(b"=").decode("ascii")

print("Clave pública para el archivo .env:")
print("VAPID_PUBLIC_KEY=" + public_key_b64)
print("\nClave privada guardada en vapid_private.pem")
print("No compartas ni publiques ese archivo.")
