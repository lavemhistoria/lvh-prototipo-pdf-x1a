# imagem base com Node.js
FROM node:20-slim

# instala o Ghostscript no sistema (necessário para a conversão PDF/X-1a)
RUN apt-get update && \
    apt-get install -y ghostscript && \
    rm -rf /var/lib/apt/lists/*

WORKDIR /app

# copia apenas os arquivos de dependência primeiro (otimiza o cache do build)
COPY package.json package-lock.json ./
RUN npm install --omit=dev

# copia o restante do projeto
COPY . .

# pasta temporária usada durante a geração dos PDFs
RUN mkdir -p temp

EXPOSE 3000

CMD ["node", "server.js"]
