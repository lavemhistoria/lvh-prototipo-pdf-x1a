# Protótipo Lá vem história! — Gerador de PDF/X-1a

Protótipo funcional que recebe uma pergunta (fixa), uma resposta em texto e até 3 fotos, e gera um PDF processado para conformidade real PDF/X-1a:2001, usando o mesmo pipeline documentado no Confluence do produto (conversão CMYK + Ghostscript).

## O que já foi testado e confirmado

Este protótipo foi testado localmente de ponta a ponta antes de chegar até você. O PDF final gerado foi inspecionado e confirma:

* Versão PDF 1.3 (compatibilidade Acrobat 4)
* GTS_PDFXVersion declarado como PDF/X-1a:2001
* OutputIntent (perfil de cor de saída) corretamente embutido no arquivo
* Conversão de imagens para CMYK, com detecção automática de fotos grayscale (convertidas para preto puro, não CMYK composto)

## Limitação importante, antes de qualquer coisa

O perfil ICC usado agora é **genérico** (Coated FOGRA39, um padrão de mercado), não o perfil real da UmLivro. Isso está documentado no código (`gerar-definicao-pdfx.js` e `PDFX_def_lvh.ps`). Quando a Bianca responder com o perfil real, veja a seção "Trocar o perfil ICC" abaixo.

## Estrutura do projeto

```
prototipo-lvh/
├── server.js                 → backend (Express + sharp + Ghostscript)
├── gerar-definicao-pdfx.js   → script para trocar o perfil ICC
├── PDFX_def_lvh.ps           → definição PDFX gerada (não editar manualmente)
├── perfis-icc/               → pasta com os perfis ICC disponíveis
├── public/
│   ├── index.html            → frontend
│   └── app.js                → lógica do frontend (upload, validação, envio)
├── Dockerfile                → usado pelo Render para montar o ambiente
├── package.json
└── .gitignore
```

## Passo a passo para colocar no ar (Render)

### 1. Criar uma conta no Render

Acesse https://render.com e crie uma conta (pode usar login com GitHub, o que facilita o próximo passo).

### 2. Subir este projeto para um repositório no GitHub

Se você ainda não tem um repositório para isso:

1. Crie um repositório novo no GitHub (pode ser privado)
2. No terminal, dentro da pasta do projeto:

```bash
git init
git add .
git commit -m "Protótipo inicial de geração de PDF/X-1a"
git branch -M main
git remote add origin https://github.com/SEU_USUARIO/NOME_DO_REPOSITORIO.git
git push -u origin main
```

(Substitua `SEU_USUARIO` e `NOME_DO_REPOSITORIO` pelos valores reais do seu repositório)

### 3. Criar o serviço no Render

1. No painel do Render, clique em **New** → **Web Service**
2. Conecte sua conta do GitHub, se ainda não tiver conectado
3. Selecione o repositório que você acabou de criar
4. O Render vai detectar o `Dockerfile` automaticamente. Confirme:
   - **Environment**: Docker
   - **Region**: a mais próxima de você (Europa, já que você está em Munique, ou EUA)
   - **Instance Type**: Free (suficiente para este protótipo)
5. Clique em **Create Web Service**

### 4. Aguardar o build

O Render vai puxar o código, montar a imagem Docker (instalando Ghostscript dentro do container), e iniciar o serviço. Isso leva entre 3 e 6 minutos na primeira vez. Você acompanha o progresso em tempo real na tela de logs do próprio Render.

### 5. Acessar o protótipo

Quando o build terminar, o Render te dá uma URL pública, algo como:

```
https://prototipo-lvh.onrender.com
```

Essa URL já é o protótipo funcionando, pronto para você testar com fotos reais.

### Importante sobre o plano gratuito do Render

No plano Free, o serviço "dorme" depois de um período de inatividade (geralmente 15 minutos sem uso) e demora de 30 a 60 segundos para "acordar" na próxima visita. Isso é absolutamente normal e esperado para um protótipo de prova de conceito, não é um bug.

## Trocar o perfil ICC (quando a Bianca responder)

1. Coloque o arquivo `.icc` que a gráfica fornecer dentro da pasta `perfis-icc/`
2. Rode localmente (ou via terminal do Render, se preferir):

```bash
node gerar-definicao-pdfx.js perfis-icc/nome-do-arquivo.icc "Nome do perfil da UmLivro"
```

3. Suba a alteração para o GitHub (`git add`, `git commit`, `git push`). O Render detecta automaticamente o push e refaz o deploy.

## Testar localmente antes de subir qualquer alteração

```bash
npm install
node server.js
```

Depois acesse `http://localhost:3000` no navegador.

## O que este protótipo NÃO faz (por ser um protótipo, não o produto final)

* Não valida cobertura de tinta (limite de 280%, documentado no Confluence). Essa validação ainda precisa ser implementada separadamente.
* Não aplica sangria, marcas de corte ou informações de página (decisão de produto já documentada: o produto real não usa sangria).
* O layout do PDF é simples e não usa o design system real do produto (Fraunces, paleta verde-marrom), pois é gerado via PDFKit (biblioteca de baixo nível), não via Puppeteer/HTML como está planejado para o produto final.
* Aceita apenas 1 pergunta fixa, sem conexão com banco de dados ou autenticação de usuário.
