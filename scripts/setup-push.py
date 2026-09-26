"""Create local push configuration without printing or committing secrets."""
import base64
import secrets
from pathlib import Path

from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.hazmat.primitives import serialization
from dotenv import dotenv_values, set_key


def setup():
    env = Path(__file__).resolve().parents[1] / "backend" / ".env"
    values = dotenv_values(env)
    if not values.get("VAPID_PUBLIC_KEY") or not values.get("VAPID_PRIVATE_KEY"):
        key = ec.generate_private_key(ec.SECP256R1())
        public = key.public_key().public_bytes(serialization.Encoding.X962, serialization.PublicFormat.UncompressedPoint)
        private = key.private_bytes(serialization.Encoding.DER, serialization.PrivateFormat.PKCS8, serialization.NoEncryption())
        set_key(env, "VAPID_PUBLIC_KEY", base64.urlsafe_b64encode(public).decode().rstrip("="))
        set_key(env, "VAPID_PRIVATE_KEY", base64.urlsafe_b64encode(private).decode().rstrip("="))
    if not values.get("VAPID_SUBJECT"):
        set_key(env, "VAPID_SUBJECT", "mailto:support@arevei.ai")
    if not values.get("CRON_SECRET"):
        set_key(env, "CRON_SECRET", secrets.token_urlsafe(32))
    print("Push configuration saved to backend/.env. Secrets were not printed. Restart the backend.")


if __name__ == "__main__":
    setup()
