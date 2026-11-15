"""Pacote padrão: habilidades e extensões recomendadas, instaladas sozinhas na primeira partida.

O catálogo fica em ``empresa_auto/catalogo``. Cada item foi conferido na origem
(repositório, pacote e licença). O agente continua livre para instalar ou criar
outras habilidades e extensões por conta própria; este pacote é só o ponto de
partida.

A instalação depende de internet e de git. Se falhar, o agente segue
trabalhando e tenta de novo mais tarde.
"""

from __future__ import annotations

import time

from .ferramentas.base import Ambiente
from .ferramentas.extensoes import carregar_catalogo as catalogo_de_extensoes
from .ferramentas.habilidades import carregar_catalogo as catalogo_de_habilidades

CHAVE_ESTADO = "pacote_padrao"
INTERVALO_NOVA_TENTATIVA = 6 * 3600


def situacao(amb: Ambiente) -> dict:
    return dict(amb.banco.obter(CHAVE_ESTADO, {}) or {})


def pendente(amb: Ambiente) -> bool:
    """Indica se ainda falta instalar algo do pacote padrão (e se já é hora de tentar de novo)."""
    if not amb.cfg.pacote_padrao:
        return False
    estado = situacao(amb)
    catalogo = catalogo_de_habilidades()
    if estado.get("versao") == catalogo.get("versao") and estado.get("completo"):
        return False
    return time.time() - float(estado.get("ultima_tentativa", 0)) >= INTERVALO_NOVA_TENTATIVA


def provisionar(amb: Ambiente) -> dict:
    """Instala o que faltar do pacote padrão. Nunca levanta exceção."""
    catalogo = catalogo_de_habilidades()
    estado = situacao(amb)
    if estado.get("versao") != catalogo.get("versao"):
        estado = {"versao": catalogo.get("versao"), "fontes": {}, "extensoes": []}
    fontes_feitas: dict = dict(estado.get("fontes") or {})
    erros: list[str] = []
    novas: list[str] = []

    pendentes = [f for f in catalogo.get("fontes", []) if f["origem"] not in fontes_feitas]
    if pendentes:
        amb.registro.sistema(
            "Instalando o pacote padrão de habilidades da comunidade",
            "\n".join(f"{f['origem']} ({len(f.get('itens', []))} habilidades)" for f in pendentes),
        )
    for fonte in pendentes:
        try:
            instaladas, erro = amb.habilidades.instalar_fonte_do_catalogo(fonte)
        except Exception as falha:  # uma fonte com problema não impede as outras
            instaladas, erro = [], str(falha)
        if instaladas:
            fontes_feitas[fonte["origem"]] = instaladas
            novas.extend(instaladas)
        if erro:
            erros.append(erro)
            if not instaladas and ("clonar" in erro or "git" in erro or "tempo esgotado" in erro):
                break  # sem rede ou sem git: não adianta insistir nas demais agora

    # Extensões que não pedem credencial ficam registradas e só iniciam quando forem ativadas.
    extensoes_feitas = list(estado.get("extensoes") or [])
    for entrada in catalogo_de_extensoes():
        exige_credencial = entrada.get("credencial") and not entrada["credencial"].get("opcional")
        if not entrada.get("padrao") or exige_credencial or entrada.get("parametros"):
            continue
        if entrada["nome"] in extensoes_feitas or amb.extensoes.instalada(entrada["nome"]):
            continue
        try:
            resposta = amb.extensoes.instalar_do_catalogo(entrada["nome"], conectar=False)
        except Exception as falha:
            resposta = f"ERRO: {falha}"
        if resposta.startswith("ERRO"):
            erros.append(f"extensão {entrada['nome']}: {resposta}")
        else:
            extensoes_feitas.append(entrada["nome"])

    completo = len(fontes_feitas) == len(catalogo.get("fontes", []))
    estado.update(
        fontes=fontes_feitas, extensoes=extensoes_feitas, completo=completo, ultima_tentativa=time.time()
    )
    amb.banco.definir(CHAVE_ESTADO, estado)
    if novas:
        amb.registro.evento(
            "habilidade", f"Pacote padrão: {len(novas)} habilidades da comunidade instaladas", ", ".join(novas)
        )
    if erros:
        amb.registro.evento(
            "sistema",
            "Parte do pacote padrão não pôde ser instalada agora; nova tentativa em algumas horas",
            "\n".join(erros),
            nivel="aviso",
        )
    return {"novas": novas, "extensoes": extensoes_feitas, "erros": erros, "completo": completo}
