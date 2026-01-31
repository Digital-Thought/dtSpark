"""
SSL certificate utilities for the web interface.

Handles generation of self-signed certificates for HTTPS support.

"""

import logging
import os.path
import socket
import ipaddress
from pathlib import Path
from datetime import datetime, timedelta, timezone
from typing import Tuple, Optional

from dtPyAppFramework.paths import ApplicationPaths

logger = logging.getLogger(__name__)


def generate_self_signed_certificate(
    cert_file: str,
    key_file: str,
    hostname: str = "localhost",
    validity_days: int = 365,
) -> bool:
    """
    Generate a self-signed SSL certificate and private key.

    Args:
        cert_file: Path where the certificate will be saved
        key_file: Path where the private key will be saved
        hostname: Hostname for the certificate (default: localhost)
        validity_days: Number of days the certificate is valid (default: 365)

    Returns:
        True if generation succeeded, False otherwise
    """
    try:
        from cryptography import x509
        from cryptography.x509.oid import NameOID
        from cryptography.hazmat.primitives import hashes
        from cryptography.hazmat.primitives.asymmetric import rsa
        from cryptography.hazmat.primitives import serialization
    except ImportError:
        logger.error("cryptography package is required for SSL certificate generation")
        logger.error("Install it with: pip install cryptography")
        return False

    try:
        # Generate private key
        logger.info("Generating RSA private key...")
        private_key = rsa.generate_private_key(
            public_exponent=65537,
            key_size=2048,
        )

        # Create certificate subject and issuer (same for self-signed)
        subject = issuer = x509.Name([
            x509.NameAttribute(NameOID.COUNTRY_NAME, "AU"),
            x509.NameAttribute(NameOID.STATE_OR_PROVINCE_NAME, "New South Wales"),
            x509.NameAttribute(NameOID.LOCALITY_NAME, "Sydney"),
            x509.NameAttribute(NameOID.ORGANIZATION_NAME, "Digital-Thought"),
            x509.NameAttribute(NameOID.COMMON_NAME, hostname),
        ])

        # Build certificate
        logger.info(f"Generating self-signed certificate for {hostname}...")
        cert = (
            x509.CertificateBuilder()
            .subject_name(subject)
            .issuer_name(issuer)
            .public_key(private_key.public_key())
            .serial_number(x509.random_serial_number())
            .not_valid_before(datetime.now(timezone.utc))
            .not_valid_after(datetime.now(timezone.utc) + timedelta(days=validity_days))
            .add_extension(
                x509.SubjectAlternativeName([
                    x509.DNSName(hostname),
                    x509.DNSName("localhost"),
                    x509.IPAddress(ipaddress.IPv4Address("127.0.0.1")),
                ]),
                critical=False,
            )
            .sign(private_key, hashes.SHA256())
        )

        # Ensure directory exists
        cert_path = Path(cert_file)
        key_path = Path(key_file)
        cert_path.parent.mkdir(parents=True, exist_ok=True)
        key_path.parent.mkdir(parents=True, exist_ok=True)

        # Write private key
        logger.info(f"Writing private key to {key_file}")
        with open(key_file, "wb") as f:
            f.write(
                private_key.private_bytes(
                    encoding=serialization.Encoding.PEM,
                    format=serialization.PrivateFormat.TraditionalOpenSSL,
                    encryption_algorithm=serialization.NoEncryption(),
                )
            )

        # Write certificate
        logger.info(f"Writing certificate to {cert_file}")
        with open(cert_file, "wb") as f:
            f.write(cert.public_bytes(serialization.Encoding.PEM))

        logger.info(f"Self-signed certificate generated successfully (valid for {validity_days} days)")
        return True

    except Exception as e:
        logger.error(f"Failed to generate self-signed certificate: {e}")
        return False


def check_certificate_files(cert_file: str, key_file: str) -> bool:
    """
    Check if certificate and key files exist and are readable.

    Args:
        cert_file: Path to certificate file
        key_file: Path to private key file

    Returns:
        True if both files exist and are readable, False otherwise
    """
    cert_path = Path(cert_file)
    key_path = Path(key_file)

    if not cert_path.exists():
        logger.debug(f"Certificate file not found: {cert_file}")
        return False

    if not key_path.exists():
        logger.debug(f"Key file not found: {key_file}")
        return False

    # Try to read files
    try:
        with open(cert_file, "r") as f:
            cert_content = f.read()
        with open(key_file, "r") as f:
            key_content = f.read()

        if not cert_content or not key_content:
            logger.warning("Certificate or key file is empty")
            return False

        return True
    except Exception as e:
        logger.error(f"Failed to read certificate files: {e}")
        return False


def setup_ssl_certificates(
    cert_file: str,
    key_file: str,
    auto_generate: bool = True,
    hostname: str = "localhost",
) -> Tuple[bool, Optional[str], Optional[str]]:
    """
    Setup SSL certificates, generating them if needed.

    Args:
        cert_file: Path to certificate file
        key_file: Path to private key file
        auto_generate: Whether to automatically generate if files don't exist
        hostname: Hostname for the certificate

    Returns:
        Tuple of (success, cert_file_path, key_file_path)
        Returns (False, None, None) if setup failed
    """
    # Convert to absolute paths
    cert_file = str(Path(ApplicationPaths().usr_data_root_path, cert_file).resolve())
    key_file = str(Path(ApplicationPaths().usr_data_root_path, key_file).resolve())

    # Check if files exist
    if check_certificate_files(cert_file, key_file):
        logger.info("SSL certificate files found and verified")
        return True, cert_file, key_file

    # Generate if auto-generate is enabled
    if auto_generate:
        logger.info("SSL certificate files not found, generating self-signed certificate...")
        if generate_self_signed_certificate(cert_file, key_file, hostname):
            return True, cert_file, key_file
        else:
            logger.error("Failed to generate SSL certificates")
            return False, None, None
    else:
        logger.error("SSL certificate files not found and auto-generation is disabled")
        return False, None, None
