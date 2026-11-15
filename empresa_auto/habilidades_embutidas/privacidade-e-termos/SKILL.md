---
name: privacidade-e-termos
description: Como tratar dados pessoais de usuários conforme a LGPD e escrever a política de privacidade, os termos de uso e o aviso de cookies do produto, com textos verdadeiros e simples. Use antes de lançar qualquer produto que colete dados e ao mudar o que é coletado.
area: gestao
---

# Privacidade e termos de uso

Esta habilidade organiza o trabalho, mas não substitui um advogado. Decisões com risco jurídico relevante são relatadas ao dono com bloqueio_relatar.

## Habilidades especializadas

Esta é a visão geral. Para o trabalho detalhado há um conjunto dedicado, em português, já instalado: comece por **lgpd-audit** (orquestra as demais) e use lgpd-data-mapping (inventário), lgpd-legal-basis (bases legais), lgpd-privacy-policy (política), lgpd-dsar (direitos do titular), lgpd-incident-response (incidentes), lgpd-retention-erasure (prazos e exclusão) e lgpd-check (auditoria do site publicado). Encontre as outras com habilidade_buscar e a palavra lgpd.

## Princípios práticos

1. **Colete o mínimo.** Cada dado pedido precisa de um motivo ligado ao funcionamento do produto. Sem motivo, não peça.
2. **Diga a verdade.** A política descreve exatamente o que o sistema faz hoje. Se o sistema mudar, o texto muda junto.
3. **Proteja.** HTTPS, senhas com algoritmo próprio, acesso restrito, cópias de segurança. Veja a habilidade seguranca-defensiva.
4. **Devolva o controle.** A pessoa consegue ver, corrigir, exportar e apagar os próprios dados.
5. **Guarde só enquanto necessário.** Defina prazos e apague depois.

## Inventário de dados

Antes de escrever qualquer texto, liste em um arquivo `docs/dados-pessoais.md` do projeto:

| Dado | Para quê | Base legal | Onde fica | Quem recebe | Por quanto tempo |
| --- | --- | --- | --- | --- | --- |
| E-mail | Acesso à conta e avisos do serviço | Execução do contrato | Banco do produto | Provedor de e-mail | Enquanto a conta existir |

Inclua o que serviços de terceiros coletam por você: hospedagem, estatísticas, envio de e-mail, pagamentos.

Bases legais mais comuns em um produto de software: execução de contrato (o dado é necessário para o serviço), consentimento (por exemplo, boletim informativo e cookies não essenciais), obrigação legal e legítimo interesse (com cautela e avaliação registrada).

## Política de privacidade

Página pública, em linguagem simples, com:

1. Quem é o responsável e como falar com ele (e-mail da empresa).
2. Quais dados são coletados e como (informados pela pessoa, coletados automaticamente, vindos de terceiros).
3. Para que cada dado é usado e a base legal.
4. Com quem os dados são compartilhados (nomes dos fornecedores e finalidade) e se saem do país.
5. Por quanto tempo ficam guardados.
6. Direitos da pessoa: confirmar o tratamento, acessar, corrigir, apagar, levar os dados para outro serviço, retirar o consentimento. E como pedir.
7. Cookies e tecnologias parecidas.
8. Como mudanças na política serão avisadas, com a data da última atualização.

Diga também que o serviço é operado por sistemas automatizados de inteligência artificial e em que isso afeta a pessoa.

## Termos de uso

1. O que é o serviço e quem pode usar.
2. Conta: responsabilidade pela senha, dados verdadeiros.
3. Uso permitido e proibido.
4. Planos, preços, cobrança, cancelamento e reembolso, quando houver.
5. De quem é o conteúdo que a pessoa envia e que licença ela dá ao serviço para funcionar.
6. Disponibilidade e limites de responsabilidade, sem retirar direitos que a lei garante ao consumidor.
7. Encerramento da conta.
8. Lei aplicável e canal de contato.

Não copie os termos de outra empresa: eles descrevem outro serviço e são protegidos por direito autoral.

## Cookies e estatísticas

- Cookies necessários ao funcionamento não pedem consentimento, mas são informados.
- Estatísticas e publicidade com cookies pedem consentimento antes de carregar, com opção de recusar tão fácil quanto a de aceitar.
- Prefira ferramentas de estatística que não usam cookies nem identificam pessoas. Elas dispensam o aviso de consentimento e respeitam o visitante.

## Atender pedidos dos titulares

Crie no produto, ou atenda por e-mail, as rotinas de exportar e apagar dados. Responda em poucos dias, confirme a identidade pelo e-mail da conta e registre o pedido e a resposta. Pedido de exclusão apaga também de cópias de segurança no ciclo normal delas.

## Incidente com dados pessoais

Siga a seção de resposta a incidente da habilidade seguranca-defensiva e relate ao dono imediatamente. A lei prevê comunicação à autoridade de proteção de dados e aos afetados quando houver risco relevante, e essa decisão é do dono.

## Crianças e dados sensíveis

Produto voltado a crianças, ou que trate saúde, biometria, religião, opinião política ou outros dados sensíveis, tem exigências muito maiores. Evite esses dados. Se o negócio depender deles, relate ao dono antes de construir.

## Revisão

A cada mudança que altere a coleta ou o uso de dados: atualize o inventário, a política e a data, e avise os usuários quando a mudança for relevante.
