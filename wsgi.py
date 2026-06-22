import os
from app import create_app
from dotenv import load_dotenv

load_dotenv()

app = create_app()

if __name__ == "__main__":
    cert = os.environ.get("SSL_CERT", "certs/cert.pem")
    key = os.environ.get("SSL_KEY", "certs/key.pem")
    port = int(os.environ.get("PORT", "5443"))

    ssl_ctx = None
    if os.path.exists(cert) and os.path.exists(key):
        import ssl

        ssl_ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        ssl_ctx.load_cert_chain(cert, key)

    app.run(host="0.0.0.0", port=port, debug=False, ssl_context=ssl_ctx)
