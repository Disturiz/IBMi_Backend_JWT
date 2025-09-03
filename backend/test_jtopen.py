import os
from dotenv import load_dotenv
import jpype

load_dotenv()
jar = os.path.abspath(os.getenv("JT400_JAR", ""))

print("JT400_JAR =", jar, "exists?", os.path.exists(jar))

if not os.path.exists(jar):
    raise SystemExit("El jt400.jar no existe en esa ruta.")

# Arrancar la JVM *solo* para probar el classpath con el jar
if not jpype.isJVMStarted():
    jpype.startJVM(classpath=[jar])

# Intentar cargar la clase del driver
AS400Driver = jpype.JClass("com.ibm.as400.access.AS400JDBCDriver")
print("Driver cargado OK:", AS400Driver)
