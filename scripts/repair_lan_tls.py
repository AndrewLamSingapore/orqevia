"""Reissue LAN certificates with strict X.509 identifiers, preserving keys.

This stages public certificates only. It never overwrites live files, exports
private keys, installs trust anchors, or restarts services.
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
from pathlib import Path

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization


def public_bytes(key):
    return key.public_key().public_bytes(serialization.Encoding.DER, serialization.PublicFormat.SubjectPublicKeyInfo)


def reissue(ca, ca_key, server, server_key):
    """Keep identities, validity windows and SPKI pins; repair extensions."""
    if ca.subject != ca.issuer or server.issuer != ca.subject:
        raise ValueError("Expected a self-signed LAN CA and its server certificate")
    if public_bytes(ca_key) != ca.public_key().public_bytes(
        serialization.Encoding.DER, serialization.PublicFormat.SubjectPublicKeyInfo
    ) or public_bytes(server_key) != server.public_key().public_bytes(
        serialization.Encoding.DER, serialization.PublicFormat.SubjectPublicKeyInfo
    ):
        raise ValueError("Certificate and private key do not match")
    if not ca.extensions.get_extension_for_class(x509.BasicConstraints).value.ca:
        raise ValueError("Issuer is not a CA")
    if server.extensions.get_extension_for_class(x509.BasicConstraints).value.ca:
        raise ValueError("Server must not be a CA")
    # Do not silently replace SAN validation with common-name matching.
    server.extensions.get_extension_for_class(x509.SubjectAlternativeName)
    now = dt.datetime.now(dt.timezone.utc)
    if any(not cert.not_valid_before_utc <= now < cert.not_valid_after_utc for cert in (ca, server)):
        raise ValueError("Expired or not-yet-valid certificates require explicit renewal")

    repaired = []
    for cert, key, is_ca in ((ca, ca_key, True), (server, server_key, False)):
        builder = (
            x509.CertificateBuilder()
            .subject_name(cert.subject)
            .issuer_name(cert.issuer)
            .public_key(key.public_key())
            .serial_number(x509.random_serial_number())
            .not_valid_before(cert.not_valid_before_utc)
            .not_valid_after(cert.not_valid_after_utc)
        )
        replaced = {x509.SubjectKeyIdentifier.oid, x509.AuthorityKeyIdentifier.oid}
        if not is_ca:
            replaced.add(x509.KeyUsage.oid)
        for extension in cert.extensions:
            if extension.oid not in replaced:
                builder = builder.add_extension(extension.value, extension.critical)
        builder = builder.add_extension(
            x509.SubjectKeyIdentifier.from_public_key(key.public_key()), False
        ).add_extension(x509.AuthorityKeyIdentifier.from_issuer_public_key(ca_key.public_key()), False)
        if not is_ca:
            builder = builder.add_extension(
                x509.KeyUsage(
                    digital_signature=True,
                    content_commitment=False,
                    key_encipherment=True,
                    data_encipherment=False,
                    key_agreement=False,
                    key_cert_sign=False,
                    crl_sign=False,
                    encipher_only=False,
                    decipher_only=False,
                ),
                True,
            )
        repaired.append(builder.sign(ca_key, hashes.SHA256()))
    return tuple(repaired)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--tls-dir", required=True, type=Path)
    parser.add_argument("--output-dir", required=True, type=Path)
    args = parser.parse_args()
    output = args.output_dir.resolve()
    if any((output / name).exists() for name in ("ca.crt", "server.crt")):
        raise SystemExit("Refusing to overwrite staged certificates")
    certs = [x509.load_pem_x509_certificate((args.tls_dir / name).read_bytes()) for name in ("ca.crt", "server.crt")]
    keys = [
        serialization.load_pem_private_key((args.tls_dir / name).read_bytes(), password=None)
        for name in ("ca.key", "server.key")
    ]
    new = reissue(certs[0], keys[0], certs[1], keys[1])
    output.mkdir(parents=True, exist_ok=True)
    for name, cert in zip(("ca.crt", "server.crt"), new):
        (output / name).write_bytes(cert.public_bytes(serialization.Encoding.PEM))
    print(
        json.dumps(
            {
                "status": "STAGED_PUBLIC_CERTIFICATES",
                "keys_preserved": True,
                "certificates": [
                    {"file": name, "sha256": cert.fingerprint(hashes.SHA256()).hex()}
                    for name, cert in zip(("ca.crt", "server.crt"), new)
                ],
            }
        )
    )


if __name__ == "__main__":
    main()
