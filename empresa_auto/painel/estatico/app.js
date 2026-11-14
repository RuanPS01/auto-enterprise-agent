(() => {
  'use strict';

  // Todo texto dinâmico entra na página por textContent: o registro pode conter
  // trechos de sites visitados pelo agente e nunca deve ser interpretado como HTML.
  const $ = (id) => document.getElementById(id);

  function el(tag, opcoes = {}, filhos = []) {
    const no = document.createElement(tag);
    if (opcoes.classe) no.className = opcoes.classe;
    if (opcoes.texto !== undefined) no.textContent = opcoes.texto;
    for (const [nome, valor] of Object.entries(opcoes.attrs || {})) no.setAttribute(nome, valor);
    for (const filho of [].concat(filhos)) if (filho) no.append(filho);
    return no;
  }

  async function api(caminho, opcoes = {}) {
    const resposta = await fetch(caminho, {
      method: opcoes.metodo || 'GET',
      headers: { 'Content-Type': 'application/json', 'X-Requested-With': 'empresa-auto' },
      body: opcoes.corpo ? JSON.stringify(opcoes.corpo) : undefined,
      credentials: 'same-origin',
    });
    if (resposta.status === 401) { location.reload(); throw new Error('Sessão expirada.'); }
    let dados = null;
    try { dados = await resposta.json(); } catch (_) { /* resposta sem corpo */ }
    if (!resposta.ok) throw new Error((dados && (dados.detail || dados.erro)) || `Erro ${resposta.status}`);
    return dados;
  }

  // ---------- formatação ----------
  const hora = (ts) => new Date(ts * 1000).toLocaleTimeString('pt-BR', { hour: '2-digit', minute: '2-digit', second: '2-digit' });
  const dataHora = (ts) => new Date(ts * 1000).toLocaleString('pt-BR', { day: '2-digit', month: '2-digit', hour: '2-digit', minute: '2-digit' });
  const dia = (ts) => new Date(ts * 1000).toLocaleDateString('pt-BR', { day: '2-digit', month: '2-digit' });
  const moeda = (v) => Number(v || 0).toLocaleString('pt-BR', { style: 'currency', currency: 'BRL' });

  function duracao(segundos) {
    const s = Math.max(0, Math.round(segundos));
    if (s < 60) return `${s} s`;
    if (s < 3600) return `${Math.floor(s / 60)} min`;
    if (s < 86400) return `${Math.floor(s / 3600)} h ${Math.floor((s % 3600) / 60)} min`;
    return `${Math.floor(s / 86400)} d ${Math.floor((s % 86400) / 3600)} h`;
  }

  function intervalo(minutos) {
    if (minutos % 1440 === 0) return minutos === 1440 ? 'todo dia' : `a cada ${minutos / 1440} dias`;
    if (minutos % 60 === 0) return minutos === 60 ? 'a cada hora' : `a cada ${minutos / 60} horas`;
    return `a cada ${minutos} minutos`;
  }

  const cache = {};
  function mudou(chave, dados) {
    const texto = JSON.stringify(dados);
    if (cache[chave] === texto) return false;
    cache[chave] = texto;
    return true;
  }

  // ---------- registro em tempo real ----------
  const ROTULOS_TIPO = {
    sistema: 'sistema', tarefa: 'tarefa', plano: 'plano', ferramenta: 'ação', resultado: 'resultado',
    pensamento: 'raciocínio', erro: 'erro', decisao: 'decisão', bloqueio: 'impedimento', pagamento: 'pagamento',
    conta: 'conta', servico: 'serviço', automacao: 'automação', habilidade: 'habilidade', extensao: 'extensão',
    memoria: 'memória', metrica: 'indicador', comunicacao: 'mensagem', resumo: 'resumo',
  };
  const MAX_LINHAS = 2000;
  const registro = $('registro');
  let filtro = 'tudo';
  let ultimoEvento = 0;
  let totalEventos = 0;

  function categoria(evento) {
    if (evento.tipo === 'ferramenta' || evento.tipo === 'resultado') return 'acoes';
    if (evento.tipo === 'pensamento') return 'raciocinio';
    return 'marcos';
  }

  function visivel(linha) {
    if (filtro === 'tudo') return true;
    if (filtro === 'erros') return linha.dataset.nivel === 'erro' || linha.dataset.nivel === 'aviso';
    return linha.dataset.categoria === filtro;
  }

  function adicionarEvento(evento) {
    if (evento.id <= ultimoEvento) return;
    ultimoEvento = evento.id;
    totalEventos += 1;
    const vazio = registro.querySelector('.registro-vazio');
    if (vazio) vazio.remove();

    const linha = el('div', { classe: `linha tipo-${evento.tipo} nivel-${evento.nivel}` });
    linha.dataset.categoria = categoria(evento);
    linha.dataset.nivel = evento.nivel;
    const resumo = el('div', { classe: 'linha-resumo' }, [
      el('span', { classe: 'linha-hora', texto: hora(evento.ts) }),
      el('span', { classe: 'linha-tipo', texto: ROTULOS_TIPO[evento.tipo] || evento.tipo }),
      el('span', { classe: 'linha-titulo', texto: evento.titulo }),
    ]);
    linha.append(resumo);
    if (evento.detalhe) {
      linha.append(el('pre', { classe: 'linha-detalhe', texto: evento.detalhe }));
      resumo.title = 'Clique para ver os detalhes';
      resumo.addEventListener('click', () => linha.classList.toggle('aberta'));
    }
    linha.hidden = !visivel(linha);
    registro.append(linha);
    while (registro.children.length > MAX_LINHAS) registro.firstElementChild.remove();
    if ($('rolagem-automatica').checked) registro.scrollTop = registro.scrollHeight;
    $('registro-contagem').textContent = `${totalEventos} eventos`;
  }

  function aplicarFiltro() {
    for (const linha of registro.children) if (linha.classList.contains('linha')) linha.hidden = !visivel(linha);
    if ($('rolagem-automatica').checked) registro.scrollTop = registro.scrollHeight;
  }

  $('filtros').addEventListener('click', (ev) => {
    const botao = ev.target.closest('[data-filtro]');
    if (!botao) return;
    filtro = botao.dataset.filtro;
    for (const b of $('filtros').children) b.classList.toggle('ativo', b === botao);
    aplicarFiltro();
  });

  registro.addEventListener('scroll', () => {
    const noFim = registro.scrollHeight - registro.scrollTop - registro.clientHeight < 40;
    $('rolagem-automatica').checked = noFim;
  });

  async function iniciarRegistro() {
    try {
      const dados = await api('/api/eventos?limite=400');
      if (!dados.eventos.length) registro.append(el('div', { classe: 'registro-vazio', texto: 'Nenhum evento ainda.' }));
      dados.eventos.forEach(adicionarEvento);
    } catch (_) { /* a conexão em tempo real tenta de novo */ }
    const fonte = new EventSource(`/api/fluxo?depois=${ultimoEvento}`);
    fonte.onmessage = (mensagem) => {
      try { adicionarEvento(JSON.parse(mensagem.data)); } catch (_) { /* evento malformado */ }
    };
  }

  // ---------- estado geral ----------
  const ROTULOS_ESTADO = {
    iniciando: 'Iniciando', aguardando_inicio: 'Aguardando a partida', trabalhando: 'Trabalhando',
    planejando: 'Planejando os próximos passos', ocioso: 'Aguardando a próxima tarefa', pausado: 'Pausado',
    aguardando_llm: 'Modelo local indisponível', baixando_modelo: 'Baixando o modelo local',
    resumindo: 'Escrevendo o resumo da semana', desligado: 'Desligado',
  };
  const FASES = [['descoberta', 'Descoberta'], ['validacao', 'Validação'], ['construcao', 'Construção'], ['lancamento', 'Lançamento'], ['operacao', 'Operação']];
  const ROTULOS_AREA = {
    pesquisa: 'pesquisa', produto: 'produto', engenharia: 'engenharia', marketing: 'marketing',
    atendimento: 'atendimento', operacoes: 'operações', financeiro: 'financeiro',
  };
  let estado = null;
  let aba = 'fila';
  let conectado = true;

  function renderTopo(e) {
    const seloLlm = $('selo-llm');
    seloLlm.textContent = e.llm.modelo;
    seloLlm.className = 'selo' + (e.llm.ok === true ? ' ok' : e.llm.ok === false ? ' erro' : '');
    seloLlm.title = e.llm.ok === false ? e.llm.erro : `Modelo local em ${e.llm.url}`;

    const selo = $('selo-estado');
    const atividade = e.atividade.estado;
    let texto = 'em operação', classe = 'selo ok';
    if (!e.iniciada) { texto = 'aguardando a partida'; classe = 'selo'; }
    else if (e.pausado) { texto = 'pausado'; classe = 'selo aviso'; }
    else if (atividade === 'aguardando_llm') { texto = 'modelo indisponível'; classe = 'selo erro'; }
    else if (atividade === 'baixando_modelo') { texto = 'baixando modelo'; classe = 'selo aviso ativo'; }
    else if (atividade === 'trabalhando' || atividade === 'planejando' || atividade === 'resumindo') classe = 'selo ok ativo';
    selo.textContent = texto;
    selo.className = classe;

    const pausa = $('botao-pausa');
    pausa.hidden = !e.iniciada;
    pausa.textContent = e.pausado ? 'Retomar' : 'Pausar';
    $('subtitulo').textContent = e.empresa.nome ? e.empresa.nome : 'Agente autônomo com modelo local';
  }

  function renderPartida(e) {
    const aviso = $('aviso-llm-partida');
    if (e.llm.ok === false) {
      aviso.textContent = `Atenção: o modelo local não está respondendo (${e.llm.erro}). Você já pode dar a partida: o agente começa assim que o modelo estiver disponível.`;
    } else if (e.llm.ok === true) {
      aviso.textContent = `Modelo local pronto: ${e.llm.modelo} (${e.llm.provedor}).`;
    } else {
      aviso.textContent = 'Verificando o modelo local...';
    }
  }

  function renderAgora(e) {
    const a = e.atividade;
    $('agora-estado').textContent = ROTULOS_ESTADO[a.estado] || a.estado;
    $('agora-tempo').textContent = `há ${duracao(e.agora - a.desde)}`;
    const tarefa = $('agora-tarefa');
    const detalhes = $('agora-detalhes');
    detalhes.replaceChildren();
    const barra = $('agora-barra');
    if (a.tarefa) {
      tarefa.textContent = a.tarefa.tipo === 'planejamento' ? 'Revisando a situação e definindo novas tarefas' : a.tarefa.titulo;
      const partes = [];
      if (a.tarefa.tipo !== 'planejamento') partes.push(`tarefa #${a.tarefa.id}`, `área: ${ROTULOS_AREA[a.tarefa.area] || a.tarefa.area}`);
      if (a.max_passos) partes.push(`passo ${a.passo} de ${a.max_passos}`);
      detalhes.append(partes.join(' · '));
      if (a.ferramenta) detalhes.append(' · ', el('code', { texto: a.ferramenta }));
      barra.hidden = !a.max_passos;
      $('agora-barra-valor').style.width = a.max_passos ? `${Math.min(100, (a.passo / a.max_passos) * 100)}%` : '0';
    } else {
      tarefa.textContent = a.detalhe || '';
      barra.hidden = true;
    }
  }

  function renderEmpresa(e) {
    if (!mudou('empresa', e.empresa)) return;
    const emp = e.empresa;
    $('empresa-nome').textContent = emp.nome || (emp.modo === 'auto' ? 'Negócio ainda em escolha' : 'Empresa ainda sem nome');
    const indice = Math.max(0, FASES.findIndex(([chave]) => chave === emp.fase));
    $('fases').replaceChildren(...FASES.map(([, rotulo], i) =>
      el('li', { classe: i < indice ? 'feita' : i === indice ? 'atual' : '', texto: rotulo })));
    const campos = [
      ['Ideia do dono', emp.ideia], ['Missão', emp.missao], ['Proposta de valor', emp.proposta_de_valor],
      ['Público-alvo', emp.publico_alvo], ['Produto', emp.produto], ['Modelo de receita', emp.modelo_de_receita],
      ['Estratégia', emp.estrategia], ['Site', emp.site], ['Canais', emp.canais],
      ['Em operação desde', emp.iniciada_em ? dataHora(emp.iniciada_em) : ''],
    ].filter(([, valor]) => valor);
    $('empresa-dados').replaceChildren(...campos.flatMap(([rotulo, valor]) =>
      [el('dt', { texto: rotulo }), el('dd', { texto: String(valor) })]));
  }

  function itemTarefa(t) {
    const etiquetas = [el('span', { texto: `#${t.id}` }), el('span', { classe: 'etiqueta', texto: ROTULOS_AREA[t.area] || t.area })];
    if (t.status === 'em_andamento') etiquetas.push(el('span', { classe: 'etiqueta andamento', texto: 'em andamento' }));
    if (t.status === 'concluida') etiquetas.push(el('span', { classe: 'etiqueta ok', texto: 'concluída' }));
    if (t.status === 'falhou') etiquetas.push(el('span', { classe: 'etiqueta falha', texto: 'falhou' }));
    if (t.status === 'cancelada') etiquetas.push(el('span', { classe: 'etiqueta', texto: 'cancelada' }));
    if (t.status === 'pendente') etiquetas.push(el('span', { texto: `prioridade ${t.prioridade}` }));
    if (t.status === 'pendente' && t.nao_antes_de > estado.agora) etiquetas.push(el('span', { texto: `a partir de ${dataHora(t.nao_antes_de)}` }));
    if (t.tentativas > 1) etiquetas.push(el('span', { texto: `tentativa ${t.tentativas}` }));
    if (t.concluido_em) etiquetas.push(el('span', { texto: dataHora(t.concluido_em) }));
    const texto = t.resultado || t.descricao;
    const detalhe = el('details', {}, [el('summary', { texto: t.resultado ? 'Ver resultado' : 'Ver descrição' }), el('div', { classe: 'item-texto', texto })]);
    detalhe.style.borderTop = '0';
    detalhe.style.paddingTop = '4px';
    return el('div', { classe: 'item' }, [
      el('div', { classe: 'item-titulo', texto: t.titulo }),
      el('div', { classe: 'item-meta' }, etiquetas),
      texto ? detalhe : null,
    ]);
  }

  function renderTarefas(e) {
    const c = e.contagem;
    $('tarefas-contagem').textContent = `${c.pendente + c.em_andamento} na fila · ${c.concluida} concluídas · ${c.falhou} falharam`;
    const lista = aba === 'fila' ? e.tarefas_abertas : e.tarefas_finalizadas;
    if (!mudou('tarefas', [aba, lista])) return;
    const abertos = new Set([...$('tarefas').querySelectorAll('details[open]')].map((d) => d.closest('.item').dataset.id));
    const nos = lista.map((t) => {
      const no = itemTarefa(t);
      no.dataset.id = String(t.id);
      if (abertos.has(String(t.id))) no.querySelector('details')?.setAttribute('open', '');
      return no;
    });
    $('tarefas').replaceChildren(...(nos.length ? nos : [el('div', { classe: 'vazio', texto: aba === 'fila' ? 'Nenhuma tarefa na fila.' : 'Nenhuma tarefa finalizada ainda.' })]));
  }

  $('cartao-tarefas').addEventListener('click', (ev) => {
    const botao = ev.target.closest('[data-aba]');
    if (!botao) return;
    aba = botao.dataset.aba;
    for (const b of botao.parentElement.children) b.classList.toggle('ativo', b === botao);
    if (estado) renderTarefas(estado);
  });

  function renderPendencias(e) {
    $('cartao-pendencias').hidden = e.bloqueios.length === 0;
    if (!mudou('bloqueios', e.bloqueios)) return;
    $('pendencias').replaceChildren(...e.bloqueios.map((b) => {
      const botao = el('button', { classe: 'botao secundario pequeno', texto: 'Marcar como resolvido' });
      botao.addEventListener('click', async () => {
        botao.disabled = true;
        try { await api(`/api/bloqueios/${b.id}/resolver`, { metodo: 'POST' }); await atualizarEstado(); } catch (_) { botao.disabled = false; }
      });
      return el('div', { classe: 'item' }, [
        el('div', { classe: 'item-titulo', texto: b.titulo }),
        el('div', { classe: 'item-meta' }, [el('span', { texto: dataHora(b.ts) })]),
        b.detalhe ? el('div', { classe: 'item-texto', texto: b.detalhe }) : null,
        el('div', { classe: 'acoes-item' }, [botao]),
      ]);
    }));
  }

  function grupoRecursos(titulo, itens, vazio) {
    const lista = itens.length
      ? el('ul', {}, itens.map((texto) => el('li', { texto })))
      : el('p', { classe: 'vazio', texto: vazio });
    const no = el('details', {}, [el('summary', {}, [titulo, el('span', { classe: 'discreto', texto: String(itens.length) })]), lista]);
    no.dataset.titulo = titulo;
    return no;
  }

  function renderRecursos(e) {
    const dados = [e.contas, e.servicos, e.automacoes, e.habilidades, e.extensoes, e.indicadores, e.decisoes, e.memorias];
    if (!mudou('recursos', dados)) return;
    const abertos = new Set([...$('recursos').querySelectorAll('details[open]')].map((d) => d.dataset.titulo));
    const grupos = [
      grupoRecursos('Contas no cofre', e.contas.map((c) => `${c.servico}: ${c.usuario}${c.origem === 'dono' ? ' (fornecida por você)' : ''}`), 'O agente ainda não criou contas.'),
      grupoRecursos('Serviços no ar', e.servicos.map((s) => `${s.nome}: ${s.rodando ? 'rodando' : 'parado'}`), 'Nenhum serviço em execução.'),
      grupoRecursos('Automações', e.automacoes.map((a) => `${a.titulo} (${intervalo(a.intervalo_min)})`), 'Nenhuma rotina recorrente.'),
      grupoRecursos('Decisões', e.decisoes.map((d) => `${dia(d.ts)}: ${d.titulo}`), 'Nenhuma decisão registrada.'),
      grupoRecursos('Indicadores', e.indicadores.map((m) => `${m.nome}: ${m.valor}`), 'Nenhum indicador medido.'),
      grupoRecursos('Habilidades', e.habilidades.map((h) => `${h.nome}${h.origem === 'instalada' ? ' (instalada pelo agente)' : ''}`), 'Nenhuma habilidade.'),
      grupoRecursos('Extensões', e.extensoes.map((x) => `${x.nome}: ${x.ferramentas} ferramentas`), 'Nenhuma extensão instalada.'),
    ];
    grupos.forEach((g) => { if (abertos.has(g.dataset.titulo)) g.setAttribute('open', ''); });
    $('recursos').replaceChildren(...grupos, el('p', { classe: 'discreto', texto: `${e.memorias} conhecimentos guardados na memória permanente.` }));
  }

  function renderPagamento(e) {
    if (!mudou('pagamento', [e.cartao, e.gastos])) return;
    const alvo = $('pagamento-situacao');
    if (!e.cartao.configurado) {
      alvo.replaceChildren(el('p', { classe: 'vazio', texto: 'Nenhum cartão cadastrado. O agente usa apenas recursos gratuitos.' }));
      $('pagamento-form-envolve').hidden = false;
      return;
    }
    const remover = el('button', { classe: 'botao secundario pequeno', texto: 'Remover cartão' });
    remover.addEventListener('click', async () => {
      remover.disabled = true;
      try { await api('/api/cartao', { metodo: 'DELETE' }); await atualizarEstado(); } catch (_) { remover.disabled = false; }
    });
    const nos = [el('div', { classe: 'situacao-cartao' }, [
      el('span', { texto: `Cartão final ${e.cartao.final} · limite de ${moeda(e.cartao.limite_mensal)} por mês · usado neste mês: ${moeda(e.cartao.gasto_mes)}` }),
      remover,
    ])];
    if (e.gastos.length) {
      nos.push(el('div', { classe: 'bloco-lista' }, [
        el('h3', { texto: 'Usos recentes' }),
        el('ul', {}, e.gastos.map((g) => el('li', { texto: `${dia(g.ts)}: ${moeda(g.valor)} (${g.motivo})` }))),
      ]));
    }
    alvo.replaceChildren(...nos);
    $('pagamento-form-envolve').hidden = true;
  }

  let ultimaCaptura = null;
  function atualizarCaptura(e) {
    if (!e.captura) { $('visao').hidden = true; return; }
    if (e.captura === ultimaCaptura) return;
    ultimaCaptura = e.captura;
    const nova = new Image();
    nova.onload = () => { $('visao-imagem').src = nova.src; $('visao').hidden = false; };
    nova.src = `/api/captura?t=${e.captura}`;
  }

  async function atualizarEstado() {
    try {
      estado = await api('/api/estado');
      conectado = true;
    } catch (_) {
      if (conectado) { $('selo-estado').textContent = 'sem conexão com o agente'; $('selo-estado').className = 'selo erro'; }
      conectado = false;
      return;
    }
    renderTopo(estado);
    $('tela-partida').hidden = estado.iniciada;
    $('tela-painel').hidden = !estado.iniciada;
    if (!estado.iniciada) { renderPartida(estado); return; }
    renderAgora(estado);
    renderEmpresa(estado);
    renderTarefas(estado);
    renderPendencias(estado);
    renderRecursos(estado);
    renderPagamento(estado);
    atualizarCaptura(estado);
  }

  // ---------- resumo semanal ----------
  let semanaEscolhida = null;

  function blocoLista(titulo, itens) {
    if (!itens.length) return null;
    return el('div', { classe: 'bloco-lista' }, [el('h3', { texto: titulo }), el('ul', {}, itens.map((texto) => el('li', { texto })))]);
  }

  async function atualizarResumo() {
    if (!estado || !estado.iniciada) return;
    let r;
    try { r = await api('/api/resumo' + (semanaEscolhida ? `?semana=${encodeURIComponent(semanaEscolhida)}` : '')); } catch (_) { return; }
    if (!mudou('resumo', r)) return;
    const seletor = $('resumo-semana');
    seletor.replaceChildren(...r.semanas.map((chave) => {
      const [ano, mes, diaMes] = chave.split('-');
      const opcao = el('option', { texto: `Semana de ${diaMes}/${mes}/${ano}`, attrs: { value: chave } });
      opcao.selected = chave === r.semana;
      return opcao;
    }));
    const n = r.numeros;
    const numero = (valor, rotulo) => el('div', { classe: 'numero' }, [el('div', { classe: 'numero-valor', texto: String(valor) }), el('div', { classe: 'numero-rotulo', texto: rotulo })]);
    $('resumo-numeros').replaceChildren(
      numero(n.tarefas_concluidas, 'tarefas concluídas'),
      numero(n.tarefas_falharam, 'tarefas que falharam'),
      numero(n.decisoes.length, 'decisões tomadas'),
      numero(moeda(n.gasto_total), 'gasto no cartão'),
    );
    const texto = $('resumo-texto');
    texto.textContent = r.texto || 'O texto do resumo é escrito pelo agente algumas vezes ao dia. Os números acima são atualizados em tempo real.';
    texto.classList.toggle('vazia', !r.texto);
    $('resumo-listas').replaceChildren(...[
      blocoLista('Concluído', n.concluidas.slice(-8).reverse().map((t) => t.titulo)),
      blocoLista('Decisões', n.decisoes.slice(0, 6).map((d) => d.titulo)),
      blocoLista('Impedimentos', n.impedimentos.slice(0, 6)),
      blocoLista('Contas e serviços', [...n.contas_criadas, ...n.servicos].slice(0, 8)),
    ].filter(Boolean));
    $('resumo-atualizado').textContent = r.atualizado_em ? `Texto atualizado em ${dataHora(r.atualizado_em)}` : '';
  }

  $('resumo-semana').addEventListener('change', (ev) => { semanaEscolhida = ev.target.value; atualizarResumo(); });

  // ---------- ações do dono ----------
  async function darPartida(modo, botao) {
    const erro = $('erro-partida');
    erro.hidden = true;
    const ideia = $('campo-ideia').value.trim();
    if (modo === 'ideia' && ideia.length < 10) {
      erro.textContent = 'Descreva a ideia da empresa com um pouco mais de detalhe.';
      erro.hidden = false;
      return;
    }
    botao.disabled = true;
    try {
      await api('/api/iniciar', { metodo: 'POST', corpo: { modo, ideia } });
      await atualizarEstado();
      atualizarResumo();
    } catch (falha) {
      erro.textContent = falha.message;
      erro.hidden = false;
    } finally {
      botao.disabled = false;
    }
  }
  $('botao-ideia').addEventListener('click', (ev) => darPartida('ideia', ev.currentTarget));
  $('botao-auto').addEventListener('click', (ev) => darPartida('auto', ev.currentTarget));

  $('botao-pausa').addEventListener('click', async (ev) => {
    const botao = ev.currentTarget; // depois de um await, ev.currentTarget passa a ser nulo
    botao.disabled = true;
    try { await api(estado && estado.pausado ? '/api/retomar' : '/api/pausar', { metodo: 'POST' }); await atualizarEstado(); } catch (_) { /* tenta na próxima atualização */ }
    botao.disabled = false;
  });

  function ligarFormulario(idForm, idErro, caminho, montar) {
    $(idForm).addEventListener('submit', async (ev) => {
      ev.preventDefault();
      const form = ev.currentTarget;
      const erro = $(idErro);
      erro.hidden = true;
      const botao = form.querySelector('button');
      botao.disabled = true;
      try {
        await api(caminho, { metodo: 'POST', corpo: montar(new FormData(form)) });
        form.reset();
        form.closest('details').removeAttribute('open');
        await atualizarEstado();
      } catch (falha) {
        erro.textContent = falha.message;
        erro.hidden = false;
      } finally {
        botao.disabled = false;
      }
    });
  }
  ligarFormulario('form-cartao', 'erro-cartao', '/api/cartao', (f) => ({
    numero: f.get('numero'), validade: f.get('validade'), cvv: f.get('cvv'), titular: f.get('titular') || '',
    limite_mensal: Number(f.get('limite_mensal')),
  }));
  ligarFormulario('form-conta', 'erro-conta', '/api/contas', (f) => ({
    servico: f.get('servico'), usuario: f.get('usuario'), senha: f.get('senha'), notas: f.get('notas') || '',
  }));

  // ---------- partida da página ----------
  (async () => {
    await atualizarEstado();
    await iniciarRegistro();
    atualizarResumo();
    setInterval(atualizarEstado, 3000);
    setInterval(atualizarResumo, 30000);
  })();
})();
