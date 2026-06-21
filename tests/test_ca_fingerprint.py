import subprocess
from ctc.auth.ca_fingerprint import ca_fingerprint_sha256


def _make_cert(tmp_path):
    cert = tmp_path / "cert.pem"
    key = tmp_path / "key.pem"
    subprocess.run([
        "openssl", "req", "-x509", "-newkey", "rsa:2048",
        "-keyout", str(key), "-out", str(cert), "-days", "1", "-nodes",
        "-subj", "/CN=copilot-proxy-ca",
    ], check=True, capture_output=True)
    return cert


def test_matches_openssl(tmp_path):
    cert = _make_cert(tmp_path)
    expected = subprocess.run(
        ["openssl", "x509", "-in", str(cert), "-noout", "-fingerprint", "-sha256"],
        check=True, capture_output=True, text=True,
    ).stdout.split("=", 1)[1].strip()
    assert ca_fingerprint_sha256(str(cert)) == expected


def test_missing_file_returns_none(tmp_path):
    assert ca_fingerprint_sha256(str(tmp_path / "nope.pem")) is None
