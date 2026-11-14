"""Cofre de credenciais.

Guarda contas, senhas, chaves de API e, opcionalmente, o cartão informado pelo
dono. O conteúdo fica cifrado em disco (Fernet, AES com autenticação).

A chave de cifra vem de uma destas fontes:

* variável de ambiente ``EA_SENHA_MESTRA`` (derivada com scrypt), ou
* arquivo ``chave_mestra.key`` criado automaticamente no diretório de dados,
  com permissão restrita ao usuário.

Como o agente precisa religar sozinho depois de uma queda de energia, o padrão
é o arquivo de chave. Isso protege contra cópias acidentais do cofre (backups,
sincronização), mas não contra alguém com acesso total à máquina.
"""

from __future__ import annotations

import base64
import json
import os
import secrets
import string
import threading
import time
from pathlib import Path

from cryptography.fernet import Fernet, InvalidToken
from cryptography.hazmat.primitives.kdf.scrypt import Scrypt


class ErroCofre(Exception):
    pass


def gerar_senha(tamanho: int = 20) -> str:
    """Gera uma senha forte com letras, números e símbolos aceitos pela maioria dos sites."""
    tamanho = max(12, min(64, int(tamanho)))
    simbolos = "!@#$%*-_=+?"
    alfabeto = string.ascii_letters + string.digits + simbolos
    while True:
        senha = "".join(secrets.choice(alfabeto) for _ in range(tamanho))
        if (
            any(c.islower() for c in senha)
            and any(c.isupper() for c in senha)
            and any(c.isdigit() for c in senha)
            and any(c in simbolos for c in senha)
        ):
            return senha


def _restringir(caminho: Path) -> None:
    try:
        os.chmod(caminho, 0o600)
    except OSError:
        pass  # no Windows as permissões seguem a ACL da pasta do usuário


