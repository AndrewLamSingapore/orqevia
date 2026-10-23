"""A real strict-client handshake guards the LAN certificate repair."""

import datetime as dt
import ipaddress
import socket
import ssl
import threading

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.x509.oid import ExtendedKeyUsageOID, NameOID
import pytest

from scripts.repair_lan_tls import reissue


def old_certificates():
    now = dt.datetime.now(dt.timezone.utc)
    ca_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "ORQEVIA test CA")])

    def base(subject, public_key):
        return (
            x509.CertificateBuilder()
            .subject_name(subject)
            .issuer_name(name)
            .public_key(public_key)
            .serial_number(x509.random_serial_number())
            .not_valid_before(now - dt.timedelta(minutes=1))
            .not_valid_after(now + dt.timedelta(days=1))
        )

    ca = (
        base(name, ca_key.public_key())
        .add_extension(x509.BasicConstraints(True, 0), True)
        .add_extension(x509.KeyUsage(True, False, False, False, False, True, True, False, False), True)
        .sign(ca_key, hashes.SHA256())
    )
    leaf = (
        base(x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "127.0.0.1")]), key.public_key())
        .add_extension(x509.BasicConstraints(False, None), True)
        .add_extension(x509.SubjectAlternativeName([x509.IPAddress(ipaddress.ip_address("127.0.0.1"))]), False)
        .add_extension(x509.ExtendedKeyUsage([ExtendedKeyUsageOID.SERVER_AUTH]), False)
        .sign(ca_key, hashes.SHA256())
    )
    return ca, ca_key, leaf, key


def test_strict_handshake_and_wrong_hostname(tmp_path):
    ca, ca_key, old_leaf, key = old_certificates()
    new_ca, leaf = reissue(ca, ca_key, old_leaf, key)
    for name, cert in [("ca.crt", new_ca), ("server.crt", leaf)]:
        (tmp_path / name).write_bytes(cert.public_bytes(serialization.Encoding.PEM))
    (tmp_path / "server.key").write_bytes(
        key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption())
    )
    client = ssl.create_default_context(cafile=str(tmp_path / "ca.crt"))
    client.verify_flags |= ssl.VERIFY_X509_STRICT
    server = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    server.load_cert_chain(tmp_path / "server.crt", tmp_path / "server.key")
    listener = socket.socket()
    listener.bind(("127.0.0.1", 0))
    listener.listen(2)
    listener.settimeout(5)

    def serve():
        for _ in range(2):
            conn, _ = listener.accept()
            try:
                with server.wrap_socket(conn, server_side=True) as stream:
                    stream.sendall(b"OK")
            except ssl.SSLError:
                conn.close()

    worker = threading.Thread(target=serve, daemon=True)
    worker.start()
    try:
        with socket.create_connection(listener.getsockname(), timeout=5) as conn:
            with client.wrap_socket(conn, server_hostname="127.0.0.1") as stream:
                assert stream.recv(2) == b"OK"
        with socket.create_connection(listener.getsockname(), timeout=5) as conn:
            with pytest.raises(ssl.SSLCertVerificationError):
                client.wrap_socket(conn, server_hostname="wrong.example")
    finally:
        worker.join(timeout=6)
        listener.close()
    assert not worker.is_alive()
    assert ca.subject == new_ca.subject
    assert key.public_key().public_numbers() == leaf.public_key().public_numbers()
    assert ca.public_key().public_numbers() == new_ca.public_key().public_numbers()
    assert (
        old_leaf.extensions.get_extension_for_class(x509.SubjectAlternativeName).value
        == leaf.extensions.get_extension_for_class(x509.SubjectAlternativeName).value
    )


def test_wrong_key_is_rejected():
    ca, ca_key, leaf, key = old_certificates()
    with pytest.raises(ValueError, match="do not match"):
        reissue(ca, key, leaf, key)


def test_non_ca_issuer_is_rejected():
    ca, ca_key, leaf, key = old_certificates()
    with pytest.raises(ValueError):
        reissue(leaf, key, leaf, key)
