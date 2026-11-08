FROM node:20-slim

# Ghostscript fecha o PDF/X-1a; Python (pikepdf, Pillow com LittleCMS, numpy)
# faz a conversao de cor, o limite de tinta, a sangria e a validacao
RUN apt-get update && \
    apt-get install -y ghostscript python3 python3-venv && \
    rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY grafica/requirements.txt grafica/requirements.txt
RUN python3 -m venv /opt/grafica && \
    /opt/grafica/bin/pip install --no-cache-dir -r grafica/requirements.txt
ENV PYTHON_GRAFICA=/opt/grafica/bin/python

# sem package-lock.json no repo, por isso copiamos so o package.json
COPY package.json ./
RUN npm install --omit=dev

COPY . .
RUN mkdir -p temp

EXPOSE 3000
CMD ["node", "server.js"]
