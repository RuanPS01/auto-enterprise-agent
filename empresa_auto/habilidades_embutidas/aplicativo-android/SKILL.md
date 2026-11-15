---
name: aplicativo-android
description: Caminhos para entregar um aplicativo Android sem loja paga, gerando um APK distribuído por link, e quando preferir uma aplicação web instalável. Use quando o produto precisar existir como aplicativo de celular.
area: programacao
---

# Aplicativo Android sem custo

## Primeiro, avalie se precisa de APK

Uma aplicação web instalável (PWA) cobre a maioria dos casos: funciona em Android e iPhone, instala pela tela do navegador, atualiza sozinha e não depende de loja. Para isso o site precisa de HTTPS, de um arquivo de manifesto e de um service worker.

Gere um APK apenas quando o produto precisar de recursos que o navegador não oferece ou quando o público espera baixar um aplicativo.

## Caminhos para gerar o APK

1. **Empacotar a aplicação web**: ferramentas de código aberto transformam um site ou PWA em um projeto Android (por exemplo Capacitor, ou Bubblewrap para Trusted Web Activity). É o caminho mais curto quando o produto já existe na web.
2. **Projeto nativo**: Gradle com Kotlin ou Java. Exige mais trabalho e só compensa para recursos nativos.

Os dois caminhos precisam, na máquina do agente, de JDK e das ferramentas de linha de comando do Android SDK, todos gratuitos. Confirme os requisitos atuais na documentação oficial com pesquisar_web antes de instalar.

## Roteiro geral

1. Instale JDK e as ferramentas de linha de comando do Android SDK. Aceite as licenças pela opção não interativa do gerenciador do SDK.
2. Gere o projeto Android a partir da aplicação web.
3. Crie a chave de assinatura com `keytool`. Guarde no cofre a senha da chave e salve o arquivo da chave fora de qualquer repositório público. Perder essa chave impede atualizar o aplicativo.
4. Compile a versão de lançamento assinada.
5. Teste a instalação em um emulador, se a máquina suportar, ou confira o APK com as ferramentas de análise do SDK.

## Distribuição sem loja paga

- Página de download no site da empresa, com o APK publicado como arquivo de uma versão do repositório.
- Instruções claras para o usuário permitir a instalação fora da loja, explicando o motivo.
- Lojas de aplicativos de código aberto aceitam projetos abertos sem taxa, mediante revisão.
- Publique junto o código de verificação (SHA-256) do APK.

As lojas oficiais cobram taxa de cadastro e exigem identificação de uma pessoa. Só considere com cartão cadastrado pelo dono e, mesmo assim, relate antes com bloqueio_relatar, porque o cadastro pede dados pessoais do dono.

## Atualizações

Sem loja, o aplicativo não atualiza sozinho. Inclua no aplicativo uma verificação de versão que avisa o usuário e leva à página de download.
