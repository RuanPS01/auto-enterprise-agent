---
name: seguranca-defensiva
description: Segurança defensiva dos sistemas da própria empresa, cobrindo segredos, dependências vulneráveis, análise estática do código, cabeçalhos e HTTPS do site, endurecimento do servidor, cópias de segurança e resposta a incidentes. Use antes de publicar, em revisões periódicas e quando houver suspeita de falha.
area: seguranca
---

# Segurança defensiva

**Escopo**: apenas os sistemas da empresa (código, site, contas, máquina do agente). Nunca varra, teste ou acesse sistemas de terceiros. Fazer isso é ilegal e contraria as regras do agente.

## Lista de verificação antes de publicar

1. Nenhum segredo no repositório.
2. Dependências sem vulnerabilidade conhecida grave.
3. Análise estática sem achados graves.
4. Entradas de usuário validadas no servidor. Consultas ao banco parametrizadas.
5. Senhas de usuários guardadas com algoritmo próprio para senhas (argon2 ou bcrypt), nunca em texto puro.
6. HTTPS em tudo, com os cabeçalhos de segurança.
7. Cópia de segurança funcionando.

## Segredos

```bash
git grep -n -I -i -E "(api[_-]?key|secret|token|senha|password)\s*[:=]" -- . ':!*.lock'
gitleaks detect --source . --no-banner      # nas versões novas: gitleaks dir .
```

Achou um segredo no histórico do git? Considere vazado: troque a chave no serviço, guarde a nova no cofre e só então limpe o repositório. Segredos entram no programa por variáveis de ambiente lidas de um arquivo `.env` listado no `.gitignore`.

## Dependências

```bash
npm audit --omit=dev                 # Node
uvx pip-audit -r requirements.txt    # Python
trivy fs --scanners vuln,secret,misconfig .   # várias linguagens, contêineres e configuração
```

Atualize o que tiver correção disponível e rode os testes. Com a credencial github-token, a extensão ext_github_dependabot mostra os alertas dos repositórios. A habilidade supply-chain-risk-auditor aprofunda a análise.

## Análise estática do código

```bash
uvx semgrep scan --config auto --error .   # regras da comunidade para várias linguagens
uvx bandit -r src                          # Python
```

Leia cada achado: confirme se é real antes de mexer. As habilidades security-and-hardening, sharp-edges e differential-review orientam a revisão.

## Site e API da empresa

```bash
curl -sI https://SEU-SITE | grep -i -E "strict-transport|content-security|x-content-type|referrer-policy|x-frame|permissions-policy"
```

Devem existir: `Strict-Transport-Security`, `Content-Security-Policy`, `X-Content-Type-Options: nosniff`, `Referrer-Policy`. Cookies de sessão com `Secure`, `HttpOnly` e `SameSite`. Limite de tentativas em login e em formulários.

Varredura passiva do próprio site (não ataca, só observa):

```bash
docker run --rm -t ghcr.io/zaproxy/zaproxy:stable zap-baseline.py -t https://SEU-SITE
```

## Máquina do agente

- Acesso por SSH só com chave, sem senha. Firewall liberando apenas o necessário (`ufw allow OpenSSH`, `ufw enable`).
- Atualizações automáticas de segurança do sistema.
- Serviços escutando em `127.0.0.1` e publicados por proxy ou túnel.
- O painel do agente fica em `127.0.0.1` ou protegido por token.
- Código da comunidade (habilidades, extensões, pacotes): prefira origens conhecidas e leia antes de executar.

## Contas da empresa

Senha única por serviço (senha_gerar), tudo no cofre. Tokens de API com o menor conjunto de permissões e, quando possível, com validade. Revogue tokens que não são mais usados.

## Resposta a incidente

1. **Conter**: tire do ar o que está comprometido (servico_parar), troque as credenciais afetadas.
2. **Entender**: o que aconteceu, desde quando, quais dados foram tocados. Guarde os registros.
3. **Corrigir** a causa e restaurar de uma cópia limpa, se preciso.
4. **Comunicar**: relate ao dono com bloqueio_relatar, com todos os fatos. Se dados pessoais de usuários foram expostos, a lei exige comunicação aos afetados e à autoridade: essa decisão é do dono.
5. **Registrar** na memória (categoria operacao) a causa e a correção.

## Rotina

Crie uma automação semanal que roda a verificação de dependências e de segredos nos projetos e uma mensal que revisa cabeçalhos do site e tokens em uso.
