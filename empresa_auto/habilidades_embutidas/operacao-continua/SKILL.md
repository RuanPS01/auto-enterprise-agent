---
name: operacao-continua
description: Rotinas para manter a empresa saudável depois do lançamento, com monitoramento, indicadores, revisão semanal e melhoria contínua. Use ao planejar a fase de operação e ao criar automações.
---

# Operação contínua

Depois do lançamento o trabalho vira um ciclo: medir, ouvir, corrigir, melhorar, divulgar. As rotinas abaixo viram automações (grupo operacao, ferramenta automacao_criar).

## Automações recomendadas

| Rotina | Intervalo sugerido | O que fazer |
| --- | --- | --- |
| Monitorar o produto | a cada 3 horas | Abrir o endereço público com buscar_pagina, conferir se responde com o conteúdo certo e, em caso de falha, diagnosticar (servico_listar, servico_logs) e corrigir. |
| Atender clientes | a cada 2 horas | Seguir a habilidade atendimento-ao-cliente. Só crie esta rotina depois que o e-mail da empresa existir. |
| Medir indicadores | todo dia | Coletar visitas, cadastros e uso, e registrar com metrica_registrar. |
| Ouvir o mercado | a cada 3 dias | Procurar menções ao produto e novas reclamações sobre o problema que ele resolve. Salvar na memória. |
| Publicar conteúdo | conforme a estratégia | Seguir a habilidade marketing-e-divulgacao. |
| Cópia de segurança | todo dia | Enviar o código ao repositório remoto e copiar os dados dos serviços para um local seguro. |

Não crie rotinas para o que ainda não existe. Cada rotina consome tempo de trabalho do agente.

## Revisão semanal

Uma vez por semana, no planejamento:

1. Compare os indicadores com os da semana anterior.
2. Liste o que funcionou e o que não funcionou, com base em dados.
3. Escolha no máximo três prioridades para a semana seguinte.
4. Registre com decisao_registrar.
5. Cancele tarefas e automações que deixaram de fazer sentido.

## Quando algo quebra

1. Confirme a falha de fora (buscar_pagina no endereço público).
2. Veja os registros: servico_logs, saída de comandos, painel da hospedagem.
3. Corrija a causa, não só o sintoma. Teste.
4. Registre na memória (categoria operacao) a causa e a correção.
5. Se usuários foram afetados, publique um aviso honesto na página.

## Quando mudar de rumo

Sinais de que a estratégia atual não funciona: semanas sem novos usuários apesar da divulgação, usuários que entram e não voltam, comentários dizendo que o problema não é importante.

Nesse caso, releia as reclamações e pedidos guardados na memória, escolha um ajuste (outro público, outra função principal, outro canal) e registre a decisão com as evidências. Mudar com base em dados é parte do trabalho. Trocar de ideia toda semana sem dados é desperdício.

## Custos

A operação deve continuar sem custo. Acompanhe os limites dos planos gratuitos. Antes de um limite estourar, otimize o uso ou migre para outra opção gratuita.