class Cofre:
    def __init__(self, dir_dados: Path, senha_mestra: str | None = None):
        self.dir_dados = Path(dir_dados)
        self.arquivo = self.dir_dados / "cofre.bin"
        self._trava = threading.RLock()
        senha = senha_mestra if senha_mestra is not None else os.environ.get("EA_SENHA_MESTRA")
        self._fernet = Fernet(self._chave_por_senha(senha) if senha else self._chave_de_arquivo())
        self._temporarios: set[str] = set()
        self._dados = self._carregar()

    # ------------------------------------------------------------------ chaves
    def _chave_de_arquivo(self) -> bytes:
        caminho = self.dir_dados / "chave_mestra.key"
        if caminho.exists():
            return caminho.read_bytes().strip()
        chave = Fernet.generate_key()
        caminho.write_bytes(chave)
        _restringir(caminho)
        return chave

    def _chave_por_senha(self, senha: str) -> bytes:
        caminho_sal = self.dir_dados / "cofre.sal"
        if caminho_sal.exists():
            sal = caminho_sal.read_bytes()
        else:
            sal = secrets.token_bytes(16)
            caminho_sal.write_bytes(sal)
            _restringir(caminho_sal)
        derivada = Scrypt(salt=sal, length=32, n=2**15, r=8, p=1).derive(senha.encode("utf-8"))
        return base64.urlsafe_b64encode(derivada)

    # ------------------------------------------------------------------ disco
    def _carregar(self) -> dict:
        if not self.arquivo.exists():
            return {"credenciais": {}, "cartao": None, "dados": {}}
        try:
            claro = self._fernet.decrypt(self.arquivo.read_bytes())
        except InvalidToken as erro:
            raise ErroCofre(
                "Não foi possível abrir o cofre: a chave mestra não confere com o arquivo cofre.bin."
            ) from erro
        dados = json.loads(claro.decode("utf-8"))
        dados.setdefault("credenciais", {})
        dados.setdefault("cartao", None)
        dados.setdefault("dados", {})
        return dados

    def _salvar(self) -> None:
        cifrado = self._fernet.encrypt(json.dumps(self._dados, ensure_ascii=False).encode("utf-8"))
        temporario = self.arquivo.with_suffix(".tmp")
        temporario.write_bytes(cifrado)
        _restringir(temporario)
        os.replace(temporario, self.arquivo)

    # ------------------------------------------------------------------ credenciais
    def salvar_credencial(
        self,
        servico: str,
        usuario: str,
        senha: str,
        url: str = "",
        notas: str = "",
        extras: dict | None = None,
        origem: str = "agente",
    ) -> None:
        chave = servico.strip().lower()
        if not chave:
            raise ErroCofre("Informe o nome do serviço.")
        with self._trava:
            anterior = self._dados["credenciais"].get(chave, {})
            self._dados["credenciais"][chave] = {
                "servico": chave,
                "usuario": usuario,
                "senha": senha,
                "url": url or anterior.get("url", ""),
                "notas": notas or anterior.get("notas", ""),
                "extras": {**anterior.get("extras", {}), **(extras or {})},
                "origem": origem,
                "atualizado_em": time.time(),
            }
            self._salvar()

    def obter_credencial(self, servico: str) -> dict | None:
        with self._trava:
            item = self._dados["credenciais"].get(servico.strip().lower())
            return dict(item) if item else None

    def listar(self) -> list[dict]:
        """Lista as contas guardadas, sem revelar senhas."""
        with self._trava:
            return [
                {
                    "servico": item["servico"],
                    "usuario": item.get("usuario", ""),
                    "url": item.get("url", ""),
                    "notas": item.get("notas", ""),
                    "origem": item.get("origem", "agente"),
                    "atualizado_em": item.get("atualizado_em", 0),
                }
                for item in sorted(self._dados["credenciais"].values(), key=lambda i: i["servico"])
            ]

    def remover_credencial(self, servico: str) -> bool:
        with self._trava:
            removido = self._dados["credenciais"].pop(servico.strip().lower(), None)
            if removido is not None:
                self._salvar()
            return removido is not None

    # ------------------------------------------------------------------ dados genéricos
    def guardar(self, chave: str, valor: object) -> None:
        """Guarda cifrado qualquer dado sensível (por exemplo, configurações de extensões)."""
        with self._trava:
            self._dados["dados"][chave] = valor
            self._salvar()

    def ler(self, chave: str, padrao: object = None) -> object:
        with self._trava:
            return self._dados["dados"].get(chave, padrao)

    # ------------------------------------------------------------------ cartão
    def definir_cartao(self, numero: str, validade: str, cvv: str, titular: str, limite_mensal: float) -> None:
        digitos = "".join(c for c in numero if c.isdigit())
        if not 12 <= len(digitos) <= 19:
            raise ErroCofre("Número de cartão inválido.")
        if not cvv.strip().isdigit() or not 3 <= len(cvv.strip()) <= 4:
            raise ErroCofre("Código de segurança inválido.")
        if not validade.strip():
            raise ErroCofre("Informe a validade do cartão.")
        if float(limite_mensal) <= 0:
            raise ErroCofre("Informe um limite mensal maior que zero.")
        with self._trava:
            self._dados["cartao"] = {
                "numero": digitos,
                "validade": validade.strip(),
                "cvv": cvv.strip(),
                "titular": titular.strip(),
                "limite_mensal": float(limite_mensal),
                "definido_em": time.time(),
            }
            self._salvar()

    def obter_cartao(self) -> dict | None:
        with self._trava:
            cartao = self._dados.get("cartao")
            return dict(cartao) if cartao else None

    def resumo_cartao(self) -> dict:
        cartao = self.obter_cartao()
        if not cartao:
            return {"configurado": False}
        return {
            "configurado": True,
            "final": cartao["numero"][-4:],
            "titular": cartao.get("titular", ""),
            "limite_mensal": cartao.get("limite_mensal", 0),
        }

    def campos_cartao(self) -> dict[str, str]:
        """Campos do cartão usados na substituição dos marcadores ``{{cartao:campo}}``."""
        cartao = self.obter_cartao()
        if not cartao:
            return {}
        partes = [p for p in "".join(c if c.isdigit() else " " for c in cartao["validade"]).split() if p]
        mes = partes[0].zfill(2) if partes else ""
        ano = partes[1] if len(partes) > 1 else ""
        ano_longo = ano if len(ano) == 4 else (f"20{ano}" if ano else "")
        return {
            "numero": cartao["numero"],
            "validade": cartao["validade"],
            "mes": mes,
            "ano": ano_longo,
            "ano_curto": ano_longo[-2:],
            "cvv": cartao["cvv"],
            "titular": cartao.get("titular", ""),
        }

    def remover_cartao(self) -> bool:
        with self._trava:
            existia = self._dados.get("cartao") is not None
            self._dados["cartao"] = None
            self._salvar()
            return existia

    # ------------------------------------------------------------------ mascaramento
    def segredos(self) -> set[str]:
        """Valores que nunca devem aparecer nos registros do painel."""
        with self._trava:
            valores: set[str] = set()
            for item in self._dados["credenciais"].values():
                if item.get("senha"):
                    valores.add(str(item["senha"]))
                for nome, valor in item.get("extras", {}).items():
                    if any(p in nome.lower() for p in ("senha", "token", "chave", "secret", "key")) and valor:
                        valores.add(str(valor))
            cartao = self._dados.get("cartao")
            if cartao:
                numero = cartao["numero"]
                grupos = [numero[i : i + 4] for i in range(0, len(numero), 4)]
                valores.update({numero, " ".join(grupos), "-".join(grupos)})
            valores.update(self._temporarios)
            return valores

    def lembrar_segredo_temporario(self, valor: str) -> None:
        """Mascara nos registros uma senha recém-gerada, antes mesmo de ela ser salva."""
        with self._trava:
            self._temporarios.add(valor)

    def zerar(self) -> None:
        with self._trava:
            self._dados = {"credenciais": {}, "cartao": None, "dados": {}}
            self._salvar()
