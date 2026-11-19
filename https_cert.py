"""Self-signed HTTPS certificate so phones/iPads can use the camera (QR scanning).

Browsers only allow the camera on https:// or http://localhost. The certificate is made once
(certs/, not committed) and remade when this PC gets an IP it does not cover, e.g. on a new
WiFi or hotspot. Each phone/iPad shows a "not private" warning the first time: tap through it.
"""
import datetime
import ipaddress
import socket
from pathlib import Path

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.x509.oid import NameOID

CERT_DIR = Path(__file__).parent / 'certs'
CERT, KEY = CERT_DIR / 'selfsigned.crt', CERT_DIR / 'selfsigned.key'


def local_ips():
    """This PC's IPv4 addresses (WiFi, Ethernet, hotspot...) plus localhost."""
    ips = {'127.0.0.1'}
    try:
        for info in socket.getaddrinfo(socket.gethostname(), None, socket.AF_INET):
            ips.add(info[4][0])
    except OSError:
        pass
    try:                                        # the address used to reach other devices
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
            s.connect(('10.255.255.255', 1))     # no packet is sent
            ips.add(s.getsockname()[0])
    except OSError:
        pass
    return sorted(ip for ip in ips if not ip.startswith('169.254.'))


def _covered_ips():
    try:
        cert = x509.load_pem_x509_certificate(CERT.read_bytes())
        san = cert.extensions.get_extension_for_class(x509.SubjectAlternativeName).value
        expired = cert.not_valid_after_utc < datetime.datetime.now(datetime.timezone.utc)
        return set() if expired else {str(ip) for ip in san.get_values_for_type(x509.IPAddress)}
    except (OSError, ValueError, x509.ExtensionNotFound):
        return set()


def ensure_cert():
    """Returns (cert path, key path), making a new certificate if needed."""
    ips = local_ips()
    if KEY.exists() and set(ips) <= _covered_ips():
        return str(CERT), str(KEY)
    CERT_DIR.mkdir(exist_ok=True)
    key = ec.generate_private_key(ec.SECP256R1())
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, 'Re:Source (local)')])
    now = datetime.datetime.now(datetime.timezone.utc)
    cert = (x509.CertificateBuilder()
            .subject_name(name).issuer_name(name).public_key(key.public_key())
            .serial_number(x509.random_serial_number())
            .not_valid_before(now - datetime.timedelta(days=1))
            .not_valid_after(now + datetime.timedelta(days=825))
            .add_extension(x509.SubjectAlternativeName(
                [x509.DNSName('localhost')] + [x509.IPAddress(ipaddress.ip_address(ip)) for ip in ips]),
                critical=False)
            .add_extension(x509.ExtendedKeyUsage([x509.oid.ExtendedKeyUsageOID.SERVER_AUTH]), critical=False)
            .sign(key, hashes.SHA256()))
    KEY.write_bytes(key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,
                                      serialization.NoEncryption()))
    CERT.write_bytes(cert.public_bytes(serialization.Encoding.PEM))
    print('Made a new HTTPS certificate for', ', '.join(ips))
    return str(CERT), str(KEY)
