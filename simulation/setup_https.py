"""Create a local development CA and HTTPS certificate for the phone bridge.

Only the public phone-ca.crt is transferred to the phone. Private keys remain
inside the ignored .local-tls folder. This script does not install trust or
change any device settings.
"""

import argparse
import ipaddress
from datetime import datetime, timedelta, timezone
from pathlib import Path

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.x509.oid import ExtendedKeyUsageOID, NameOID

TLS_DIR = Path(__file__).resolve().parents[1] / '.local-tls'


def create_certificates(ip: str) -> None:
    address = ipaddress.ip_address(ip)
    TLS_DIR.mkdir(exist_ok=True)
    ca_key_file = TLS_DIR / 'ca-key.pem'
    ca_file = TLS_DIR / 'phone-ca.crt'
    now = datetime.now(timezone.utc)
    ca = x509.load_pem_x509_certificate(ca_file.read_bytes()) if ca_file.exists() else None
    has_key_id = ca is not None and any(isinstance(ext.value, x509.SubjectKeyIdentifier) for ext in ca.extensions)
    if ca_key_file.exists() and has_key_id:
        ca_key = serialization.load_pem_private_key(ca_key_file.read_bytes(), password=None)
        ca = x509.load_pem_x509_certificate(ca_file.read_bytes())
    else:
        ca_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, 'STILL HERE local simulation CA')])
        ca = (x509.CertificateBuilder().subject_name(name).issuer_name(name)
              .public_key(ca_key.public_key()).serial_number(x509.random_serial_number())
              .not_valid_before(now - timedelta(minutes=5)).not_valid_after(now + timedelta(days=365))
              .add_extension(x509.BasicConstraints(ca=True, path_length=0), critical=True)
              .add_extension(x509.SubjectKeyIdentifier.from_public_key(ca_key.public_key()), critical=False)
              .add_extension(x509.KeyUsage(digital_signature=True, content_commitment=False,
                  key_encipherment=False, data_encipherment=False, key_agreement=False,
                  key_cert_sign=True, crl_sign=True, encipher_only=False, decipher_only=False), critical=True)
              .sign(ca_key, hashes.SHA256()))
        ca_key_file.write_bytes(ca_key.private_bytes(serialization.Encoding.PEM,
            serialization.PrivateFormat.PKCS8, serialization.NoEncryption()))
        ca_file.write_bytes(ca.public_bytes(serialization.Encoding.PEM))
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    cert = (x509.CertificateBuilder()
            .subject_name(x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, str(address))]))
            .issuer_name(ca.subject).public_key(key.public_key())
            .serial_number(x509.random_serial_number())
            .not_valid_before(now - timedelta(minutes=5)).not_valid_after(now + timedelta(days=90))
            .add_extension(x509.BasicConstraints(ca=False, path_length=None), critical=True)
            .add_extension(x509.SubjectKeyIdentifier.from_public_key(key.public_key()), critical=False)
            .add_extension(x509.AuthorityKeyIdentifier.from_issuer_public_key(ca_key.public_key()), critical=False)
            .add_extension(x509.SubjectAlternativeName([x509.IPAddress(address),
                x509.IPAddress(ipaddress.ip_address('127.0.0.1')), x509.DNSName('localhost')]), critical=False)
            .add_extension(x509.ExtendedKeyUsage([ExtendedKeyUsageOID.SERVER_AUTH]), critical=False)
            .sign(ca_key, hashes.SHA256()))
    (TLS_DIR / 'server-key.pem').write_bytes(key.private_bytes(serialization.Encoding.PEM,
        serialization.PrivateFormat.PKCS8, serialization.NoEncryption()))
    (TLS_DIR / 'server.pem').write_bytes(cert.public_bytes(serialization.Encoding.PEM))
    print(f'Public phone certificate: {ca_file}')
    print(f'Download through the HTTP bridge: http://{address}:8765/phone-ca.crt')
    print('Install that public CA certificate on the phone, then restart the bridge with:')
    print('python -m uvicorn simulation.phone_bridge:app --host 0.0.0.0 --port 8765 '
          '--ssl-keyfile .local-tls/server-key.pem --ssl-certfile .local-tls/server.pem')
    print(f'Phone controller: https://{address}:8765')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--ip', required=True, help='Laptop Wi-Fi IPv4 address')
    create_certificates(parser.parse_args().ip)
