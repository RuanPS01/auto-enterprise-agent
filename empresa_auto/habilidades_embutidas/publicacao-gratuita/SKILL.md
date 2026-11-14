---
name: publicacao-gratuita
description: Caminhos para colocar sites, aplicações e APIs no ar sem custo, e para expor serviços que rodam na máquina do agente. Use ao publicar ou atualizar qualquer produto na internet.
---

# Publicação gratuita

Planos gratuitos mudam com frequência. Antes de escolher um serviço, confirme os limites atuais com pesquisar_web e leia a página de preços com buscar_pagina.

## Opções por tipo de produto

**Site estático** (HTML, CSS, JavaScript, sem servidor):

- Hospedagem de páginas ligada a repositórios git: publica automaticamente a cada envio de código.
- Plataformas de sites estáticos com plano gratuito e CLI própria.

**Aplicação com servidor ou API**:

- Plataformas de funções sem servidor com plano gratuito.
- Plataformas de contêiner com plano gratuito (costumam hibernar por inatividade: avise isso na página se afetar o usuário).
- A própria máquina do agente, exposta por um túnel.

**Serviço na máquina do agente exposto por túnel**:

1. Suba o serviço com servico_iniciar e confirme que responde em `http://localhost:PORTA`.
2. Exponha com um túnel gratuito. Alguns clientes de túnel oferecem endereços temporários sem cadastro, bons para testes. Endereço fixo geralmente exige conta gratuita.
3. Suba o túnel também com servico_iniciar, para ser religado sozinho.
4. Leia o endereço público em servico_logs e teste com buscar_pagina.

A máquina do agente fica ligada o tempo todo, então hospedar nela é viável. O ponto fraco é a conexão doméstica: prefira hospedagem externa para o site principal e use a máquina para tarefas de bastidor.

## Roteiro de publicação

1. O produto funciona localmente e está registrado no git.
2. Escolha o serviço e crie a conta (habilidade contas-e-credenciais). Prefira serviços com CLI ou API, que dispensam cliques.
3. Guarde no cofre o login e, quando houver, o token de API.
4. Publique pela CLI ou por envio ao repositório.
5. **Confirme de fora**: abra o endereço público com buscar_pagina e com o navegador. Só considere publicado depois de ver o conteúdo certo no endereço público.
6. Registre o endereço com empresa_atualizar (campo site) e salve na memória como publicar novamente.
7. Crie uma automação de monitoramento que confere o endereço a cada poucas horas.

## Domínio

Use o subdomínio gratuito que a hospedagem fornece. Domínio próprio custa dinheiro: só com cartão cadastrado pelo dono e depois de o produto ter usuários.

## Autenticação de CLIs sem navegador humano

- Prefira tokens de API criados na página de configurações do serviço e passados por variável de ambiente.
- Fluxos de "código de dispositivo" podem ser concluídos pelo agente: a CLI mostra um endereço e um código, e o agente abre o endereço no navegador já conectado à conta.
- Nunca grave tokens em arquivos do repositório.
