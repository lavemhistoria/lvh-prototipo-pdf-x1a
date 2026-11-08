# Lá vem história! - protótipo PDF/X-1a

Leia `HANDOFF.md` (pacote de handoff) para contexto completo, decisões e pendências.

## Regras

- Responder em português do Brasil.
- Nunca usar travessão (caractere longo) em respostas, código, comentários ou documentos.
- Ser crítico e questionar premissas do Moreno em vez de apenas concordar.
- Nunca commitar `PDFX_def_lvh.ps` (gerado em runtime) nem arquivos em `temp/`.
- Ghostscript: a ordem dos argumentos importa (opções, -sOutputFile, .ps de definição, PDF de entrada).

## Comandos

- Rodar: `npm install && node server.js` (requer `gs` no PATH)
- Deploy: push na `main` dispara o Render
