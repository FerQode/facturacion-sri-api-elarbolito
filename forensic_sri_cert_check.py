import os
import sys
import base64
import hashlib
import binascii
import subprocess

def run_forensic():
    print("==================================================")
    print("🔎 SRI PKCS#12 FORENSIC DIAGNOSTIC TOOL")
    print("==================================================")

    b64_env = os.environ.get('SRI_FIRMA_BASE64', '')
    p12_pass = os.environ.get('SRI_FIRMA_PASS', '')

    if not b64_env:
        print("[CRÍTICO] La variable SRI_FIRMA_BASE64 no está definida o está vacía.")
        sys.exit(1)
    
    if not p12_pass:
        print("[CRÍTICO] La variable SRI_FIRMA_PASS no está definida o está vacía.")
        sys.exit(1)

    print(f"[*] Longitud bruta del Base64 original: {len(b64_env)} caracteres")

    b64_clean = b64_env.strip().replace('"', '').replace('\r', '').replace('\n', '').replace(' ', '')
    
    missing_padding = len(b64_clean) % 4
    if missing_padding:
        b64_clean += '=' * (4 - missing_padding)

    try:
        p12_bytes = base64.b64decode(b64_clean, validate=True)
    except Exception as e:
        print(f"\n[❌ FATAL] FALLO EN DECODIFICACIÓN BASE64.")
        print(f"Detalle Técnico: {str(e)}")
        sys.exit(1)

    cert_path = '/tmp/forensic_cert.p12'
    
    with open(cert_path, 'wb') as f:
        f.write(p12_bytes)
        f.flush()
        os.fsync(f.fileno())

    size_disk = os.path.getsize(cert_path)
    sha256_hash = hashlib.sha256(p12_bytes).hexdigest()
    
    first_32_hex = binascii.hexlify(p12_bytes[:32]).decode('ascii')
    last_32_hex = binascii.hexlify(p12_bytes[-32:]).decode('ascii')

    print("\n================== RADIOGRAFÍA ==================")
    print(f"SHA-256        : {sha256_hash}")
    print(f"Tamaño en Disco: {size_disk} bytes")
    print(f"Primeros 32 hex: {first_32_hex}")
    print(f"Últimos  32 hex: {last_32_hex}")
    print("=================================================")
    
    if not first_32_hex.startswith("3082"):
        print(f"\n[❌ FATAL] MAGIC NUMBER INCORRECTO. No comienza con 3082.")
        sys.exit(1)
    else:
        print("[OK] Cabecera ASN.1 válida detectada (3082...).")

    env_vars = os.environ.copy()
    env_vars['P12_PASS'] = p12_pass

    print("\n[*] Ejecutando OpenSSL Validator...")
    openssl_cmd = ["openssl", "pkcs12", "-in", cert_path, "-info", "-noout", "-passin", "env:P12_PASS"]
    
    try:
        result_ssl = subprocess.run(openssl_cmd, capture_output=True, text=True, env=env_vars)
        print(f"OpenSSL Return Code: {result_ssl.returncode}")
        print(f"OpenSSL STDOUT:\n{result_ssl.stdout}")
        print(f"OpenSSL STDERR:\n{result_ssl.stderr}")
    except FileNotFoundError:
        print("[-] OpenSSL no está instalado.")

    print("\n[*] Entorno de Java...")
    try:
        java_info = subprocess.run(["java", "-version"], capture_output=True, text=True)
        print(f"Java Version STDOUT:\n{java_info.stdout}")
        print(f"Java Version STDERR:\n{java_info.stderr}")
    except FileNotFoundError:
        print(f"[❌ FATAL] Java no encontrado.")

    print("\n[*] Ejecutando Java Keytool...")
    keytool_cmd = ["keytool", "-list", "-storetype", "PKCS12", "-keystore", cert_path, "-storepass", p12_pass]
    
    try:
        result_kt = subprocess.run(keytool_cmd, capture_output=True, text=True)
        print(f"Keytool Return Code: {result_kt.returncode}")
        print(f"Keytool STDOUT:\n{result_kt.stdout}")
        print(f"Keytool STDERR:\n{result_kt.stderr}")
    except FileNotFoundError:
        print("[-] Keytool no está instalado.")

if __name__ == "__main__":
    run_forensic()
