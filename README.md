# Protótipo Lá vem história!: gerador de PDF/X-1a

Motor que transforma o livro do site no arquivo que a gráfica (Meta Brasil / UmLivro) pede no "Manual do Fechamento de Arquivo": PDF/X-1a:2001, CMYK, preto em K, cobertura de tinta até 280%, sangria e marcas de corte.

## Rodar localmente

Requer Node 20+, Python 3.9+ e Ghostscript (`gs`) no PATH.

```
npm install
python3 -m venv .venv && .venv/bin/pip install -r grafica/requirements.txt
PYTHON_GRAFICA=.venv/bin/python node server.js
```

Abra http://localhost:3000 para o formulário antigo do protótipo.

## Rotas

- `POST /grafica`: recebe o livro impresso pelo site no modo gráfica (campos `livro` e `fundo`) e devolve o PDF/X-1a. O relatório da validação vai no cabeçalho `X-Relatorio-Grafica` (JSON em base64). PDF reprovado volta com 422 e o relatório.
- `POST /gerar-pdf`: formulário original (pergunta, resposta e até 3 fotos, montado com pdfkit), agora passando pelo mesmo motor.

## Motor da gráfica

Tudo sobre cor, transparência, sangria e validação está em [`grafica/README.md`](grafica/README.md).

## Deploy

Render (Docker, plano Free). O Dockerfile instala Ghostscript e o ambiente Python do motor. Cada push na branch `main` dispara novo deploy.

## Perfil ICC

O perfil em `perfis-icc/` é um placeholder (Coated FOGRA39). Para trocar pelo da UmLivro, coloque o `.icc` na pasta e ajuste `ICC_PADRAO` e `CONDICAO` em `grafica/pipeline.py`.
