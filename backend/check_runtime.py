REQ = [
    "fastapi",
    "uvicorn",
    "dotenv",
    "jose",
    "passlib",
    "multipart",
    "email_validator",
    "jaydebeapi",
    "jpype",
]
missing = []
for m in REQ:
    try:
        __import__(m)
    except Exception as e:
        missing.append(f"{m} -> {e.__class__.__name__}: {e}")
if missing:
    raise SystemExit("Dependencias faltantes:\n" + "\n".join(missing))
print("OK dependencias.")
