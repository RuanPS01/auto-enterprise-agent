"""Memória, fila de tarefas e dados da empresa."""

from __future__ import annotations

import json
import time

from .base import Ambiente, Catalogo, P

AREAS = ["pesquisa", "produto", "engenharia", "marketing", "atendimento", "operacoes", "financeiro"]
FASES = ["descoberta", "validacao", "construcao", "lancamento", "operacao"]
# Fração máxima da janela de contexto que as descrições de ferramentas podem ocupar.
LIMITE_CONTEXTO_FERRAMENTAS = 0.45
# Extensões com mais ferramentas que isto só são ligadas com filtro.
MAX_FERRAMENTAS_SEM_FILTRO = 14
CAMPOS_EMPRESA = [
    "nome",
    "missao",
    "proposta_de_valor",
    "publico_alvo",
    "produto",
    "modelo_de_receita",
    "estrategia",
    "fase",
    "site",
    "canais",
]


def registrar(cat: Catalogo, amb: Ambiente) -> None:
    banco = amb.banco

    # ------------------------------------------------------------------ controle da tarefa
    @cat.ferramenta(
        "concluir_tarefa",
        "Encerra a tarefa atual. Chame quando o objetivo foi atingido, ou quando ficou comprovado que não é "
        "possível atingi-lo. O resultado deve relatar fatos: o que foi feito, onde está, o que falta.",
        resultado=P("string", "Relato objetivo do que foi feito e dos resultados obtidos."),
        sucesso=P("boolean", "true se o objetivo foi atingido, false caso contrário (padrão true).", obrigatorio=False),
    )
    def concluir_tarefa(resultado: str, sucesso: bool = True) -> str:
        amb.conclusao = {"resultado": resultado.strip(), "sucesso": bool(sucesso)}
        return "Tarefa encerrada."

    def _custo(nomes_grupos: set[str], avulsas: set[str]) -> int:
        """Estimativa, em tokens, do espaço que as descrições das ferramentas ocupam no contexto do modelo."""
        return len(json.dumps(cat.esquemas(nomes_grupos, avulsas), ensure_ascii=False)) // 3

    @cat.ferramenta(
        "ativar_ferramentas",
        "Liga um grupo extra de ferramentas para esta tarefa. Grupos embutidos: navegador (usar sites), contas "
        "(cofre e e-mail), operacao (serviços e automações), gestao (dados da empresa e fila de tarefas), expansao "
        "(habilidades e extensões), pagamento (cartão do dono, se houver). Extensões usam grupos ext_NOME; nas que "
        "têm muitas ferramentas, informe um filtro para ligar só as necessárias.",
        grupo=P("string", "Nome do grupo a ativar."),
        filtro=P("string", "Só para extensões: palavras que aparecem no nome das ferramentas desejadas, separadas por vírgula.", obrigatorio=False),
    )
    def ativar_ferramentas(grupo: str, filtro: str = "") -> str:
        grupo = grupo.strip().lower()
        disponiveis = cat.grupos()
        if grupo == "pagamento" and not amb.cofre.obter_cartao():
            return "O dono não cadastrou cartão: não há ferramentas de pagamento. Tudo deve ser gratuito."
        if grupo not in disponiveis:
            return f"ERRO: grupo desconhecido. Grupos disponíveis: {', '.join(sorted(disponiveis))}."
        limite = int(amb.cfg.contexto_tokens * LIMITE_CONTEXTO_FERRAMENTAS)
        estouro = (
            "NEGADO: essas ferramentas não cabem na memória do modelo junto com as que já estão ligadas. "
            "Use um filtro mais específico, ou conclua esta etapa e crie outra tarefa para a próxima."
        )

        if grupo.startswith("ext_") and amb.extensoes is not None:
            try:
                amb.extensoes.garantir(grupo[4:])
            except Exception as erro:
                return f"ERRO ao iniciar a extensão: {erro}"
            nomes = cat.nomes({grupo})
            termos = [t.strip().lower() for t in filtro.split(",") if t.strip()]
            if termos:
                escolhidas = [n for n in nomes if any(t in n.lower() for t in termos)]
                if not escolhidas:
                    return f"Nenhuma ferramenta combina com o filtro. Ferramentas da extensão: {', '.join(nomes)}."
            elif len(nomes) > MAX_FERRAMENTAS_SEM_FILTRO:
                return (
                    f"A extensão tem {len(nomes)} ferramentas, demais para ligar de uma vez. Chame de novo com "
                    f"filtro, usando partes dos nomes das que você precisa, separadas por vírgula. "
                    f"Ferramentas: {', '.join(nomes)}."
                )
            else:
                escolhidas = nomes
            if _custo(amb.grupos_ativos, amb.ferramentas_avulsas | set(escolhidas)) > limite:
                return estouro
            amb.ferramentas_avulsas.update(escolhidas)
            return f"Ativadas {len(escolhidas)} ferramentas da extensão: {', '.join(escolhidas)}."

        if _custo(amb.grupos_ativos | {grupo}, amb.ferramentas_avulsas) > limite:
            return estouro
        amb.grupos_ativos.add(grupo)
        return f"Grupo '{grupo}' ativado. Ferramentas novas: {', '.join(cat.nomes({grupo}))}."

    # ------------------------------------------------------------------ memória
    @cat.ferramenta(
        "memoria_salvar",
        "Guarda um conhecimento permanente da empresa: descobertas de pesquisa, aprendizados, endereços de "
        "serviços, como algo foi feito. O que não for salvo aqui será esquecido ao fim da tarefa.",
        titulo=P("string", "Título curto e específico."),
        conteudo=P("string", "O conhecimento, com dados concretos (números, links, nomes)."),
        categoria=P(
            "string",
            "Categoria da nota.",
            obrigatorio=False,
            enum=["mercado", "cliente", "produto", "tecnico", "marketing", "operacao", "aprendizado", "geral"],
        ),
    )
    def memoria_salvar(titulo: str, conteudo: str, categoria: str = "geral") -> str:
        banco.salvar_memoria(titulo, conteudo, categoria)
        amb.registro.evento(
            "memoria", f"Conhecimento salvo: {titulo}", conteudo, tarefa_id=(amb.tarefa_atual or {}).get("id")
        )
        return "Conhecimento salvo na memória permanente."

    @cat.ferramenta(
        "memoria_buscar",
        "Busca na memória permanente da empresa. Consulte antes de pesquisar de novo algo já estudado.",
        consulta=P("string", "Palavras-chave do que procura."),
    )
    def memoria_buscar(consulta: str) -> str:
        achados = banco.buscar_memorias(consulta, limite=6)
        if not achados:
            return "Nada encontrado na memória para essa consulta."
        return "\n\n".join(
            f"[{m['categoria']}] {m['titulo']} ({time.strftime('%d/%m/%Y', time.localtime(m['ts']))})\n{m['conteudo'][:900]}"
            for m in achados
        )

    # ------------------------------------------------------------------ tarefas
    @cat.ferramenta(
        "tarefa_criar",
        "Coloca uma nova tarefa na fila da empresa. Cada tarefa deve ter um objetivo único, concreto e "
        "verificável, que caiba em uma sessão de trabalho.",
        titulo=P("string", "Título curto que começa com um verbo."),
        descricao=P("string", "O que fazer, com contexto suficiente para executar sem outras informações, e o critério de pronto."),
        area=P("string", "Área responsável.", enum=AREAS),
        prioridade=P("integer", "De 1 (urgente) a 5 (pode esperar). Padrão 3.", obrigatorio=False),
        adiar_minutos=P("integer", "Só começar depois de tantos minutos (padrão 0).", obrigatorio=False),
    )
    def tarefa_criar(titulo: str, descricao: str, area: str, prioridade: int = 3, adiar_minutos: int = 0) -> str:
        if area not in AREAS:
            area = "operacoes"
        if banco.existe_tarefa_aberta(titulo):
            return "Já existe uma tarefa aberta com esse título. Não foi criada outra."
        if banco.contar_tarefas_abertas("trabalho") >= amb.cfg.max_tarefas_abertas:
            return (
                "NEGADO: a fila já está cheia. Conclua ou cancele tarefas existentes antes de criar novas "
                "(ative o grupo 'gestao' para usar tarefa_listar e tarefa_cancelar)."
            )
        atual = amb.tarefa_atual or {}
        origem = "planejamento" if atual.get("tipo") == "planejamento" else "agente"
        novo_id = banco.criar_tarefa(titulo, descricao, area, prioridade, origem=origem, adiar_minutos=adiar_minutos)
        amb.registro.evento("plano", f"Nova tarefa #{novo_id}: {titulo}", descricao, tarefa_id=atual.get("id"))
        return f"Tarefa #{novo_id} criada."

    @cat.ferramenta(
        "tarefa_listar",
        "Mostra a fila de tarefas da empresa.",
        _grupo="gestao",
        situacao=P(
            "string",
            "Filtro (padrão: abertas).",
            obrigatorio=False,
            enum=["abertas", "concluida", "falhou", "cancelada"],
        ),
    )
    def tarefa_listar(situacao: str = "abertas") -> str:
        tarefas = banco.tarefas_abertas() if situacao == "abertas" else banco.tarefas(situacao, 25)
        tarefas = [t for t in tarefas if t["tipo"] == "trabalho"]
        if not tarefas:
            return "Nenhuma tarefa nessa situação."
        linhas = []
        for t in tarefas:
            extra = f" resultado: {t['resultado'][:160]}" if t["resultado"] else ""
            linhas.append(f"#{t['id']} [{t['area']}, prioridade {t['prioridade']}, {t['status']}] {t['titulo']}{extra}")
        return "\n".join(linhas)

    @cat.ferramenta(
        "tarefa_cancelar",
        "Cancela uma tarefa aberta que deixou de fazer sentido.",
        _grupo="gestao",
        id=P("integer", "Número da tarefa."),
        motivo=P("string", "Por que está sendo cancelada."),
    )
    def tarefa_cancelar(id: int, motivo: str) -> str:
        tarefa = banco.tarefa(id)
        if not tarefa or tarefa["status"] != "pendente":
            return "ERRO: só é possível cancelar tarefas pendentes existentes."
        banco.atualizar_tarefa(id, status="cancelada", resultado=f"Cancelada: {motivo}", concluido_em=time.time())
        amb.registro.evento("plano", f"Tarefa #{id} cancelada: {tarefa['titulo']}", motivo)
        return f"Tarefa #{id} cancelada."

    # ------------------------------------------------------------------ empresa
    @cat.ferramenta(
        "empresa_atualizar",
        "Registra ou altera um dado oficial da empresa. Campos: nome, missao, proposta_de_valor, publico_alvo, "
        "produto, modelo_de_receita, estrategia, fase, site, canais. Fases válidas: descoberta, validacao, "
        "construcao, lancamento, operacao.",
        _grupo="gestao",
        campo=P("string", "Campo a alterar.", enum=CAMPOS_EMPRESA),
        valor=P("string", "Novo valor."),
    )
    def empresa_atualizar(campo: str, valor: str) -> str:
        campo = campo.strip().lower()
        if campo not in CAMPOS_EMPRESA:
            return f"ERRO: campo inválido. Use um destes: {', '.join(CAMPOS_EMPRESA)}."
        valor = valor.strip()
        if campo == "fase":
            valor = valor.lower()
            if valor not in FASES:
                return f"ERRO: fase inválida. Use uma destas: {', '.join(FASES)}."
        banco.definir(campo, valor)
        amb.registro.evento("decisao", f"Empresa: {campo} definido", valor, tarefa_id=(amb.tarefa_atual or {}).get("id"))
        return f"Campo '{campo}' atualizado."

    @cat.ferramenta(
        "decisao_registrar",
        "Registra uma decisão importante da empresa e a justificativa (fica no histórico e no resumo semanal).",
        _grupo="gestao",
        titulo=P("string", "A decisão, em uma frase."),
        justificativa=P("string", "Evidências e raciocínio que sustentam a decisão."),
    )
    def decisao_registrar(titulo: str, justificativa: str) -> str:
        banco.registrar_decisao(titulo, justificativa)
        amb.registro.evento("decisao", f"Decisão: {titulo}", justificativa, tarefa_id=(amb.tarefa_atual or {}).get("id"))
        return "Decisão registrada."

    @cat.ferramenta(
        "metrica_registrar",
        "Registra o valor atual de um indicador da empresa (visitas, cadastros, clientes, receita, avaliações).",
        _grupo="gestao",
        nome=P("string", "Nome do indicador."),
        valor=P("string", "Valor medido agora."),
    )
    def metrica_registrar(nome: str, valor: str) -> str:
        banco.registrar_metrica(nome, valor)
        amb.registro.evento("metrica", f"Indicador {nome}: {valor}", tarefa_id=(amb.tarefa_atual or {}).get("id"))
        return "Indicador registrado."

    @cat.ferramenta(
        "bloqueio_relatar",
        "Avisa o dono, pelo painel, de algo que o agente não consegue resolver sozinho (por exemplo: verificação "
        "humana obrigatória, exigência de documento, serviço que só funciona pago). O trabalho não para: depois "
        "de relatar, siga por outro caminho.",
        titulo=P("string", "O impedimento, em uma frase."),
        detalhe=P("string", "O que foi tentado e o que o dono poderia fazer para destravar."),
    )
    def bloqueio_relatar(titulo: str, detalhe: str) -> str:
        banco.registrar_bloqueio(titulo, detalhe)
        amb.registro.evento(
            "bloqueio", f"Impedimento: {titulo}", detalhe, nivel="aviso", tarefa_id=(amb.tarefa_atual or {}).get("id")
        )
        return "Impedimento registrado no painel. Continue por outro caminho; não espere resposta."
