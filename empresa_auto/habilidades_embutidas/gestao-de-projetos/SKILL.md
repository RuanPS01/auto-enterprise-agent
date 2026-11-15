---
name: gestao-de-projetos
description: Gestão de projeto e de produto da empresa, com roteiro, priorização, divisão em tarefas, critérios de pronto, riscos e revisão semanal, usando a fila interna e, quando houver, GitHub Issues e Projects. Use ao planejar, repriorizar ou acompanhar entregas.
area: gestao
---

# Gestão de projetos

A fila de tarefas do agente é o sistema de gestão da empresa. Esta habilidade diz como mantê-la saudável.

## Do objetivo à tarefa

1. **Objetivo do período** (uma a quatro semanas): um resultado mensurável, não uma lista de afazeres. Exemplo: "20 pessoas usaram o produto de ponta a ponta". Registre com empresa_atualizar (campo estrategia).
2. **Entregas**: de três a seis coisas concretas que levam ao objetivo.
3. **Tarefas**: cada entrega vira tarefas que cabem em uma sessão de trabalho. Crie com tarefa_criar.

Uma boa tarefa tem: verbo no início, um único resultado, o contexto necessário para executar sem outras fontes, e o critério de pronto ("está pronto quando...").

## Priorização

Pontue cada candidata de 1 a 5 em impacto no objetivo, confiança de que funciona e facilidade. Multiplique os três. Faça primeiro o que tem a maior pontuação. Prioridades da fila: 1 para o que destrava outras tarefas ou corrige algo quebrado, 2 para entregas do objetivo atual, 3 para melhorias, 4 e 5 para o que pode esperar.

Regras:

- No máximo três frentes ao mesmo tempo. Terminar vale mais que começar.
- Algo quebrado em produção passa na frente de tudo.
- Tarefa que falhou duas vezes precisa ser redesenhada (menor, outro caminho), não repetida.
- Cancele o que perdeu o sentido (tarefa_cancelar). Fila limpa é fila útil.

## Critérios de pronto

- Código: roda, foi testado, está no git, o README diz como usar.
- Publicação: aberta pelo endereço público e conferida.
- Conteúdo: revisado, publicado, com o link salvo na memória.
- Pesquisa: achados na memória, com fontes.

## Riscos e dependências

Mantenha na memória uma nota "Riscos do projeto" com: o risco, o sinal de que está acontecendo e a resposta planejada. Riscos típicos: depender de um plano gratuito que pode mudar, de uma conta que exige verificação humana, de um único canal de aquisição.

Dependência de terceiros ou do dono vira impedimento (bloqueio_relatar) e a tarefa correspondente é adiada com adiar_minutos, enquanto o trabalho segue em outra frente.

## Revisão semanal

1. Compare os indicadores com a semana anterior (grupo gestao, metrica_registrar).
2. O que foi concluído, o que falhou e por quê.
3. O objetivo do período ainda faz sentido? Se não, registre a mudança com decisao_registrar.
4. Defina as três prioridades da próxima semana.

## Quando houver repositório no GitHub

- O programa `gh` cria e lista issues pela linha de comando: `gh issue create --title "..." --body "..."`, `gh issue list`, `gh issue close NUMERO`. Exige `gh auth login` com token (variável GH_TOKEN).
- Com a credencial github-token no cofre ficam disponíveis as extensões ext_github_issues e ext_github_projetos.
- Use issues para o que é público (defeitos relatados por usuários, pedidos). A fila interna continua sendo a fonte da verdade do agente.
- Mantenha um arquivo CHANGELOG.md no repositório do produto com as mudanças de cada versão.

## Habilidades relacionadas

spec-driven-development (especificar antes de construir), planning-and-task-breakdown (quebrar em tarefas), idea-refine (lapidar uma ideia), shipping-and-launch (lista de verificação de lançamento).
