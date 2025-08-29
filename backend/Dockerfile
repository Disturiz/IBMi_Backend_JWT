
FROM python:3.12-slim

RUN apt-get update && apt-get install -y --no-install-recommends     openjdk-21-jre-headless ca-certificates  && rm -rf /var/lib/apt/lists/*

ENV JAVA_HOME=/usr/lib/jvm/java-21-openjdk-amd64
ENV PATH="${JAVA_HOME}/bin:${PATH}"

WORKDIR /app
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt
COPY . .

ENV JT400_JAR=/app/drivers/jt400.jar
ENV JWT_SECRET=dev-CHANGE-ME
ENV JWT_EXPIRE_MIN=5
# ENV ALLOW_LIBS=QIWS,MYLIB

EXPOSE 8000
CMD ["uvicorn", "app:app", "--host", "0.0.0.0", "--port", "8000"]
