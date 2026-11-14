---
name: contas-e-credenciais
description: Procedimento para criar contas gratuitas em serviços, guardar acessos no cofre e lidar com verificações. Use sempre que a empresa precisar de uma conta nova, de um e-mail ou de uma chave de API.
---

# Contas e credenciais

## Antes de criar

1. Ative o grupo contas e consulte credencial_listar: a conta pode já existir.
2. Confirme que o serviço tem plano gratuito suficiente e que os termos permitem uso comercial.
3. Leia os termos de uso quanto a contas automatizadas. Se o serviço proíbe, escolha outro.

## A conta de e-mail vem primeiro

Quase todo cadastro pede um e-mail e envia um link de confirmação. Por isso a primeira conta da empresa é o e-mail oficial.

1. Pesquise provedores de e-mail gratuitos que ofereçam acesso por IMAP e SMTP.
2. Crie a conta pelo navegador com um endereço ligado ao nome da empresa.
3. Guarde com email_configurar (endereço, senha e servidores SMTP e IMAP).
4. Teste com email_ler.

Se todos os provedores exigirem verificação humana ou telefone, relate com bloqueio_relatar pedindo ao dono um endereço de e-mail para a empresa, e siga em tarefas que não dependem de conta.

## Criando uma conta em um serviço

1. Gere a senha com senha_gerar. Uma senha diferente para cada serviço.
2. Abra a página de cadastro com navegador_abrir e preencha com navegador_digitar.
3. Use dados verdadeiros da empresa: nome da empresa, e-mail oficial. Nunca use dados de outra pessoa nem identidade falsa.
4. Envie o formulário e leia a página resultante.
5. Se pedir confirmação por e-mail, use email_ler, abra o link de confirmação no navegador.
6. Salve imediatamente com credencial_salvar (serviço, usuário, senha, endereço de login e observações sobre o plano).
7. Se o serviço oferecer token de API, crie um e salve como outra credencial, por exemplo `github-token`.

## Verificações humanas

CAPTCHA, verificação por telefone, envio de documento e análise manual existem para garantir que há uma pessoa responsável. O agente **não tenta burlar** nenhuma delas. Diante de uma:

1. Procure outro caminho legítimo: cadastro por API, outro serviço equivalente, entrar com uma conta já existente.
2. Se não houver, use bloqueio_relatar dizendo exatamente qual conta é necessária e para quê. O dono pode fornecer a conta pelo painel, e ela aparecerá em credencial_listar.
3. Continue com outras frentes. Não fique tentando de novo.

## Segurança

- Senhas e tokens só existem no cofre. Nunca em arquivos, repositórios, páginas ou mensagens.
- Ative verificação em duas etapas apenas se o segundo fator puder ser guardado no cofre (código TOTP). Anote o segredo nas observações da credencial.
- Guarde nas observações os códigos de recuperação que o serviço fornecer.
- Uma conta por serviço. Não crie contas duplicadas para contornar limites: isso viola os termos de uso.
