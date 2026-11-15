---
name: infraestrutura-e-servidores
description: Infraestrutura da empresa na máquina do agente e em nuvem gratuita, com Docker, proxy reverso com HTTPS, túneis, serviços, cópias de segurança, monitoramento, integração contínua e programas de código aberto auto-hospedados. Use ao subir, manter ou diagnosticar qualquer servidor ou serviço.
area: infraestrutura
---

# Infraestrutura e servidores

Confira em AMBIENTE quais programas existem e se é permitido instalar pacotes do sistema. Sem essa permissão, use contêineres ou instalações na pasta do usuário (uv, npm, binários baixados).

## Processos de longa duração

Tudo o que precisa ficar no ar sobe com servico_iniciar (grupo operacao): o agente religa se cair e depois de reiniciar a máquina. O comando deve ficar em primeiro plano. Diagnóstico: servico_listar e servico_logs.

## Docker

```bash
docker compose up -d                 # sobe o que está no compose.yaml da pasta
docker compose ps                    # situação
docker compose logs --tail 100 NOME  # registros de um serviço
docker compose pull && docker compose up -d   # atualizar
docker system df                     # uso de disco
```

- Um diretório por sistema, com `compose.yaml` e um arquivo `.env` fora do git.
- Dados sempre em volumes nomeados ou pastas montadas, nunca dentro do contêiner.
- Fixe a versão das imagens (`imagem:1.2.3`). `latest` quebra sem aviso.
- Exponha portas só em `127.0.0.1:PORTA:PORTA` e publique pela internet pelo proxy ou pelo túnel.

## Publicar um serviço local na internet

**Túnel rápido, sem conta** (endereço temporário, bom para testes):

```bash
cloudflared tunnel --url http://localhost:3000
```

O endereço aparece na saída do comando. Suba com servico_iniciar e leia em servico_logs. Endereço fixo exige conta gratuita na Cloudflare e um domínio.

**Proxy reverso com HTTPS automático** (quando a máquina tem domínio e portas 80 e 443 abertas), arquivo `Caddyfile`:

```
exemplo.com {
    reverse_proxy localhost:3000
}
```

```bash
caddy run --config Caddyfile
```

## Cópias de segurança

- Código: `git push` para um repositório remoto a cada entrega.
- SQLite: `sqlite3 dados.db ".backup 'copia-AAAA-MM-DD.db'"` (seguro com o banco em uso).
- PostgreSQL em contêiner: `docker compose exec -T banco pg_dump -U usuario base > copia.sql`.
- Pastas: `tar czf copia-AAAA-MM-DD.tar.gz pasta/`.
- Guarde cópias fora da máquina e teste a restauração de vez em quando. Cópia nunca restaurada não é cópia.
- Crie uma automação diária (automacao_criar) para isso.

## Monitoramento

- Disponibilidade: automação que abre o endereço público com buscar_pagina e confere o conteúdo.
- Máquina: `df -h` (disco), `free -h` (memória), `uptime` (carga). Disco cheio é a causa mais comum de queda.
- Limpeza: `docker system prune -f`, registros antigos, caches de build.
- Para painéis de disponibilidade há programas abertos auto-hospedados (por exemplo Uptime Kuma).

## Integração contínua no GitHub

Arquivo `.github/workflows/testes.yml`:

```yaml
name: testes
on: [push]
jobs:
  testes:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: "3.12"
      - run: pip install -r requirements.txt
      - run: pytest
```

Segredos entram por "secrets" do repositório, nunca no arquivo. Acompanhe as execuções com `gh run list` e `gh run view --log-failed`, ou com a extensão ext_github_actions.

## Programas abertos que a empresa pode hospedar

Antes de pagar ou depender de um serviço, veja se há alternativa aberta que roda em Docker: busca (SearXNG), agendamento de redes sociais (Postiz), estatísticas de site (Umami, Plausible), boletim por e-mail (Listmonk), atendimento (Chatwoot), monitoramento (Uptime Kuma). Leia os requisitos de memória de cada um antes: a máquina também roda o modelo de linguagem.

## Diagnóstico de falhas

1. O processo está de pé? (servico_listar, `docker compose ps`)
2. O que dizem os registros? (servico_logs, `docker compose logs`)
3. A porta responde localmente? (`curl -sS -m 10 -I http://localhost:PORTA`)
4. Responde de fora? (buscar_pagina no endereço público)
5. Disco, memória e carga estão normais?

Corrija a causa, teste, e registre na memória (categoria operacao) o que aconteceu.

## Habilidades relacionadas

publicacao-gratuita, ci-cd-and-automation, observability-and-instrumentation, shipping-and-launch, seguranca-defensiva. Extensões do catálogo: cloudflare, netlify, sentry, github-actions.
